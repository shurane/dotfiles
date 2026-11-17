"""Media filename and directory parsing using guessit and library folder matching."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

from guessit import guessit  # type: ignore[import-untyped]

from homelab_media.models import MediaKind, PathTraversalSecurityError, ReasonCode

FOLDER_YEAR_RE = re.compile(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)$")
CD_DISC_RE = re.compile(r"(?:^|[._\-\s])(cd|disc|disk)[._\-\s]?(\d+)(?:$|[._\-\s])", re.IGNORECASE)
FAST_SE_RE = re.compile(
    r"(?:^|[._\-\s\[])S(\d{1,2})E(\d{1,3})(?:-?E(\d{1,3}))?(?:$|[._\-\s\]])",
    re.IGNORECASE,
)
FAST_ANIME_EP_RE = re.compile(r"\s-\s(\d{1,3})(?:v\d)?(?:\s*[\(\[]|\s*$)")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
UNSAFE_FS_CHARS_RE = re.compile(r'[*?"<>|\x00-\x1f]')

CONFIDENCE_EXACT = 1.0
CONFIDENCE_TMDB = 0.95
CONFIDENCE_REVIEW_THRESHOLD = 0.85
CONFIDENCE_NEEDS_REVIEW = 0.70

FolderIndex = dict[str, tuple[str, int | None]]


def _as_int(val: object) -> int | None:
    """Return int(val) if val is an int, else None."""
    return int(val) if isinstance(val, int) else None


@dataclass(frozen=True, slots=True)
class ParentResolution:
    """Result of resolving a media item's destination parent directory."""

    folder_name: str
    confidence: float
    reason: str
    existing_mismatch: str | None = None


@dataclass(frozen=True, slots=True)
class MovieParseResult:
    """Parsed destination details for a movie file."""

    parent: ParentResolution
    target_path: Path


@dataclass(frozen=True, slots=True)
class TVParseResult:
    """Parsed destination details for a TV episode file."""

    parent: ParentResolution
    season: int
    episode_label: str
    episode_value: int | str
    target_path: Path


def normalize_title_key(title: str) -> str:
    """Normalize a title to lowercase alphanumeric tokens for fuzzy folder comparison."""
    return NON_ALNUM_RE.sub("", title.lower())


def sanitize_folder_name(name: str) -> str:
    """Sanitize a folder/file title for POSIX and Samba/Windows compatibility.

    Converts ':' to ' -', '/' and '\\' to '-', and strips other reserved characters.
    """
    cleaned = name.replace(":", " -").replace("/", "-").replace("\\", "-")
    cleaned = UNSAFE_FS_CHARS_RE.sub("", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" .")


def assert_safe_target(
    target_path: Path,
    media_root: Path,
    *,
    follow_symlinks: bool = False,
) -> Path:
    """Verify target_path stays strictly inside media_root to prevent path traversal.

    By default performs a pure lexical normalization check (zero filesystem lstat syscalls)
    suitable for scanning thousands of candidate targets. Pass `follow_symlinks=True` at
    execution time (before os.link) to also resolve any symlinks on disk.
    """
    target_str = str(target_path)
    root_str = str(media_root)
    if "\x00" in target_str or "\x00" in root_str:
        msg = "Target or root path contains NUL byte"
        raise PathTraversalSecurityError(msg)

    if follow_symlinks:
        resolved_root = media_root.resolve()
        resolved_target = target_path.resolve()
    else:
        resolved_root = Path(os.path.abspath(root_str))  # noqa: PTH100
        resolved_target = Path(os.path.abspath(target_str))  # noqa: PTH100

    if resolved_target == resolved_root or not resolved_target.is_relative_to(resolved_root):
        msg = f"Target path {resolved_target} escapes media root {resolved_root}"
        raise PathTraversalSecurityError(msg)
    return resolved_target


def _smart_title_case(title: str) -> str:
    """Preserve existing casing/punctuation from guessit while cleaning dots/underscores."""
    cleaned = title.replace("_", " ").strip()
    if "." in cleaned and " " not in cleaned:
        cleaned = cleaned.replace(".", " ")
    return sanitize_folder_name(cleaned)


def _guess_metadata(input_str: str, media_type: str) -> dict[str, Any]:
    """Run guessit with explicit media type ('movie' or 'episode')."""
    result = dict(guessit(input_str, {"type": media_type}))
    rg = result.get("release_group")
    title = result.get("title")
    if isinstance(rg, str) and isinstance(title, str) and rg and title:
        # Guard against guessit misclassifying the first word of a hyphenated title
        # (e.g., "Wreck-It.Ralph" -> release_group="Wreck", title="It Ralph") as a prefix group.
        base_name = Path(input_str).name
        first_word = title.split()[0]
        if re.match(rf"^{re.escape(rg)}-{re.escape(first_word)}", base_name, re.IGNORECASE):
            result["title"] = f"{rg}-{title}"
            result.pop("release_group", None)
    return result


