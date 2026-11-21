"""High-performance POSIX filesystem scanner and media gap analyzer."""

from __future__ import annotations

import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from whenever import Instant

from homelab_media.clients.qbittorrent import QBittorrentClient
from homelab_media.clients.tmdb import TmdbClient, TmdbMatch
from homelab_media.filter import SyncIgnore, check_name_skip, check_size_skip, is_pruned_dir, load_syncignore
from homelab_media.models import (
    ActionType,
    CandidateOption,
    GapReport,
    MediaKind,
    ReasonCode,
    ReviewItem,
    SyncAction,
    TorrentItem,
)
from homelab_media.parser import (
    CONFIDENCE_REVIEW_THRESHOLD,
    CONFIDENCE_TMDB,
    FolderIndex,
    ParentResolution,
    _as_int,
    assert_safe_target,
    build_folder_index,
    movie_target_path,
    parse_movie_target,
    parse_torrent_metadata,
    parse_tv_target,
    resolve_parent_folder,
    tv_target_path,
)

if TYPE_CHECKING:
    from homelab_media.config import MediaConfig

UNSTABLE_TORRENT_STATES: frozenset[str] = frozenset(
    {
        "allocating",
        "checkingDL",
        "checkingResumeData",
        "checkingUP",
        "downloading",
        "forcedDL",
        "metaDL",
        "moving",
        "queuedDL",
        "stalledDL",
    }
)
PARTIAL_SUFFIXES: tuple[str, ...] = (".part", ".parts", ".!qB")


@dataclass(slots=True)
class _Candidate:
    """A parsed candidate media file awaiting conflict check, review, or TMDB resolution."""

    kind: MediaKind
    torrent_name: str
    source_file: Path
    source_ino: int
    file_size: int
    tracked: bool
    media_subdir: Path
    parent_res: ParentResolution
    target_file: Path
    season_num: int | None = None
    ep_val: int | str | None = None


@dataclass(slots=True)
class _TorrentWalk:
    """Result of walking one torrent once."""

    files: list[tuple[os.DirEntry[str], Path]] = field(default_factory=list)
    pruned_dirs: list[Path] = field(default_factory=list)
    has_partial: bool = False
    syncignore: SyncIgnore | None = None


@dataclass(slots=True)
class _LibraryIndex:
    """In-memory snapshot of a media library root (TV or movies) from a single walk."""

    inodes: set[int] = field(default_factory=set)
    top_folders: set[str] = field(default_factory=set)
    target_inodes: dict[Path, int] = field(default_factory=dict)


@dataclass(slots=True)
class _ScanContext:
    """Shared state across a single `scan_media_gaps` invocation."""

    config: MediaConfig
    report: GapReport
    tmdb: TmdbClient
    indexed_by_kind: dict[MediaKind, _LibraryIndex]
    folder_indices: dict[MediaKind, FolderIndex]
    review_groups: dict[tuple[MediaKind, str, str], ReviewItem] = field(default_factory=dict)
    pending_tmdb: list[_Candidate] = field(default_factory=list)


def _index_media_library(media_dir: Path) -> _LibraryIndex:
    """Single-pass os.scandir index of inodes, top-level folders, and target paths."""
    idx = _LibraryIndex()
    if not media_dir.is_dir():
        return idx

    stack: list[tuple[Path, bool]] = [(media_dir, True)]
    while stack:
        current, is_root = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if is_root:
                            idx.top_folders.add(entry.name)
                        stack.append((Path(entry.path), False))
                    elif entry.is_file(follow_symlinks=False):
                        ino = entry.inode()
                        idx.inodes.add(ino)
                        idx.target_inodes[Path(entry.path)] = ino
        except OSError:
            continue

    return idx


def _is_torrent_in_progress(torrent: TorrentItem) -> bool:
    """Return True if torrent is incomplete or in an unstable state."""
    return torrent.progress < 1.0 or torrent.state in UNSTABLE_TORRENT_STATES


def _scan_single_dir(
    current: Path,
    item_path: Path,
    walk: _TorrentWalk,
) -> tuple[list[Path], list[Path], bool]:
    """Scan one directory inside a torrent; returns (subdirs, pruned_dirs, found_root_syncignore)."""
    subdirs: list[Path] = []
    pruned_here: list[Path] = []
    found_root_syncignore = False
    with os.scandir(current) as it:
        for entry in it:
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                if is_pruned_dir(entry.name):
                    pruned_here.append(Path(entry.path))
                else:
                    subdirs.append(Path(entry.path))
            elif entry.name.endswith(PARTIAL_SUFFIXES):
                walk.has_partial = True
                return subdirs, pruned_here, False
            elif entry.is_file(follow_symlinks=False):
                if entry.name == ".syncignore" and current == item_path:
                    found_root_syncignore = True
                else:
                    walk.files.append((entry, Path(entry.path).relative_to(item_path)))
    return subdirs, pruned_here, found_root_syncignore


