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
        subdirs: list[Path] = []
        pruned_here: list[Path] = []
        found_root_syncignore = False
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if is_pruned_dir(entry.name):
                            pruned_here.append(Path(entry.path))
                            continue
                        subdirs.append(Path(entry.path))
                    elif entry.name.endswith(PARTIAL_SUFFIXES):
                        walk.has_partial = True
                        return walk
                    elif entry.is_file(follow_symlinks=False):
                        if entry.name == ".syncignore" and current == item_path:
                            found_root_syncignore = True
                            continue
                        walk.files.append((entry, Path(entry.path).relative_to(item_path)))
        except OSError:
            continue

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


def _scan_torrent_entry(
    top_entry: os.DirEntry[str],
    *,
    kind: MediaKind,
    media_subdir: Path,
    lib_index: _LibraryIndex,
    folder_index: FolderIndex,
    tracked: bool,
    tmdb_configured: bool,
    report: GapReport,
    review_groups: dict[tuple[MediaKind, str, str], ReviewItem],
    pending_tmdb: list[_Candidate],
) -> None:
    """Inspect a single top-level torrent directory or file and populate `report`."""
    torrent_name = top_entry.name
    item_path = Path(top_entry.path)

    if top_entry.is_dir(follow_symlinks=False):
        walk = _walk_torrent(item_path)
        if walk.has_partial:
            return
        syncignore = walk.syncignore
        if syncignore is not None and syncignore.ignore_all:
            report.ignored_items.append(
                SyncAction(
                    torrent_name=torrent_name,
                    source_file=item_path / ".syncignore",
                    kind=kind,
                    action_type=ActionType.IGNORED,
                    reason=ReasonCode.SYNCIGNORE_DIR,
                    tracked_by_qbittorrent=tracked,
                )
            )
            return
    elif top_entry.is_file(follow_symlinks=False):
        walk = _TorrentWalk(files=[(top_entry, Path(top_entry.name))])
        syncignore = None
    else:
        return

    def _skip(source: Path, reason: str, size: int = 0) -> None:
        report.skipped_extras.append(
            SyncAction(
                torrent_name=torrent_name,
                source_file=source,
                kind=kind,
                action_type=ActionType.SKIP_EXTRA,
                reason=reason,
                file_size=size,
                tracked_by_qbittorrent=tracked,
            )
        )

    for pruned_dir in walk.pruned_dirs:
        _skip(pruned_dir, f"{ReasonCode.BLACKLISTED_DIR}:{pruned_dir.name}")

    torrent_meta = None
    torrent_parent: ParentResolution | None = None
    for entry, rel_path in walk.files:
        source_file = Path(entry.path)
        if entry.name == ".syncignore":
            continue

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
            continue

        if entry.inode() in lib_index.inodes:
            report.already_synced_count += 1
            continue

        # Check extension and extra keywords before touching stat() on disk.
        if name_skip := check_name_skip(rel_path, entry.name):
            _skip(source_file, name_skip)
            continue

        try:
            st = entry.stat(follow_symlinks=False)
        except OSError:
            continue

        if size_skip := check_size_skip(st.st_size, kind):
            _skip(source_file, size_skip, st.st_size)
            continue

        if torrent_meta is None:
            torrent_meta = parse_torrent_metadata(torrent_name, kind)
            if title_raw := torrent_meta.get("title"):
                # Pre-compute parent folder once for the whole torrent when title is known
                # (for movies only when year is also known; for TV whenever title is known).
                year_val = _as_int(torrent_meta.get("year"))
                if kind == MediaKind.TV or year_val is not None:
                    torrent_parent = resolve_parent_folder(
                        kind,
                        str(title_raw),
                        year_val,
                        folder_index,
                    )

        if kind == MediaKind.MOVIE:
            parsed_movie = parse_movie_target(
                torrent_name,
                entry.name,
                folder_index,
                media_subdir,
                torrent_meta=torrent_meta,
                precomputed_parent=torrent_parent,
            )
            cand = _Candidate(
                kind=kind,
                torrent_name=torrent_name,
                source_file=source_file,
                source_ino=entry.inode(),
                file_size=st.st_size,
                tracked=tracked,
                media_subdir=media_subdir,
                parent_res=parsed_movie.parent,
                target_file=parsed_movie.target_path,
            )
        else:
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
                _skip(source_file, ReasonCode.NO_EPISODE_TAG, st.st_size)
                continue
            cand = _Candidate(
                kind=kind,
                torrent_name=torrent_name,
                source_file=source_file,
                source_ino=entry.inode(),
                file_size=st.st_size,
                tracked=tracked,
                media_subdir=media_subdir,
                parent_res=parsed_tv.parent,
                target_file=parsed_tv.target_path,
                season_num=parsed_tv.season,
                ep_val=parsed_tv.episode_value,
            )

        if cand.parent_res.reason == ReasonCode.MISSING_YEAR_QUERY_TMDB and tmdb_configured:
            pending_tmdb.append(cand)
            continue

        _finalize_item(
            cand,
            target_inodes=lib_index.target_inodes,
            report=report,
            review_groups=review_groups,
            tmdb_candidates=[],
        )