def parse_torrent_metadata(torrent_name: str, kind: MediaKind) -> dict[str, Any]:
    """Parse a torrent's top-level name once so all files inside reuse the result."""
    media_type = "movie" if kind == MediaKind.MOVIE else "episode"
    return _guess_metadata(torrent_name, media_type)


def build_folder_index(existing_folders: Iterable[str]) -> FolderIndex:
    """Pre-compute normalized title -> (folder_name, year) for O(1) parent matching.

    Iterates in sorted order and keeps the first match per normalized title, matching
    the deterministic precedence of the linear scan.
    """
    index: FolderIndex = {}
    for existing in sorted(existing_folders):
        m = FOLDER_YEAR_RE.match(existing)
        if m:
            norm = normalize_title_key(m.group("title").strip())
            year: int | None = int(m.group("year"))
        else:
            norm = normalize_title_key(existing)
            year = None
        if norm not in index:
            index[norm] = (existing, year)
    return index


def resolve_parent_folder(
    _kind: MediaKind,
    parsed_title: str,
    parsed_year: int | None,
    existing_folders: set[str] | FolderIndex,
) -> ParentResolution:
    """Resolve the canonical <Title> (<Year>) parent folder against existing media directories."""
    clean_title = _smart_title_case(parsed_title)
    target_norm = normalize_title_key(clean_title)

    index = existing_folders if isinstance(existing_folders, dict) else build_folder_index(existing_folders)

    # 1. Check existing media folders for O(1) normalized match
    if match := index.get(target_norm):
        existing, ex_year = match
        if parsed_year is not None and ex_year != parsed_year:
            return ParentResolution(
                folder_name=f"{clean_title} ({parsed_year})",
                confidence=CONFIDENCE_NEEDS_REVIEW,
                reason=ReasonCode.STRUCTURAL_MISMATCH,
                existing_mismatch=existing,
            )
        return ParentResolution(
            folder_name=existing,
            confidence=CONFIDENCE_EXACT,
            reason=ReasonCode.EXACT_EXISTING_MATCH,
        )

    # 2. New folder with Title + Year
    if parsed_year is not None:
        return ParentResolution(
            folder_name=f"{clean_title} ({parsed_year})",
            confidence=CONFIDENCE_EXACT,
            reason=ReasonCode.PARSED_TITLE_YEAR,
        )

    # 3. Missing year -> flag for TMDB/review
    return ParentResolution(
        folder_name=clean_title,
        confidence=CONFIDENCE_NEEDS_REVIEW,
        reason=ReasonCode.MISSING_YEAR_QUERY_TMDB,
    )


def movie_target_path(media_movies_dir: Path, folder_name: str, filename: str) -> Path:
    """Build `<root>/<Folder>/<Folder>[ - cdN].<ext>`; the single source of truth for movie targets."""
    path = Path(filename)
    disc_suffix = ""
    if disc_match := CD_DISC_RE.search(path.stem):
        disc_suffix = f" - cd{int(disc_match.group(2))}"
    return media_movies_dir / folder_name / f"{folder_name}{disc_suffix}{path.suffix.lower()}"


def tv_target_path(media_tv_dir: Path, folder_name: str, season: int, episode_filename: str) -> Path:
    """Build `<root>/<Folder>/Season NN/<episode_filename>`; the single source of truth for TV targets."""
    return media_tv_dir / folder_name / f"Season {season:02d}" / episode_filename


def _format_episode_tag(season: int, ep_start: int, ep_end: int | None = None) -> tuple[str, int | str]:
    """Format `(episode_tag, episode_value)` for single or multi-episode TV files."""
    if ep_end is not None and ep_end != ep_start:
        ep_lo, ep_hi = min(ep_start, ep_end), max(ep_start, ep_end)
        return f"S{season:02d}E{ep_lo:02d}-E{ep_hi:02d}", f"{ep_lo}-{ep_hi}"
    return f"S{season:02d}E{ep_start:02d}", ep_start


