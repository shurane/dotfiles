"""Media filename and directory parsing using guessit and library folder matching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from guessit import guessit  # type: ignore[import-untyped]

from homelab_media.models import MediaKind, PathTraversalSecurityError

FOLDER_YEAR_RE = re.compile(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)$")
CD_DISC_RE = re.compile(r"(?:^|[._\-\s])(cd|disc|disk)[._\-\s]?(\d+)(?:$|[._\-\s])", re.IGNORECASE)
FAST_SE_RE = re.compile(
    r"(?:^|[._\-\s\[])S(\d{1,2})E(\d{1,3})(?:-?E(\d{1,3}))?(?:$|[._\-\s\]])",
    re.IGNORECASE,
)
FAST_ANIME_EP_RE = re.compile(r"\s-\s(\d{1,3})(?:v\d)?(?:\s*[\(\[]|\s*$)")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
UNSAFE_FS_CHARS_RE = re.compile(r'[*?"<>|\x00-\x1f]')


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


def _normalize_title_key(title: str) -> str:
    """Normalize a title to lowercase alphanumeric tokens for fuzzy folder comparison."""
    return NON_ALNUM_RE.sub("", title.lower())


def sanitize_folder_name(name: str) -> str:
    """Sanitize a folder/file title for POSIX and Samba/Windows compatibility.

    Converts ':' to ' -', '/' and '\\' to '-', and strips other reserved characters.
    """
    cleaned = name.replace(":", " -").replace("/", "-").replace("\\", "-")
    cleaned = UNSAFE_FS_CHARS_RE.sub("", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" .")


def assert_safe_target(target_path: Path, media_root: Path) -> Path:
    """Verify target_path stays strictly inside media_root to prevent path traversal."""
    resolved_root = media_root.resolve()
    resolved_target = target_path.resolve()
    if not resolved_target.is_relative_to(resolved_root):
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


def resolve_parent_folder(
    _kind: MediaKind,
    parsed_title: str,
    parsed_year: int | None,
    existing_folders: set[str],
) -> ParentResolution:
    """Resolve the canonical <Title> (<Year>) parent folder against existing media directories."""
    clean_title = _smart_title_case(parsed_title)
    target_norm = _normalize_title_key(clean_title)

    # 1. Check existing media folders for exact or normalized match
    for existing in sorted(existing_folders):
        m = FOLDER_YEAR_RE.match(existing)
        if m:
            ex_title = m.group("title").strip()
            ex_year = int(m.group("year"))
            if _normalize_title_key(ex_title) == target_norm:
                if parsed_year is not None and parsed_year != ex_year:
                    proposed = f"{clean_title} ({parsed_year})"
                    return ParentResolution(
                        folder_name=proposed,
                        confidence=0.70,
                        reason="STRUCTURAL_MISMATCH",
                        existing_mismatch=existing,
                    )
                return ParentResolution(
                    folder_name=existing,
                    confidence=1.0,
                    reason="EXACT_EXISTING_MATCH",
                )
        elif _normalize_title_key(existing) == target_norm:
            if parsed_year is not None:
                proposed = f"{clean_title} ({parsed_year})"
                return ParentResolution(
                    folder_name=proposed,
                    confidence=0.70,
                    reason="STRUCTURAL_MISMATCH",
                    existing_mismatch=existing,
                )
            return ParentResolution(
                folder_name=existing,
                confidence=1.0,
                reason="EXACT_EXISTING_MATCH",
            )

    # 2. New folder with Title + Year
    if parsed_year is not None:
        return ParentResolution(
            folder_name=f"{clean_title} ({parsed_year})",
            confidence=1.0,
            reason="PARSED_TITLE_YEAR",
        )

    # 3. Missing year -> flag for TMDB/review
    return ParentResolution(
        folder_name=clean_title,
        confidence=0.70,
        reason="MISSING_YEAR_QUERY_TMDB",
    )


def movie_target_path(media_movies_dir: Path, folder_name: str, filename: str) -> Path:
    """Build `<root>/<Folder>/<Folder>[ - cdN].<ext>`; the single source of truth for movie targets."""
    path = Path(filename)
    disc_suffix = ""
    if disc_match := CD_DISC_RE.search(path.stem):
        disc_suffix = f" - cd{int(disc_match.group(2))}"
    return media_movies_dir / folder_name / f"{folder_name}{disc_suffix}{path.suffix.lower()}"


def parse_movie_target(
    torrent_name: str,
    _rel_path: str,
    filename: str,
    existing_movies: set[str],
    media_movies_dir: Path,
    *,
    torrent_meta: dict[str, Any] | None = None,
) -> MovieParseResult:
    """Parse movie title, year, and optional disc number to compute target path."""
    meta_torrent = torrent_meta if torrent_meta is not None else _guess_metadata(torrent_name, "movie")
    has_torrent_title_year = bool(meta_torrent.get("title") and meta_torrent.get("year"))
    meta_file = {} if has_torrent_title_year else _guess_metadata(filename, "movie")

    title = str(meta_torrent.get("title") or meta_file.get("title") or Path(torrent_name).stem)
    year_raw = meta_torrent.get("year") or meta_file.get("year")
    year = int(year_raw) if isinstance(year_raw, int) else None

    parent = resolve_parent_folder(MediaKind.MOVIE, title, year, existing_movies)
    target_path = movie_target_path(media_movies_dir, parent.folder_name, filename)
    assert_safe_target(target_path, media_movies_dir)

    return MovieParseResult(parent=parent, target_path=target_path)


def parse_tv_target(
    torrent_name: str,
    rel_path: str,
    filename: str,
    existing_shows: set[str],
    media_tv_dir: Path,
    *,
    torrent_meta: dict[str, Any] | None = None,
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
        ep_end_str = fast_match.group(3)
        if ep_end_str is not None:
            ep_end = int(ep_end_str)
            ep_lo, ep_hi = min(ep_start, ep_end), max(ep_start, ep_end)
            episode_tag = f"S{season:02d}E{ep_lo:02d}-E{ep_hi:02d}"
            episode_val: int | str = f"{ep_lo}-{ep_hi}"
        else:
            episode_tag = f"S{season:02d}E{ep_start:02d}"
            episode_val = ep_start
        show_title = str(meta_torrent["title"])
        year_raw = meta_torrent.get("year")
        year = int(year_raw) if isinstance(year_raw, int) else None
    elif anime_match and meta_torrent.get("title"):
        season_raw = meta_torrent.get("season")
        season = int(season_raw) if isinstance(season_raw, int) else 1
        ep_num = int(anime_match.group(1))
        episode_tag = f"S{season:02d}E{ep_num:02d}"
        episode_val = ep_num
        show_title = str(meta_torrent["title"])
        year_raw = meta_torrent.get("year")
        year = int(year_raw) if isinstance(year_raw, int) else None
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
        year_raw = meta_torrent.get("year") or meta_rel.get("year") or meta_file.get("year")
        year = int(year_raw) if isinstance(year_raw, int) else None

        season_raw = meta_file.get("season") or meta_rel.get("season") or meta_torrent.get("season")
        season = int(season_raw) if isinstance(season_raw, int) else 1

        if isinstance(episode_raw, list):
            ep_nums = [int(e) for e in episode_raw]
            ep_lo, ep_hi = min(ep_nums), max(ep_nums)
            episode_tag = f"S{season:02d}E{ep_lo:02d}-E{ep_hi:02d}"
            episode_val = f"{ep_lo}-{ep_hi}"
        else:
            ep_num = int(episode_raw)
            episode_tag = f"S{season:02d}E{ep_num:02d}"
            episode_val = ep_num

    parent = resolve_parent_folder(MediaKind.TV, show_title, year, existing_shows)
    ext = Path(filename).suffix.lower()

    season_dir = f"Season {season:02d}"
    target_path = media_tv_dir / parent.folder_name / season_dir / f"{episode_tag}{ext}"
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
            rel_path,
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