def _walk_torrent(item_path: Path) -> _TorrentWalk:
    """Walk a torrent directory once (one scandir per non-pruned directory).

    - Pruned extras directories (Extras/, Sample/, Subs/, Featurettes/, etc.) are
      recorded and skipped without opening or descending into them.
    - If a root `.syncignore` has zero patterns (`ignore_all`), short-circuits
      immediately before descending into any subdirectories.
    - Aborts early if any partial-download marker (.part, .parts, .!qB) is found.
    """
    walk = _TorrentWalk()
    stack: list[Path] = [item_path]
    while stack:
        current = stack.pop()
        try:
            subdirs, pruned_here, found_root_syncignore = _scan_single_dir(current, item_path, walk)
        except OSError:
            continue
        if walk.has_partial:
            return walk
        if found_root_syncignore:
            walk.syncignore = load_syncignore(item_path)
            if walk.syncignore is not None and walk.syncignore.ignore_all:
                walk.files.clear()
                return walk
        walk.pruned_dirs.extend(pruned_here)
        stack.extend(subdirs)
    return walk


def scan_media_gaps(
    config: MediaConfig,
    *,
    qb_client: QBittorrentClient | None = None,
    tmdb_client: TmdbClient | None = None,
    use_qbittorrent: bool = True,
) -> GapReport:
    """Scan /mnt/mango/torrents and /mnt/mango/media to identify gaps, extras, and review items."""
    start_ns = time.perf_counter_ns()
    report = GapReport(generated_at=str(Instant.now()))
    owns_tmdb = tmdb_client is None
    tmdb = tmdb_client or TmdbClient(
        api_key=config.tmdb_api_key,
        read_token=config.tmdb_read_token,
    )
    try:
        return _scan_with_clients(
            config,
            report,
            start_ns,
            tmdb,
            qb_client=qb_client,
            use_qbittorrent=use_qbittorrent,
        )
    finally:
        if owns_tmdb:
            tmdb.close()


def _index_qbittorrent(
    report: GapReport,
    qb_future: Future[tuple[bool, list[TorrentItem]]] | None,
) -> tuple[dict[str, TorrentItem], set[str]]:
    """Populate report.in_progress and return (torrent_by_key, in_progress_names)."""
    torrent_by_key: dict[str, TorrentItem] = {}
    in_progress_names: set[str] = set()
    if qb_future is None:
        report.qbittorrent_online = False
        return torrent_by_key, in_progress_names

    qb_online, torrents = qb_future.result()
    report.qbittorrent_online = qb_online
    for t in torrents:
        keys = (t.name, t.content_path.name) if t.content_path.name else (t.name,)
        for key in keys:
            torrent_by_key[key] = t
        if _is_torrent_in_progress(t):
            report.in_progress.append(t)
            in_progress_names.update(keys)
    return torrent_by_key, in_progress_names


def _build_candidate(
    ctx: _ScanContext,
    *,
    kind: MediaKind,
    torrent_name: str,
    entry: os.DirEntry[str],
    rel_path: Path,
    file_size: int,
    tracked: bool,
    torrent_meta: dict[str, object],
    torrent_parent: ParentResolution | None,
) -> _Candidate | None:
    """Parse a single video file into a `_Candidate` (or None if TV lacks an episode tag)."""
    media_subdir = ctx.config.media_root(kind)
    folder_index = ctx.folder_indices[kind]
    source_file = Path(entry.path)

    if kind == MediaKind.MOVIE:
        parsed_movie = parse_movie_target(
            torrent_name,
            entry.name,
            folder_index,
            media_subdir,
            torrent_meta=torrent_meta,
            precomputed_parent=torrent_parent,
        )
        return _Candidate(
            kind=kind,
            torrent_name=torrent_name,
            source_file=source_file,
            source_ino=entry.inode(),
            file_size=file_size,
            tracked=tracked,
            media_subdir=media_subdir,
            parent_res=parsed_movie.parent,
            target_file=parsed_movie.target_path,
        )

    parsed_tv = parse_tv_target(
        torrent_name,
        rel_path.as_posix(),
        entry.name,
        folder_index,
        media_subdir,
        torrent_meta=torrent_meta,
        precomputed_parent=torrent_parent,
    )
    if parsed_tv is None:
        return None
    return _Candidate(
        kind=kind,
        torrent_name=torrent_name,
        source_file=source_file,
        source_ino=entry.inode(),
        file_size=file_size,
        tracked=tracked,
        media_subdir=media_subdir,
        parent_res=parsed_tv.parent,
        target_file=parsed_tv.target_path,
        season_num=parsed_tv.season,
        ep_val=parsed_tv.episode_value,
    )


