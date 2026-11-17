"""Rich terminal presentation for media gap reports and sync summaries."""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markup import escape
from rich.text import Text

from homelab_media.models import MediaKind, ReasonCode

if TYPE_CHECKING:
    from homelab_media.executor import ExecutionSummary
    from homelab_media.models import GapReport, SyncAction

# Exact reason code -> label.
_EXACT_LABELS: dict[str, str] = {
    ReasonCode.EXACT_EXISTING_MATCH: "existing",
    ReasonCode.PARSED_TITLE_YEAR: "parsed",
    ReasonCode.TMDB_MATCH: "tmdb",
    ReasonCode.SMALL_MOVIE_PROMO_OR_SAMPLE: "small promo",
    ReasonCode.TINY_OR_SPARSE_FILE: "<1 MiB",
    ReasonCode.NO_EPISODE_TAG: "no episode",
    ReasonCode.SYNCIGNORE_DIR: ".syncignore",
}

# "PREFIX:detail" reason code -> label template ({detail} is substituted).
_PREFIX_LABELS: dict[str, str] = {
    ReasonCode.BLACKLISTED_DIR: "pruned dir",
    ReasonCode.NON_VIDEO_EXT: "non-video",
    ReasonCode.EXTRA_KEYWORD: "{detail}",
    ReasonCode.SYNCIGNORE_PATTERN: ".syncignore ({detail})",
}

_IEC_STEP = 1024.0


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
        if val < _IEC_STEP or unit == "TiB":
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= _IEC_STEP
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


def _is_directory_action(act: SyncAction, torrent_name: str) -> bool:
    """Return True if a skipped/ignored SyncAction represents a directory entry."""
    return act.reason.startswith(f"{ReasonCode.BLACKLISTED_DIR}:") or (
        act.reason == ReasonCode.SYNCIGNORE_DIR and act.source_file.name == torrent_name
    )


def _render_ready_section(
    out: Console,
    grouped: dict[tuple[MediaKind, str, str], list[SyncAction]],
) -> None:
    """Render the Ready to Sync section (or a green no-gaps message when empty)."""
    if not grouped:
        out.print("[green]No pending media gaps detected.[/green]")
        return

    print_section_header(out, "Ready to Sync (/mnt/mango/media/...)", style="bold cyan")
    for (kind, _torrent_name, rel_target), items in sorted(grouped.items(), key=lambda kv: kv[0][2]):
        total_size = format_bytes(sum(i.file_size for i in items))
        reason = reason_label(items[0].reason)
        link_path = items[0].source_file if len(items) == 1 else items[0].source_file.parent
        file_uri = link_path.absolute().as_uri()
        segments = [f"[green]{escape(rel_target)}[/green]"]
        if kind == MediaKind.TV:
            segments.append(f"[cyan]{format_episode_ranges(items)}[/cyan]")
        segments.extend(
            [
                f"[white]{total_size}[/white]",
                f"[yellow]{reason}[/yellow]",
                f"[dim][link={file_uri}]torrent[/link][/dim]",
            ]
        )
        out.print(" / ".join(segments), soft_wrap=True, highlight=False)


def _render_skipped_section(out: Console, verbose_skipped: list[SyncAction]) -> None:
    """Render the verbose Skipped Extras & Auxiliary Files tree."""
    ls_colors = parse_ls_colors()
    skipped_by_torrent: dict[str, list[SyncAction]] = defaultdict(list)
    for sk in verbose_skipped:
        skipped_by_torrent[sk.torrent_name].append(sk)

    print_section_header(out, "Skipped Extras & Auxiliary Files", style="bold magenta")
    for torrent_name in sorted(skipped_by_torrent, key=str.lower):
        items = skipped_by_torrent[torrent_name]
        link_path = (
            items[0].source_file if items[0].source_file.name == torrent_name else items[0].source_file.parent
        )
        header_text = ls_styled(f"{torrent_name}/", ls_colors, is_dir=True)
        header_text.stylize(f"link {link_path.absolute().as_uri()}")
        out.print(header_text, soft_wrap=True, highlight=False)

        ordered = sorted(
            items,
            key=lambda s: (not _is_directory_action(s, torrent_name), s.source_file.name.lower()),
        )
        for sk in ordered:
            is_dir = _is_directory_action(sk, torrent_name)
            label = f"{sk.source_file.name}/" if is_dir else sk.source_file.name
            ext = "" if is_dir else Path(sk.source_file.name).suffix.lower()
            item_text = ls_styled(label, ls_colors, is_dir=is_dir, ext=ext)
            item_text.stylize(f"link {sk.source_file.absolute().as_uri()}")
            out.print(
                Text.assemble(
                    Text("  "),
                    item_text,
                    Text(" · ", style="dim"),
                    Text(reason_label(sk.reason), style="yellow"),
                ),
                soft_wrap=True,
                highlight=False,
            )


