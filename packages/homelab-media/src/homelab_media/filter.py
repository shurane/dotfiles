"""Filtering engine for extras, featurettes, samples, auxiliary files, and .syncignore."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

from homelab_media.models import MediaKind, ReasonCode

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


def check_name_skip(rel_path: str | Path, filename: str) -> str:
    """Return a skip reason if the path/filename can be skipped without calling stat(), else ''."""
    ext = Path(filename).suffix.lower()
    if ext not in VIDEO_EXTENSIONS:
        return f"{ReasonCode.NON_VIDEO_EXT}:{ext or 'none'}"

    for part in Path(rel_path).parts[:-1]:
        if is_pruned_dir(part):
            return f"{ReasonCode.BLACKLISTED_DIR}:{part}"

    if match := EXTRA_KEYWORD_RE.search(Path(filename).stem):
        return f"{ReasonCode.EXTRA_KEYWORD}:{match.group(1).lower()}"

    return ""


def check_size_skip(file_size: int, kind: MediaKind) -> str:
    """Return a skip reason if the video file size is below minimum thresholds, else ''."""
    if file_size < MIN_VALID_VIDEO_BYTES:
        return ReasonCode.TINY_OR_SPARSE_FILE

    if kind == MediaKind.MOVIE and file_size < MIN_MOVIE_FEATURE_BYTES:
        return ReasonCode.SMALL_MOVIE_PROMO_OR_SAMPLE

    return ""


def is_extra_or_auxiliary(
    rel_path: str | Path,
    filename: str,
    file_size: int,
    kind: MediaKind,
) -> tuple[bool, str]:
    """Determine whether a file should be skipped as an extra, sample, or non-video auxiliary file.

    Returns (should_skip, reason_code).
    """
    reason = check_name_skip(rel_path, filename) or check_size_skip(file_size, kind)
    return bool(reason), reason


@dataclass(frozen=True, slots=True)
class SyncIgnore:
    """A parsed .syncignore. An existing file with zero active patterns ignores the whole directory."""

    patterns: tuple[str, ...] = ()

    @property
    def ignore_all(self) -> bool:
        return not self.patterns

    def match(self, rel_file_path: Path) -> str:
        """Return the ignore reason code for rel_file_path, or '' if it is not ignored."""
        if self.ignore_all:
            return ReasonCode.SYNCIGNORE_DIR
        rel_posix = rel_file_path.as_posix()
        name = rel_file_path.name
        for pat in self.patterns:
            clean_pat = pat.lstrip("/")
            if (
                fnmatch.fnmatch(rel_posix, clean_pat)
                or fnmatch.fnmatch(name, clean_pat)
                or (clean_pat.endswith("/") and rel_posix.startswith(clean_pat))
            ):
                return f"{ReasonCode.SYNCIGNORE_PATTERN}:{pat}"
        return ""


def load_syncignore(torrent_dir: Path) -> SyncIgnore | None:
    """Read torrent_dir/.syncignore once. Returns None when the file does not exist."""
    try:
        text = (torrent_dir / ".syncignore").read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        return None
    lines = (raw.strip() for raw in text.splitlines())
    return SyncIgnore(tuple(line for line in lines if line and not line.startswith("#")))


def parse_syncignore(syncignore_path: Path) -> tuple[bool, list[str]]:
    """Parse a .syncignore file.

    Returns (ignore_entire_dir, patterns).
    An existing .syncignore with zero active patterns ignores the entire directory.
    """
    parsed = load_syncignore(syncignore_path.parent) if syncignore_path.name == ".syncignore" else None
    if parsed is None:
        return False, []
    return parsed.ignore_all, list(parsed.patterns)


def check_syncignore(torrent_dir: Path, rel_file_path: Path) -> tuple[bool, str]:
    """Check whether rel_file_path inside torrent_dir is excluded by .syncignore.

    Returns (is_ignored, reason). Prefer load_syncignore() + SyncIgnore.match() when
    checking many files from one directory so the file is only read once.
    """
    syncignore = load_syncignore(torrent_dir)
    reason = syncignore.match(rel_file_path) if syncignore else ""
    return bool(reason), reason