def _open_torrent_walk(
    top_entry: os.DirEntry[str],
    *,
    kind: MediaKind,
    tracked: bool,
    report: GapReport,
) -> _TorrentWalk | None:
    """Return a `_TorrentWalk` for `top_entry`, or None if partial, non-regular, or dir-ignored."""
    item_path = Path(top_entry.path)
    if top_entry.is_dir(follow_symlinks=False):
        walk = _walk_torrent(item_path)
        if walk.has_partial:
            return None
        if walk.syncignore is not None and walk.syncignore.ignore_all:
            report.ignored_items.append(
                SyncAction(
                    torrent_name=top_entry.name,
                    source_file=item_path / ".syncignore",
                    kind=kind,
                    action_type=ActionType.IGNORED,
                    reason=ReasonCode.SYNCIGNORE_DIR,
                    tracked_by_qbittorrent=tracked,
                )
            )
            return None
        return walk
    if top_entry.is_file(follow_symlinks=False):
        return _TorrentWalk(files=[(top_entry, Path(top_entry.name))])
    return None


def _precompute_torrent_parent(
    kind: MediaKind,
    torrent_meta: dict[str, object],
    folder_index: FolderIndex,
) -> ParentResolution | None:
    """Pre-compute parent folder once for the torrent when `torrent_meta` has a title."""
    title_raw = torrent_meta.get("title")
    if not title_raw:
        return None
    year_val = _as_int(torrent_meta.get("year"))
    if kind == MediaKind.TV or year_val is not None:
        return resolve_parent_folder(kind, str(title_raw), year_val, folder_index)
    return None


def _filter_walked_file(
    entry: os.DirEntry[str],
    rel_path: Path,
    *,
    kind: MediaKind,
    torrent_name: str,
    tracked: bool,
    syncignore: SyncIgnore | None,
    lib_index: _LibraryIndex,
    report: GapReport,
) -> int | None:
    """Filter a walked file and return its `st_size` if it is a candidate, else None."""
    source_file = Path(entry.path)
    if syncignore is not None and (ignore_reason := syncignore.match(rel_path)):
        report.ignored_items.append(
            SyncAction(
                torrent_name=torrent_name,
                source_file=source_file,
                kind=kind,
                action_type=ActionType.IGNORED,
                reason=ignore_reason,
                tracked_by_qbittorrent=tracked,
            )
        )
        return None

    if entry.inode() in lib_index.inodes:
        report.already_synced_count += 1
        return None

    if name_skip := check_name_skip(rel_path, entry.name):
        report.skipped_extras.append(
            SyncAction(
                torrent_name=torrent_name,
                source_file=source_file,
                kind=kind,
                action_type=ActionType.SKIP_EXTRA,
                reason=name_skip,
                tracked_by_qbittorrent=tracked,
            )
        )
        return None

    try:
        file_size = entry.stat(follow_symlinks=False).st_size
    except OSError:
        return None

    if size_skip := check_size_skip(file_size, kind):
        report.skipped_extras.append(
            SyncAction(
                torrent_name=torrent_name,
                source_file=source_file,
                kind=kind,
                action_type=ActionType.SKIP_EXTRA,
                reason=size_skip,
                file_size=file_size,
                tracked_by_qbittorrent=tracked,
            )
        )
        return None

    return file_size