def render_gap_report(
    report: GapReport,
    console: Console | None = None,
    *,
    verbose: bool = False,
) -> None:
    """Render a GapReport as compact, scannable Rich output."""
    out = console or Console()
    qb_badge = "[green]online[/green]" if report.qbittorrent_online else "[yellow]offline (disk mode)[/yellow]"

    grouped: dict[tuple[MediaKind, str, str], list[SyncAction]] = defaultdict(list)
    for act in report.ready_to_sync:
        grouped[(act.kind, act.torrent_name, relative_target_folder(act))].append(act)

    unsynced_files = len(report.ready_to_sync)
    total_files = report.already_synced_count + unsynced_files
    unsynced_color = "bold cyan" if unsynced_files > 0 else "green"
    verbose_skipped = [*report.skipped_extras, *report.ignored_items]
    summary_text = (
        f"qBittorrent: {qb_badge} | "
        f"Scan: [cyan]{report.scan_duration_ms:.1f} ms[/cyan] | "
        f"Unsynced: [{unsynced_color}]{unsynced_files}/{total_files} files[/{unsynced_color}] | "
        f"Review: [bold yellow]{len(report.flagged_for_review)}[/bold yellow] | "
        f"Skipped: [dim]{len(verbose_skipped)}[/dim] | "
        f"Conflicts: [bold red]{len(report.conflicts)}[/bold red]"
    )
    out.print(f"[bold blue]homelab-media plan[/bold blue] · {summary_text}", soft_wrap=True, highlight=False)

    if report.in_progress:
        print_section_header(out, "In-Progress Torrents (Protected)", style="bold yellow")
        for item in report.in_progress:
            out.print(
                f"[yellow]{escape(item.name)}[/yellow] / [cyan]{item.progress * 100:.1f}%[/cyan] "
                f"/ [white]{escape(item.state)}[/white] / [dim]{format_bytes(item.size)}[/dim]",
                soft_wrap=True,
                highlight=False,
            )

    _render_ready_section(out, grouped)

    if report.flagged_for_review:
        print_section_header(out, "Flagged for Review (Use --resolve ID=OPT)", style="bold yellow")
        for rev in report.flagged_for_review:
            opts = " | ".join(f"[cyan]{c.option_id}[/cyan]: {escape(c.description)}" for c in rev.candidates)
            out.print(
                f"[bold yellow]{rev.id}[/bold yellow] / [white]{escape(rev.torrent_name)}[/white] "
                f"/ [yellow]{escape(rev.issue)}[/yellow] / {opts}",
                soft_wrap=True,
                highlight=False,
            )

    if report.conflicts:
        print_section_header(out, "Conflicts (Protected - Existing Target Differs)", style="bold red")
        for conf in report.conflicts:
            file_uri = conf.source_file.absolute().as_uri()
            out.print(
                f"[red]{escape(str(conf.target_file or '-'))}[/red] / [yellow]{escape(conf.reason)}[/yellow] "
                f"/ [dim][link={file_uri}]torrent[/link][/dim]",
                soft_wrap=True,
                highlight=False,
            )

    if verbose and verbose_skipped:
        _render_skipped_section(out, verbose_skipped)


def render_execution_summary(
    summary: ExecutionSummary,
    *,
    dry_run: bool,
    console: Console | None = None,
) -> None:
    """Render the result of executing hardlinks."""
    out = console or Console()
    prefix = "[dim][dry-run][/dim] " if dry_run else ""
    out.print(
        f"{prefix}Linked: [bold green]{summary.linked_count}[/bold green], "
        f"Already synced: [cyan]{summary.already_synced_count}[/cyan], "
        f"Errors: [bold red]{len(summary.errors)}[/bold red]",
    )
    for err in summary.errors:
        out.print(f"  [red]ERROR:[/red] {err}")
