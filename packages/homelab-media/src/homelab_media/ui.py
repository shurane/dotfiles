"""Presentation helpers (formatting, LS_COLORS styling, reason labels) for the renderer."""

from __future__ import annotations

import os
from collections import defaultdict
from typing import TYPE_CHECKING

from rich.text import Text

from homelab_media.models import MediaKind

if TYPE_CHECKING:
    from rich.console import Console

    from homelab_media.models import SyncAction

# Exact reason code -> label.
_EXACT_LABELS: dict[str, str] = {
    "EXACT_EXISTING_MATCH": "existing",
    "PARSED_TITLE_YEAR": "parsed",
    "TMDB_MATCH": "tmdb",
    "SMALL_MOVIE_PROMO_OR_SAMPLE": "small promo",
    "TINY_OR_SPARSE_FILE": "<1 MiB",
    "NO_EPISODE_TAG": "no episode",
    "SYNCIGNORE_DIR": ".syncignore",
}

# "PREFIX:detail" reason code -> label template ({detail} is substituted).
_PREFIX_LABELS: dict[str, str] = {
    "BLACKLISTED_DIR": "pruned dir",
    "NON_VIDEO_EXT": "non-video",
    "EXTRA_KEYWORD": "{detail}",
    "SYNCIGNORE_PATTERN": ".syncignore ({detail})",
}


def reason_label(reason: str) -> str:
    """Convert an internal reason code into a concise human-readable label."""
    if label := _EXACT_LABELS.get(reason):
        return label
    prefix, sep, detail = reason.partition(":")
    if sep and (template := _PREFIX_LABELS.get(prefix)):
        return template.format(detail=detail)
    return reason.lower()


def format_bytes(num_bytes: int) -> str:
    """Format byte count into human-readable IEC units."""
    val = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if val < 1024.0 or unit == "TiB":
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return f"{num_bytes} B"


def format_episode_ranges(actions: list[SyncAction]) -> str:
    """Compact TV SyncActions into concise season/episode ranges (e.g. 'S01E01-E12')."""
    by_season: dict[int, list[int]] = defaultdict(list)
    extra_labels: list[str] = []
    for act in actions:
        season = act.season if act.season is not None else 1
        if isinstance(act.episode, int):
            by_season[season].append(act.episode)
        elif act.episode is not None:
            extra_labels.append(f"S{season:02d}E{act.episode}")

    def _span(start: int, end: int) -> str:
        return f"E{start:02d}-E{end:02d}" if start != end else f"E{start:02d}"

    parts: list[str] = []
    for season in sorted(by_season):
        eps = sorted(set(by_season[season]))
        ranges: list[str] = []
        start = prev = eps[0]
        for ep in eps[1:]:
            if ep != prev + 1:
                ranges.append(_span(start, prev))
                start = ep
            prev = ep
        ranges.append(_span(start, prev))
        parts.append(f"S{season:02d}{','.join(ranges)}")
    parts.extend(sorted(extra_labels))
    return ", ".join(parts) if parts else "episodes"


def relative_target_folder(act: SyncAction) -> str:
    """Return compact 'tv/<Show (Year)>' or 'movies/<Movie (Year)>' without the media root prefix."""
    if act.target_file is None:
        return "-"
    folder = act.target_file.parent.parent.name if act.kind == MediaKind.TV else act.target_file.parent.name
    return f"{act.kind.value}/{folder}"


def parse_ls_colors() -> dict[str, str]:
    """Parse LS_COLORS into a mapping of key ('di', '*.mkv', etc.) -> SGR ANSI code."""
    mapping: dict[str, str] = {}
    for entry in os.environ.get("LS_COLORS", "").split(":"):
        key, sep, val = entry.partition("=")
        if sep and key and val:
            mapping[key.lower()] = val
    return mapping


def ls_styled(
    label: str,
    ls_colors: dict[str, str],
    *,
    is_dir: bool = False,
    ext: str = "",
    fallback: str = "yellow",
) -> Text:
    """Style a path label using LS_COLORS (with fallback Rich style)."""
    sgr = ""
    if is_dir:
        sgr = ls_colors.get("di", "")
        fallback = "bold blue"
    elif ext:
        sgr = ls_colors.get(f"*{ext.lower()}", "")
    if sgr and sgr not in ("0", "00"):
        return Text.from_ansi(f"\x1b[{sgr}m{label}\x1b[0m")
    return Text(label, style=fallback)


def print_section_header(out: Console, title: str, *, style: str) -> None:
    """Print a colored section header with a subtle divider underneath."""
    out.print(f"\n[{style}]{title}[/{style}]")
    out.print(f"[dim]{'─' * len(title)}[/dim]")