def _scan_torrent_entry(
    ctx: _ScanContext,
    kind: MediaKind,
    top_entry: os.DirEntry[str],
    *,
    tracked: bool,
) -> None:
    """Inspect a single top-level torrent directory or file and populate `ctx.report`."""
    report = ctx.report
    walk = _open_torrent_walk(top_entry, kind=kind, tracked=tracked, report=report)
    if walk is None:
        return

    torrent_name = top_entry.name
    lib_index = ctx.indexed_by_kind[kind]
    folder_index = ctx.folder_indices[kind]

    for pruned_dir in walk.pruned_dirs:
        report.skipped_extras.append(
            SyncAction(
                torrent_name=torrent_name,
                source_file=pruned_dir,
                kind=kind,
                action_type=ActionType.SKIP_EXTRA,
                reason=f"{ReasonCode.BLACKLISTED_DIR}:{pruned_dir.name}",
                tracked_by_qbittorrent=tracked,
            )
        )

    torrent_meta: dict[str, object] | None = None
    torrent_parent: ParentResolution | None = None
    for entry, rel_path in walk.files:
        file_size = _filter_walked_file(
            entry,
            rel_path,
            kind=kind,
            torrent_name=torrent_name,
            tracked=tracked,
            syncignore=walk.syncignore,
            lib_index=lib_index,
            report=report,
        )
        if file_size is None:
            continue

        if torrent_meta is None:
            torrent_meta = parse_torrent_metadata(torrent_name, kind)
            torrent_parent = _precompute_torrent_parent(kind, torrent_meta, folder_index)

        cand = _build_candidate(
            ctx,
            kind=kind,
            torrent_name=torrent_name,
            entry=entry,
            rel_path=rel_path,
            file_size=file_size,
            tracked=tracked,
            torrent_meta=torrent_meta,
            torrent_parent=torrent_parent,
        )
        if cand is None:
            report.skipped_extras.append(
                SyncAction(
                    torrent_name=torrent_name,
                    source_file=Path(entry.path),
                    kind=kind,
                    action_type=ActionType.SKIP_EXTRA,
                    reason=ReasonCode.NO_EPISODE_TAG,
                    file_size=file_size,
                    tracked_by_qbittorrent=tracked,
                )
            )
            continue

        if cand.parent_res.reason == ReasonCode.MISSING_YEAR_QUERY_TMDB and ctx.tmdb.is_configured:
            ctx.pending_tmdb.append(cand)
            continue

        _finalize_item(ctx, cand, tmdb_candidates=[])


def _resolve_pending_tmdb(ctx: _ScanContext, pool: ThreadPoolExecutor) -> None:
    """Resolve missing-year candidates against TMDB in parallel and finalize them."""
    unique_queries = {(c.kind, c.parent_res.folder_name) for c in ctx.pending_tmdb}
    tmdb_futures = {key: pool.submit(ctx.tmdb.resolve, key[0], key[1]) for key in unique_queries}
    tmdb_results = {key: fut.result() for key, fut in tmdb_futures.items()}

    for cand in ctx.pending_tmdb:
        best_match, tmdb_candidates = tmdb_results[(cand.kind, cand.parent_res.folder_name)]
        if best_match is not None:
            cand.parent_res = ParentResolution(
                folder_name=best_match.folder_name,
                confidence=CONFIDENCE_TMDB,
                reason=ReasonCode.TMDB_MATCH,
            )
            if cand.kind == MediaKind.MOVIE:
                cand.target_file = movie_target_path(
                    cand.media_subdir, best_match.folder_name, cand.source_file.name
                )
            else:
                cand.target_file = tv_target_path(
                    cand.media_subdir,
                    best_match.folder_name,
                    cand.season_num if cand.season_num is not None else 1,
                    cand.target_file.name,
                )
            assert_safe_target(cand.target_file, cand.media_subdir)

        _finalize_item(ctx, cand, tmdb_candidates=tmdb_candidates)


def _scan_with_clients(
    config: MediaConfig,
    report: GapReport,
    start_ns: int,
    tmdb: TmdbClient,
    *,
    qb_client: QBittorrentClient | None,
    use_qbittorrent: bool,
) -> GapReport:
    qb_future: Future[tuple[bool, list[TorrentItem]]] | None = None

    with ThreadPoolExecutor(max_workers=4) as pool:
        if use_qbittorrent:
            client = qb_client or QBittorrentClient(
                config.qbittorrent_url,
                config.qbittorrent_user,
                config.qbittorrent_pass,
            )
            qb_future = pool.submit(client.fetch_torrents)

        indexed_by_kind = {
            kind: _index_media_library(config.media_root(kind))
            for kind in (MediaKind.TV, MediaKind.MOVIE)
        }
        folder_indices = {
            kind: build_folder_index(lib_idx.top_folders)
            for kind, lib_idx in indexed_by_kind.items()
        }
        torrent_by_key, in_progress_names = _index_qbittorrent(report, qb_future)
        ctx = _ScanContext(
            config=config,
            report=report,
            tmdb=tmdb,
            indexed_by_kind=indexed_by_kind,
            folder_indices=folder_indices,
        )

        for kind in (MediaKind.TV, MediaKind.MOVIE):
            torrents_subdir = config.torrents_root(kind)
            if not torrents_subdir.is_dir():
                continue

            with os.scandir(torrents_subdir) as root_it:
                top_entries = sorted(root_it, key=lambda e: e.name)

            for top_entry in top_entries:
                if top_entry.is_symlink() or top_entry.name in in_progress_names:
                    continue
                _scan_torrent_entry(ctx, kind, top_entry, tracked=top_entry.name in torrent_by_key)

        if ctx.pending_tmdb:
            _resolve_pending_tmdb(ctx, pool)

    report.scan_duration_ms = round((time.perf_counter_ns() - start_ns) / 1_000_000, 2)
    return report


