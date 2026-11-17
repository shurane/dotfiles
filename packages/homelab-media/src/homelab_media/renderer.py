"""Rich terminal presentation for media gap reports and sync summaries."""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markup import escape
from rich.text import Text

from homelab_media.models import MediaKind

if TYPE_CHECKING:
    from homelab_media.executor import ExecutionSummary
    from homelab_media.models import GapReport, SyncAction

REASON_LABELS: dict[str, str] = {
    "EXACT_EXISTING_MATCH": "existing",
    "PARSED_TITLE_YEAR": "parsed",
    "TMDB_MATCH": "tmdb",
}


def _format_bytes(num_bytes: int) -> str:
    """Format byte count into human-readable IEC units."""
    val = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if val < 1024.0 or unit == "TiB":
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return f"{num_bytes} B"


def _format_episode_ranges(actions: list[SyncAction]) -> str:
    """Compact TV SyncActions into concise season/episode ranges (e.g. 'S01E01-E12')."""
    by_season: dict[int, list[int]] = defaultdict(list)
    extra_labels: list[str] = []

    for act in actions:
        season = act.season if act.season is not None else 1
        if isinstance(act.episode, int):
            by_season[season].append(act.episode)
        elif act.episode is not None:
            extra_labels.append(f"S{season:02d}E{act.episode}")

    parts: list[str] = []
    for season in sorted(by_season):
        eps = sorted(set(by_season[season]))
        ranges: list[str] = []
        start = prev = eps[0]
        for ep in eps[1:]:
            if ep == prev + 1:
                prev = ep
            else:
                ranges.append(f"E{start:02d}-E{prev:02d}" if start != prev else f"E{start:02d}")
                start = prev = ep
        ranges.append(f"E{start:02d}-E{prev:02d}" if start != prev else f"E{start:02d}")
        parts.append(f"S{season:02d}{','.join(ranges)}")

    parts.extend(sorted(extra_labels))
    return ", ".join(parts) if parts else "episodes"


def _relative_target_folder(act: SyncAction) -> str:
    """Return compact 'tv/<Show (Year)>' or 'movies/<Movie (Year)>' without /mnt/mango/media prefix."""
    if act.target_file is None:
        return "-"
    folder = act.target_file.parent.parent.name if act.kind == MediaKind.TV else act.target_file.parent.name
    return f"{act.kind.value}/{folder}"


def _parse_ls_colors() -> dict[str, str]:
    """Parse LS_COLORS into a mapping of key ('di', '*.mkv', etc.) -> SGR ANSI code."""
    raw = os.environ.get("LS_COLORS", "")
    mapping: dict[str, str] = {}
    for entry in raw.split(":"):
        if "=" in entry:
            key, val = entry.split("=", 1)
            if key and val:
                mapping[key.lower()] = val
    return mapping