def parse_movie_target(
    torrent_name: str,
    filename: str,
    existing_movies: set[str] | FolderIndex,
    media_movies_dir: Path,
    *,
    torrent_meta: dict[str, Any] | None = None,
    precomputed_parent: ParentResolution | None = None,
) -> MovieParseResult:
    """Parse movie title, year, and optional disc number to compute target path."""
    if precomputed_parent is not None:
        parent = precomputed_parent
    else:
        meta_torrent = torrent_meta if torrent_meta is not None else _guess_metadata(torrent_name, "movie")
        has_torrent_title_year = bool(meta_torrent.get("title") and meta_torrent.get("year"))
        meta_file = {} if has_torrent_title_year else _guess_metadata(filename, "movie")

        title = str(meta_torrent.get("title") or meta_file.get("title") or Path(torrent_name).stem)
        year = _as_int(meta_torrent.get("year") or meta_file.get("year"))
        parent = resolve_parent_folder(MediaKind.MOVIE, title, year, existing_movies)

    target_path = movie_target_path(media_movies_dir, parent.folder_name, filename)
    assert_safe_target(target_path, media_movies_dir)

    return MovieParseResult(parent=parent, target_path=target_path)


def parse_tv_target(
    torrent_name: str,
    rel_path: str,
    filename: str,
    existing_shows: set[str] | FolderIndex,
    media_tv_dir: Path,
    *,
    torrent_meta: dict[str, Any] | None = None,
    precomputed_parent: ParentResolution | None = None,
) -> TVParseResult | None:
    """Parse TV show title, season, and episode(s) to compute target path.

    Returns None if the file lacks episode identifiers (e.g. a stray promo clip).
    """
    meta_torrent = torrent_meta if torrent_meta is not None else _guess_metadata(torrent_name, "episode")

    # Fast-path: if torrent_meta already resolved show title, extract SxxExx or anime "- NN"
    # via regex without calling guessit() on every individual episode file.
    stem = Path(filename).stem
    has_subdir = "/" in rel_path.replace("\\", "/")
    fast_match = FAST_SE_RE.search(stem)
    anime_match = None if (fast_match or has_subdir) else FAST_ANIME_EP_RE.search(stem)

    if fast_match and meta_torrent.get("title"):
        season = int(fast_match.group(1))
        ep_start = int(fast_match.group(2))
        ep_end = int(fast_match.group(3)) if fast_match.group(3) is not None else None
        episode_tag, episode_val = _format_episode_tag(season, ep_start, ep_end)
        show_title = str(meta_torrent["title"])
        year = _as_int(meta_torrent.get("year"))
    elif anime_match and meta_torrent.get("title"):
        season = _as_int(meta_torrent.get("season")) or 1
        episode_tag, episode_val = _format_episode_tag(season, int(anime_match.group(1)))
        show_title = str(meta_torrent["title"])
        year = _as_int(meta_torrent.get("year"))
    else:
        meta_file = _guess_metadata(filename, "episode")

        # Only parse rel_path when the file is nested in subdirectories (e.g. Season 06/ep01.mkv)
        meta_rel = _guess_metadata(rel_path, "episode") if has_subdir else meta_file

        episode_raw = meta_file.get("episode") or meta_rel.get("episode")
        if episode_raw is None:
            return None

        show_title = str(
            meta_torrent.get("title") or meta_rel.get("title") or meta_file.get("title") or Path(torrent_name).stem
        )
        year = _as_int(meta_torrent.get("year") or meta_rel.get("year") or meta_file.get("year"))
        season = _as_int(meta_file.get("season") or meta_rel.get("season") or meta_torrent.get("season")) or 1

        if isinstance(episode_raw, list):
            ep_nums = [int(e) for e in episode_raw]
            episode_tag, episode_val = _format_episode_tag(season, min(ep_nums), max(ep_nums))
        else:
            episode_tag, episode_val = _format_episode_tag(season, int(episode_raw))

    parent = (
        precomputed_parent
        if precomputed_parent is not None
        else resolve_parent_folder(MediaKind.TV, show_title, year, existing_shows)
    )
    ext = Path(filename).suffix.lower()

    target_path = tv_target_path(media_tv_dir, parent.folder_name, season, f"{episode_tag}{ext}")
    assert_safe_target(target_path, media_tv_dir)

    return TVParseResult(
        parent=parent,
        season=season,
        episode_label=episode_tag,
        episode_value=episode_val,
        target_path=target_path,
    )


def resolve_target_with_folder(
    kind: MediaKind,
    torrent_name: str,
    rel_path: str,
    filename: str,
    chosen_folder: str,
    media_subdir: Path,
) -> tuple[Path, int | None, int | str | None] | None:
    """Resolve a target path inside an explicitly chosen parent folder (used by --resolve)."""
    safe_folder = sanitize_folder_name(chosen_folder)
    if kind == MediaKind.MOVIE:
        parsed_m = parse_movie_target(
            torrent_name,
            filename,
            {safe_folder},
            media_subdir,
        )
        return parsed_m.target_path, None, None

    parsed_t = parse_tv_target(
        torrent_name,
        rel_path,
        filename,
        {safe_folder},
        media_subdir,
    )
    if parsed_t is None:
        return None
    return parsed_t.target_path, parsed_t.season, parsed_t.episode_value