def _resolve_pending_tmdb(
    pending_tmdb: list[_Candidate],
    *,
    indexed_by_kind: dict[MediaKind, _LibraryIndex],
    pool: ThreadPoolExecutor,
    tmdb: TmdbClient,
    report: GapReport,
    review_groups: dict[tuple[MediaKind, str, str], ReviewItem],
) -> None:
    """Resolve missing-year candidates against TMDB in parallel and finalize them."""
    unique_queries = {(c.kind, c.parent_res.folder_name) for c in pending_tmdb}
    tmdb_futures = {key: pool.submit(tmdb.resolve, key[0], key[1]) for key in unique_queries}
    tmdb_results = {key: fut.result() for key, fut in tmdb_futures.items()}

    for cand in pending_tmdb:
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
                    cand.season_num or 1,
                    cand.target_file.name,
                )
            assert_safe_target(cand.target_file, cand.media_subdir)

        _finalize_item(
            cand,
            target_inodes=indexed_by_kind[cand.kind].target_inodes,
            report=report,
            review_groups=review_groups,
            tmdb_candidates=tmdb_candidates,
        )


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
        torrent_by_key, in_progress_names = _index_qbittorrent(report, qb_future)

        review_groups: dict[tuple[MediaKind, str, str], ReviewItem] = {}
        pending_tmdb: list[_Candidate] = []

        for kind in (MediaKind.TV, MediaKind.MOVIE):
            torrents_subdir = config.torrents_root(kind)
            if not torrents_subdir.is_dir():
                continue
            lib_index = indexed_by_kind[kind]
            folder_index = build_folder_index(lib_index.top_folders)
            media_subdir = config.media_root(kind)

            with os.scandir(torrents_subdir) as root_it:
                top_entries = sorted(root_it, key=lambda e: e.name)

            for top_entry in top_entries:
                if top_entry.is_symlink() or top_entry.name in in_progress_names:
                    continue
                _scan_torrent_entry(
                    top_entry,
                    kind=kind,
                    media_subdir=media_subdir,
                    lib_index=lib_index,
                    folder_index=folder_index,
                    tracked=top_entry.name in torrent_by_key,
                    tmdb_configured=tmdb.is_configured,
                    report=report,
                    review_groups=review_groups,
                    pending_tmdb=pending_tmdb,
                )

        if pending_tmdb:
            _resolve_pending_tmdb(
                pending_tmdb,
                indexed_by_kind=indexed_by_kind,
                pool=pool,
                tmdb=tmdb,
                report=report,
                review_groups=review_groups,
            )

    report.scan_duration_ms = round((time.perf_counter_ns() - start_ns) / 1_000_000, 2)
    return report


def _finalize_item(
    cand: _Candidate,
    *,
    target_inodes: dict[Path, int],
    report: GapReport,
    review_groups: dict[tuple[MediaKind, str, str], ReviewItem],
    tmdb_candidates: list[TmdbMatch],
) -> None:
    """Check conflicts/confidence and append the finalized candidate to GapReport."""
    target_ino = target_inodes.get(cand.target_file)
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
        if group_key not in review_groups:
            if tmdb_candidates:
                candidates = [
                    CandidateOption(
                        option_id=f"opt-{idx}",
                        target_path=cand.media_subdir / m.folder_name,
                        description=f"TMDB match: '{m.folder_name}' (id={m.tmdb_id})",
                    )
                    for idx, m in enumerate(tmdb_candidates, start=1)
                ]
            else:
                candidates = [
                    CandidateOption(
                        option_id="opt-1",
                        target_path=cand.media_subdir / parent_res.folder_name,
                        description=f"Use proposed folder '{parent_res.folder_name}'",
                    )
                ]
                if parent_res.existing_mismatch:
                    candidates.append(
                        CandidateOption(
                            option_id="opt-2",
                            target_path=cand.media_subdir / parent_res.existing_mismatch,
                            description=f"Use existing folder '{parent_res.existing_mismatch}'",
                        )
                    )
            msg = (
                f"Structural mismatch: target '{parent_res.folder_name}' "
                f"vs existing '{parent_res.existing_mismatch}'"
                if parent_res.existing_mismatch
                else f"Missing release year for '{parent_res.folder_name}'; verify via TMDB/TVDB"
            )
            rev_item = ReviewItem(
                id=f"rev-{len(review_groups) + 1:03d}",
                torrent_name=cand.torrent_name,
                kind=cand.kind,
                issue=parent_res.reason,
                confidence=parent_res.confidence,
                message=msg,
                candidates=candidates,
                source_files=[cand.source_file],
            )
            review_groups[group_key] = rev_item
            report.flagged_for_review.append(rev_item)
        else:
            review_groups[group_key].source_files.append(cand.source_file)
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