def _build_review_candidates(
    cand: _Candidate,
    tmdb_candidates: list[TmdbMatch],
) -> list[CandidateOption]:
    """Build selectable resolution options for a flagged review item."""
    if tmdb_candidates:
        return [
            CandidateOption(
                option_id=f"opt-{idx}",
                target_path=cand.media_subdir / m.folder_name,
                description=f"TMDB match: '{m.folder_name}' (id={m.tmdb_id})",
            )
            for idx, m in enumerate(tmdb_candidates, start=1)
        ]

    parent_res = cand.parent_res
    options = [
        CandidateOption(
            option_id="opt-1",
            target_path=cand.media_subdir / parent_res.folder_name,
            description=f"Use proposed folder '{parent_res.folder_name}'",
        )
    ]
    if parent_res.existing_mismatch:
        options.append(
            CandidateOption(
                option_id="opt-2",
                target_path=cand.media_subdir / parent_res.existing_mismatch,
                description=f"Use existing folder '{parent_res.existing_mismatch}'",
            )
        )
    return options


def _finalize_item(
    ctx: _ScanContext,
    cand: _Candidate,
    *,
    tmdb_candidates: list[TmdbMatch],
) -> None:
    """Check conflicts/confidence and append the finalized candidate to `ctx.report`."""
    report = ctx.report
    target_ino = ctx.indexed_by_kind[cand.kind].target_inodes.get(cand.target_file)
    if target_ino is not None:
        if target_ino == cand.source_ino:
            report.already_synced_count += 1
            return
        report.conflicts.append(
            SyncAction(
                torrent_name=cand.torrent_name,
                source_file=cand.source_file,
                target_file=cand.target_file,
                kind=cand.kind,
                action_type=ActionType.CONFLICT,
                reason=ReasonCode.TARGET_EXISTS_DIFFERENT_INODE,
                file_size=cand.file_size,
                season=cand.season_num,
                episode=cand.ep_val,
                tracked_by_qbittorrent=cand.tracked,
            )
        )
        return

    parent_res = cand.parent_res
    if parent_res.confidence < CONFIDENCE_REVIEW_THRESHOLD:
        group_key = (cand.kind, cand.torrent_name, parent_res.reason)
        if group_key not in ctx.review_groups:
            msg = (
                f"Structural mismatch: target '{parent_res.folder_name}' "
                f"vs existing '{parent_res.existing_mismatch}'"
                if parent_res.existing_mismatch
                else f"Missing release year for '{parent_res.folder_name}'; verify via TMDB/TVDB"
            )
            rev_item = ReviewItem(
                id=f"rev-{len(ctx.review_groups) + 1:03d}",
                torrent_name=cand.torrent_name,
                kind=cand.kind,
                issue=parent_res.reason,
                confidence=parent_res.confidence,
                message=msg,
                candidates=_build_review_candidates(cand, tmdb_candidates),
                source_files=[cand.source_file],
            )
            ctx.review_groups[group_key] = rev_item
            report.flagged_for_review.append(rev_item)
        else:
            ctx.review_groups[group_key].source_files.append(cand.source_file)
        return

    report.ready_to_sync.append(
        SyncAction(
            torrent_name=cand.torrent_name,
            source_file=cand.source_file,
            target_file=cand.target_file,
            kind=cand.kind,
            action_type=ActionType.SYNC,
            reason=parent_res.reason,
            file_size=cand.file_size,
            confidence=parent_res.confidence,
            season=cand.season_num,
            episode=cand.ep_val,
            tracked_by_qbittorrent=cand.tracked,
        )
    )