def _ls_styled(
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


def _skipped_reason_label(reason: str) -> str:
    """Convert an internal skip reason code into a concise human-readable label."""
    if reason.startswith("BLACKLISTED_DIR:"):
        return "pruned dir"
    if reason.startswith("NON_VIDEO_EXT:"):
        return "non-video"
    if reason.startswith("EXTRA_KEYWORD:"):
        return reason.split(":", 1)[1]
    if reason == "SMALL_MOVIE_PROMO_OR_SAMPLE":
        return "small promo"
    if reason == "TINY_OR_SPARSE_FILE":
        return "<1 MiB"
    if reason == "NO_EPISODE_TAG":
        return "no episode"
    return reason.lower()


def _print_section_header(out: Console, title: str, *, style: str) -> None:
    """Print a colored section header with a subtle divider underneath."""
    out.print(f"\n[{style}]{title}[/{style}]")
    out.print(f"[dim]{'─' * len(title)}[/dim]")


def render_gap_report(
    report: GapReport,
    console: Console | None = None,
    *,
    verbose: bool = False,
) -> None:
    """Render a GapReport as compact, scannable Rich panels and tables."""
    out = console or Console()
    qb_badge = "[green]online[/green]" if report.qbittorrent_online else "[yellow]offline (disk mode)[/yellow]"

    grouped: dict[tuple[MediaKind, str, str], list[SyncAction]] = defaultdict(list)
    for act in report.ready_to_sync:
        grouped[(act.kind, act.torrent_name, _relative_target_folder(act))].append(act)

    synced_files = report.already_synced_count
    total_files = synced_files + len(report.ready_to_sync)
    summary_text = (
        f"qBittorrent: {qb_badge} | "
        f"Scan: [cyan]{report.scan_duration_ms:.1f} ms[/cyan] | "
        f"Synced: [green]{synced_files}/{total_files} files[/green] | "
        f"Review: [bold yellow]{len(report.flagged_for_review)}[/bold yellow] | "
        f"Extras skipped: [dim]{len(report.skipped_extras)}[/dim] | "
        f"Conflicts: [bold red]{len(report.conflicts)}[/bold red]"
    )
    out.print(f"[bold blue]homelab-media plan[/bold blue] · {summary_text}", soft_wrap=True, highlight=False)

    if report.in_progress:
        _print_section_header(out, "In-Progress Torrents (Protected)", style="bold yellow")
        for item in report.in_progress:
            out.print(
                f"[yellow]{escape(item.name)}[/yellow] / [cyan]{item.progress * 100:.1f}%[/cyan] "
                f"/ [white]{escape(item.state)}[/white] / [dim]{_format_bytes(item.size)}[/dim]",
                soft_wrap=True,
                highlight=False,
            )

    if grouped:
        _print_section_header(out, "Ready to Sync (/mnt/mango/media/...)", style="bold cyan")
        for (kind, _torrent_name, rel_target), items in sorted(grouped.items(), key=lambda kv: kv[0][2]):
            total_size = _format_bytes(sum(i.file_size for i in items))
            reason = REASON_LABELS.get(items[0].reason, items[0].reason.lower())
            link_path = items[0].source_file if len(items) == 1 else items[0].source_file.parent
            file_uri = link_path.absolute().as_uri()
            segments = [f"[green]{escape(rel_target)}[/green]"]
            if kind == MediaKind.TV:
                segments.append(f"[cyan]{_format_episode_ranges(items)}[/cyan]")
            segments.extend(
                [
                    f"[white]{total_size}[/white]",
                    f"[yellow]{reason}[/yellow]",
                    f"[dim][link={file_uri}]torrent[/link][/dim]",
                ]
            )
            out.print(" / ".join(segments), soft_wrap=True, highlight=False)
    else:
        out.print("[green]No pending media gaps detected.[/green]")

    if report.flagged_for_review:
        _print_section_header(out, "Flagged for Review (Use --resolve ID=OPT)", style="bold yellow")
        for rev in report.flagged_for_review:
            opts = " | ".join(f"[cyan]{c.option_id}[/cyan]: {escape(c.description)}" for c in rev.candidates)
            out.print(
                f"[bold yellow]{rev.id}[/bold yellow] / [white]{escape(rev.torrent_name)}[/white] "
                f"/ [yellow]{escape(rev.issue)}[/yellow] / {opts}",
                soft_wrap=True,
                highlight=False,
            )

    if report.conflicts:
        _print_section_header(out, "Conflicts (Protected - Existing Target Differs)", style="bold red")
        for conf in report.conflicts:
            file_uri = conf.source_file.absolute().as_uri()
            out.print(
                f"[red]{escape(str(conf.target_file or '-'))}[/red] / [yellow]{escape(conf.reason)}[/yellow] "
                f"/ [dim][link={file_uri}]torrent[/link][/dim]",
                soft_wrap=True,
                highlight=False,
            )

    if verbose and report.skipped_extras:
        ls_colors = _parse_ls_colors()
        skipped_by_torrent: dict[str, list[SyncAction]] = defaultdict(list)
        for sk in report.skipped_extras:
            skipped_by_torrent[sk.torrent_name].append(sk)

        _print_section_header(out, "Skipped Extras & Auxiliary Files", style="bold magenta")
        for torrent_name in sorted(skipped_by_torrent, key=str.lower):
            items = skipped_by_torrent[torrent_name]
            link_path = (
                items[0].source_file
                if items[0].source_file.name == torrent_name
                else items[0].source_file.parent
            )
            file_uri = link_path.absolute().as_uri()
            header_text = _ls_styled(f"{torrent_name}/", ls_colors, is_dir=True)
            header_text.stylize(f"link {file_uri}")
            out.print(header_text, soft_wrap=True, highlight=False)

            dir_items = sorted(
                (sk for sk in items if sk.reason.startswith("BLACKLISTED_DIR:")),
                key=lambda s: s.source_file.name.lower(),
            )
            file_items = sorted(
                (sk for sk in items if not sk.reason.startswith("BLACKLISTED_DIR:")),
                key=lambda s: s.source_file.name.lower(),
            )
            for sk in [*dir_items, *file_items]:
                is_dir = sk.reason.startswith("BLACKLISTED_DIR:")
                label = f"{sk.source_file.name}/" if is_dir else sk.source_file.name
                ext = "" if is_dir else Path(sk.source_file.name).suffix.lower()
                reason_label = _skipped_reason_label(sk.reason)
                item_text = _ls_styled(label, ls_colors, is_dir=is_dir, ext=ext)
                item_text.stylize(f"link {sk.source_file.absolute().as_uri()}")
                out.print(
                    Text.assemble(
                        Text("  "),
                        item_text,
                        Text(" · ", style="dim"),
                        Text(reason_label, style="yellow"),
                    ),
                    soft_wrap=True,
                    highlight=False,
                )


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
        f"Errors: [bold red]{len(summary.errors)}[/bold red]"
    )
    for err in summary.errors:
        out.print(f"  [red]ERROR:[/red] {err}")
