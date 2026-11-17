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
from homelab_media.filter import is_extra_or_auxiliary, is_pruned_dir, load_syncignore
from homelab_media.models import (
    ActionType,
    CandidateOption,
    GapReport,
    MediaKind,
    ReviewItem,
    SyncAction,
    TorrentItem,
)
from homelab_media.parser import (
    ParentResolution,
    assert_safe_target,
    movie_target_path,
    parse_movie_target,
    parse_torrent_metadata,
    parse_tv_target,
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


@dataclass(slots=True)
class _PendingTmdbItem:
    kind: MediaKind
    torrent_name: str
    source_file: Path
    source_ino: int
    file_size: int
    tracked: bool
    media_subdir: Path
    parent_res: ParentResolution
    target_file: Path
    season_num: int | None
    ep_val: int | str | None


def _index_media_library(media_dir: Path) -> tuple[set[int], set[str]]:
    """Single-pass os.scandir inode index and top-level folder names for a media root."""
    inodes: set[int] = set()
    top_folders: set[str] = set()
    if not media_dir.is_dir():
        return inodes, top_folders

    stack: list[Path] = []
    with os.scandir(media_dir) as it:
        for entry in it:
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                top_folders.add(entry.name)
                stack.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                inodes.add(entry.inode())

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        inodes.add(entry.inode())
        except OSError:
            continue

    return inodes, top_folders


def _is_torrent_in_progress(torrent: TorrentItem) -> bool:
    """Return True if torrent is incomplete or in an unstable state."""
    return torrent.progress < 1.0 or torrent.state in UNSTABLE_TORRENT_STATES


PARTIAL_SUFFIXES: tuple[str, ...] = (".part", ".parts", ".!qB")


@dataclass(slots=True)
class _TorrentWalk:
    """Result of walking one torrent once."""

    files: list[tuple[os.DirEntry[str], Path]] = field(default_factory=list)
    pruned_dirs: list[Path] = field(default_factory=list)
    has_partial: bool = False
    has_syncignore: bool = False


def _walk_torrent(item_path: Path) -> _TorrentWalk:
    """Walk a torrent directory exactly once (one scandir per directory).

    Collects regular files outside pruned extras trees, records the pruned dirs, and
    aborts early if any partial-download marker is found (including inside pruned
    trees, which are scanned for markers only).
    """
    walk = _TorrentWalk()
    stack: list[tuple[Path, bool]] = [(item_path, False)]
    while stack:
        current, in_pruned = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        child_pruned = in_pruned
                        if not in_pruned and is_pruned_dir(entry.name):
                            walk.pruned_dirs.append(Path(entry.path))
                            child_pruned = True
                        stack.append((Path(entry.path), child_pruned))
                    elif entry.name.endswith(PARTIAL_SUFFIXES):
                        walk.has_partial = True
                        return walk
                    elif not in_pruned and entry.is_file(follow_symlinks=False):
                        if entry.name == ".syncignore" and current == item_path:
                            walk.has_syncignore = True
                        walk.files.append((entry, Path(entry.path).relative_to(item_path)))
        except OSError:
            continue
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


def _scan_with_clients(
    config: MediaConfig,
    report: GapReport,
    start_ns: int,
    tmdb: TmdbClient,
    *,
    qb_client: QBittorrentClient | None,
    use_qbittorrent: bool,
) -> GapReport:
    torrent_by_key: dict[str, TorrentItem] = {}
    in_progress_names: set[str] = set()
    qb_future: Future[tuple[bool, list[TorrentItem]]] | None = None

    with ThreadPoolExecutor(max_workers=4) as pool:
        if use_qbittorrent:
            client = qb_client or QBittorrentClient(
                config.qbittorrent_url,
                config.qbittorrent_user,
                config.qbittorrent_pass,
            )
            qb_future = pool.submit(client.fetch_torrents)
        else:
            report.qbittorrent_online = False

        tv_inodes, existing_shows = _index_media_library(config.media_tv_dir)
        movie_inodes, existing_movies = _index_media_library(config.media_movies_dir)

        if qb_future is not None:
            qb_online, torrents = qb_future.result()
            report.qbittorrent_online = qb_online
            for t in torrents:
                torrent_by_key[t.name] = t
                if t.content_path.name:
                    torrent_by_key[t.content_path.name] = t
                if _is_torrent_in_progress(t):
                    report.in_progress.append(t)
                    in_progress_names.add(t.name)
                    if t.content_path.name:
                        in_progress_names.add(t.content_path.name)

        review_counter = 0
        review_groups: dict[tuple[MediaKind, str, str], ReviewItem] = {}
        pending_tmdb: list[_PendingTmdbItem] = []

        for kind, torrents_subdir, media_subdir, media_inodes, existing_folders in (
            (MediaKind.TV, config.torrents_tv_dir, config.media_tv_dir, tv_inodes, existing_shows),
            (MediaKind.MOVIE, config.torrents_movies_dir, config.media_movies_dir, movie_inodes, existing_movies),
        ):
            if not torrents_subdir.is_dir():
                continue

            with os.scandir(torrents_subdir) as root_it:
                top_entries = sorted(root_it, key=lambda e: e.name)

            for top_entry in top_entries:
                if top_entry.is_symlink():
                    continue

                torrent_name = top_entry.name
                item_path = Path(top_entry.path)
                qb_item = torrent_by_key.get(torrent_name)
                tracked = qb_item is not None

                if torrent_name in in_progress_names:
                    continue
                if top_entry.is_dir(follow_symlinks=False):
                    walk = _walk_torrent(item_path)
                    if walk.has_partial:
                        continue
                    syncignore = load_syncignore(item_path) if walk.has_syncignore else None
                elif top_entry.is_file(follow_symlinks=False):
                    walk = _TorrentWalk(files=[(top_entry, Path(top_entry.name))])
                    syncignore = None
                else:
                    continue

                files, pruned_dirs = walk.files, walk.pruned_dirs
                for pruned_dir in pruned_dirs:
                    report.skipped_extras.append(
                        SyncAction(
                            torrent_name=torrent_name,
                            source_file=pruned_dir,
                            kind=kind,
                            action_type=ActionType.SKIP_EXTRA,
                            reason=f"BLACKLISTED_DIR:{pruned_dir.name}",
                            tracked_by_qbittorrent=tracked,
                        )
                    )

                torrent_meta = None
                for entry, rel_path in files:
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

                    if entry.inode() in media_inodes:
                        report.already_synced_count += 1
                        continue

                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue

                    skip, skip_reason = is_extra_or_auxiliary(rel_path, entry.name, st.st_size, kind)
                    if skip:
                        report.skipped_extras.append(
                            SyncAction(
                                torrent_name=torrent_name,
                                source_file=source_file,
                                kind=kind,
                                action_type=ActionType.SKIP_EXTRA,
                                reason=skip_reason,
                                file_size=st.st_size,
                                tracked_by_qbittorrent=tracked,
                            )
                        )
                        continue

                    if torrent_meta is None:
                        torrent_meta = parse_torrent_metadata(torrent_name, kind)

                    if kind == MediaKind.MOVIE:
                        parsed_movie = parse_movie_target(
                            torrent_name,
                            rel_path.as_posix(),
                            entry.name,
                            existing_folders,
                            media_subdir,
                            torrent_meta=torrent_meta,
                        )
                        parent_res = parsed_movie.parent
                        target_file = parsed_movie.target_path
                        season_num: int | None = None
                        ep_val: int | str | None = None
                    else:
                        parsed_tv = parse_tv_target(
                            torrent_name,
                            rel_path.as_posix(),
                            entry.name,
                            existing_folders,
                            media_subdir,
                            torrent_meta=torrent_meta,
                        )
                        if parsed_tv is None:
                            report.skipped_extras.append(
                                SyncAction(
                                    torrent_name=torrent_name,
                                    source_file=source_file,
                                    kind=kind,
                                    action_type=ActionType.SKIP_EXTRA,
                                    reason="NO_EPISODE_TAG",
                                    file_size=st.st_size,
                                    tracked_by_qbittorrent=tracked,
                                )
                            )
                            continue
                        parent_res = parsed_tv.parent
                        target_file = parsed_tv.target_path
                        season_num = parsed_tv.season
                        ep_val = parsed_tv.episode_value

                    if parent_res.reason == "MISSING_YEAR_QUERY_TMDB" and tmdb.is_configured:
                        pending_tmdb.append(
                            _PendingTmdbItem(
                                kind=kind,
                                torrent_name=torrent_name,
                                source_file=source_file,
                                source_ino=entry.inode(),
                                file_size=st.st_size,
                                tracked=tracked,
                                media_subdir=media_subdir,
                                parent_res=parent_res,
                                target_file=target_file,
                                season_num=season_num,
                                ep_val=ep_val,
                            )
                        )
                        continue

                    review_counter = _finalize_item(
                        report=report,
                        review_groups=review_groups,
                        review_counter=review_counter,
                        kind=kind,
                        torrent_name=torrent_name,
                        source_file=source_file,
                        source_ino=entry.inode(),
                        file_size=st.st_size,
                        tracked=tracked,
                        media_subdir=media_subdir,
                        parent_res=parent_res,
                        target_file=target_file,
                        season_num=season_num,
                        ep_val=ep_val,
                        tmdb_candidates=[],
                    )

        if pending_tmdb:
            unique_queries = {(item.kind, item.parent_res.folder_name) for item in pending_tmdb}
            tmdb_futures = {key: pool.submit(tmdb.resolve, key[0], key[1]) for key in unique_queries}
            tmdb_results = {key: fut.result() for key, fut in tmdb_futures.items()}

            for item in pending_tmdb:
                best_match, tmdb_candidates = tmdb_results[(item.kind, item.parent_res.folder_name)]
                parent_res = item.parent_res
                target_file = item.target_file

                if best_match is not None:
                    parent_res = ParentResolution(
                        folder_name=best_match.folder_name,
                        confidence=0.95,
                        reason="TMDB_MATCH",
                    )
                    if item.kind == MediaKind.MOVIE:
                        target_file = movie_target_path(
                            item.media_subdir, best_match.folder_name, item.source_file.name
                        )
                    else:
                        target_file = (
                            item.media_subdir
                            / best_match.folder_name
                            / f"Season {item.season_num or 1:02d}"
                            / target_file.name
                        )
                    assert_safe_target(target_file, item.media_subdir)

                review_counter = _finalize_item(
                    report=report,
                    review_groups=review_groups,
                    review_counter=review_counter,
                    kind=item.kind,
                    torrent_name=item.torrent_name,
                    source_file=item.source_file,
                    source_ino=item.source_ino,
                    file_size=item.file_size,
                    tracked=item.tracked,
                    media_subdir=item.media_subdir,
                    parent_res=parent_res,
                    target_file=target_file,
                    season_num=item.season_num,
                    ep_val=item.ep_val,
                    tmdb_candidates=tmdb_candidates,
                )

    report.scan_duration_ms = round((time.perf_counter_ns() - start_ns) / 1_000_000, 2)
    return report


def _finalize_item(
    *,
    report: GapReport,
    review_groups: dict[tuple[MediaKind, str, str], ReviewItem],
    review_counter: int,
    kind: MediaKind,
    torrent_name: str,
    source_file: Path,
    source_ino: int,
    file_size: int,
    tracked: bool,
    media_subdir: Path,
    parent_res: ParentResolution,
    target_file: Path,
    season_num: int | None,
    ep_val: int | str | None,
    tmdb_candidates: list[TmdbMatch],
) -> int:
    """Check conflicts/confidence and append the finalized item to GapReport."""
    if target_file.exists():
        try:
            target_ino = target_file.stat(follow_symlinks=False).st_ino
        except OSError:
            target_ino = -1
        if target_ino == source_ino:
            report.already_synced_count += 1
            return review_counter
        report.conflicts.append(
            SyncAction(
                torrent_name=torrent_name,
                source_file=source_file,
                target_file=target_file,
                kind=kind,
                action_type=ActionType.CONFLICT,
                reason="TARGET_EXISTS_DIFFERENT_INODE",
                file_size=file_size,
                season=season_num,
                episode=ep_val,
                tracked_by_qbittorrent=tracked,
            )
        )
        return review_counter

    if parent_res.confidence < 0.85:
        group_key = (kind, torrent_name, parent_res.reason)
        if group_key not in review_groups:
            review_counter += 1
            if tmdb_candidates:
                candidates = [
                    CandidateOption(
                        option_id=f"opt-{idx}",
                        target_path=media_subdir / m.folder_name,
                        description=f"TMDB match: '{m.folder_name}' (id={m.tmdb_id})",
                    )
                    for idx, m in enumerate(tmdb_candidates, start=1)
                ]
            else:
                candidates = [
                    CandidateOption(
                        option_id="opt-1",
                        target_path=media_subdir / parent_res.folder_name,
                        description=f"Use proposed folder '{parent_res.folder_name}'",
                    )
                ]
                if parent_res.existing_mismatch:
                    candidates.append(
                        CandidateOption(
                            option_id="opt-2",
                            target_path=media_subdir / parent_res.existing_mismatch,
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
                id=f"rev-{review_counter:03d}",
                torrent_name=torrent_name,
                kind=kind,
                issue=parent_res.reason,
                confidence=parent_res.confidence,
                message=msg,
                candidates=candidates,
                source_files=[source_file],
            )
            review_groups[group_key] = rev_item
            report.flagged_for_review.append(rev_item)
        else:
            review_groups[group_key].source_files.append(source_file)
        return review_counter

    report.ready_to_sync.append(
        SyncAction(
            torrent_name=torrent_name,
            source_file=source_file,
            target_file=target_file,
            kind=kind,
            action_type=ActionType.SYNC,
            reason=parent_res.reason,
            file_size=file_size,
            confidence=parent_res.confidence,
            season=season_num,
            episode=ep_val,
            tracked_by_qbittorrent=tracked,
        )
    )
    return review_counter
