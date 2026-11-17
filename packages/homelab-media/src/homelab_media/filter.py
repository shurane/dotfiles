"""Filtering engine for extras, featurettes, samples, auxiliary files, and .syncignore."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from homelab_media.models import MediaKind

VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mkv", ".mp4", ".avi", ".m4v", ".webm", ".ts"})

PRUNED_DIR_NAMES: frozenset[str] = frozenset(
    {
        "featurettes",
        "extras",
        "extra",
        "sample",
        "samples",
        "screens",
        "screenshots",
        "subs",
        "subtitles",
        "bonus",
        "trailers",
        "trailer",
    }
)

EXTRA_KEYWORD_RE = re.compile(
    r"(?:^|[._\-\s\[\(])(sample|trailer|promo|teaser|featurette|preview[._\-\s]+clip|exclusive[._\-\s]+clip)(?:$|[._\-\s\]\)])",
    re.IGNORECASE,
)

MIN_VALID_VIDEO_BYTES = 1 * 1024 * 1024  # 1 MiB
MIN_MOVIE_FEATURE_BYTES = 50 * 1024 * 1024  # 50 MiB


def is_pruned_dir(dirname: str) -> bool:
    """Return True if a directory name is an extras/auxiliary tree that should be pruned."""
    return dirname.strip().lower() in PRUNED_DIR_NAMES


def is_extra_or_auxiliary(
    rel_path: str | Path,
    filename: str,
    file_size: int,
    kind: MediaKind,
) -> tuple[bool, str]:
    """Determine whether a file should be skipped as an extra, sample, or non-video auxiliary file.

    Returns (should_skip, reason_code).
    """
    ext = Path(filename).suffix.lower()
    if ext not in VIDEO_EXTENSIONS:
        return True, f"NON_VIDEO_EXT:{ext or 'none'}"

    rel_parts = Path(rel_path).parts[:-1]
    for part in rel_parts:
        if is_pruned_dir(part):
            return True, f"BLACKLISTED_DIR:{part}"

    stem = Path(filename).stem
    if match := EXTRA_KEYWORD_RE.search(stem):
        return True, f"EXTRA_KEYWORD:{match.group(1).lower()}"

    if file_size < MIN_VALID_VIDEO_BYTES:
        return True, "TINY_OR_SPARSE_FILE"

    if kind == MediaKind.MOVIE and file_size < MIN_MOVIE_FEATURE_BYTES:
        return True, "SMALL_MOVIE_PROMO_OR_SAMPLE"

    return False, ""


def parse_syncignore(syncignore_path: Path) -> tuple[bool, list[str]]:
    """Parse a .syncignore file.

    Returns (ignore_entire_dir, patterns).
    An existing .syncignore with zero active patterns ignores the entire directory.
    """
    if not syncignore_path.is_file():
        return False, []

    patterns: list[str] = []
    for raw_line in syncignore_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)

    if not patterns:
        return True, []
    return False, patterns


def check_syncignore(torrent_dir: Path, rel_file_path: Path) -> tuple[bool, str]:
    """Check whether rel_file_path inside torrent_dir is excluded by .syncignore.

    Returns (is_ignored, reason).
    """
    syncignore_file = torrent_dir / ".syncignore"
    ignore_all, patterns = parse_syncignore(syncignore_file)
    if ignore_all:
        return True, "SYNCIGNORE_DIR"

    if not patterns:
        return False, ""

    rel_posix = rel_file_path.as_posix()
    name = rel_file_path.name
    for pat in patterns:
        clean_pat = pat.lstrip("/")
        if (
            fnmatch.fnmatch(rel_posix, clean_pat)
            or fnmatch.fnmatch(name, clean_pat)
            or (clean_pat.endswith("/") and rel_posix.startswith(clean_pat))
        ):
            return True, f"SYNCIGNORE_PATTERN:{pat}"

    return False, ""
