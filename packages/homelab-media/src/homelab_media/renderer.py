"""Rich terminal presentation for media gap reports and sync summaries."""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
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


def _format_skipped_summary(items: list[SyncAction], ls_colors: dict[str, str]) -> Text:
    """Summarize skipped extras/auxiliary items sorted directories-first with LS_COLORS."""
    dir_items: list[SyncAction] = []
    named_items: list[SyncAction] = []
    non_video_exts: set[str] = set()
    non_video_count = 0

    for sk in items:
        if sk.reason.startswith("NON_VIDEO_EXT:"):
            ext = sk.reason.split(":", 1)[1]
            non_video_exts.add(ext)
            non_video_count += 1
        elif sk.reason.startswith("BLACKLISTED_DIR:"):
            dir_items.append(sk)
        else:
            named_items.append(sk)

    dir_items.sort(key=lambda s: s.source_file.name.lower())
    named_items.sort(key=lambda s: s.source_file.name.lower())

    tokens: list[Text] = []
    for sk in dir_items:
        t = _ls_styled(f"{sk.source_file.name}/", ls_colors, is_dir=True)
        t.append(" (dir)", style="dim")
        tokens.append(t)

    for sk in named_items:
        ext = Path(sk.source_file.name).suffix.lower()
        if sk.reason.startswith("EXTRA_KEYWORD:"):
            tag = sk.reason.split(":", 1)[1]
        elif sk.reason == "SMALL_MOVIE_PROMO_OR_SAMPLE":
            tag = "promo"
        elif sk.reason == "TINY_OR_SPARSE_FILE":
            tag = "<1 MiB"
        elif sk.reason == "NO_EPISODE_TAG":
            tag = "no episode"
        else:
            tag = sk.reason.lower()
        t = _ls_styled(sk.source_file.name, ls_colors, ext=ext)
        t.append(f" ({tag})", style="dim")
        tokens.append(t)

    if non_video_count > 0:
        ext_list = sorted(non_video_exts)
        ext_text = Text(f"{non_video_count}x (", style="yellow")
        for idx, ext in enumerate(ext_list):
            if idx > 0:
                ext_text.append(", ", style="dim")
            ext_text.append_text(_ls_styled(ext, ls_colors, ext=ext))
        ext_text.append(")", style="yellow")
        tokens.append(ext_text)

    out_text = Text()
    for idx, tok in enumerate(tokens):
        if idx > 0:
            out_text.append(", ", style="dim")
        out_text.append_text(tok)
    return out_text


def render_gap_report(
    report: GapReport,
    console: Console | None = None,
    *,
    verbose: bool = False,
) -> None:
    """Render a GapReport as compact, scannable Rich panels and tables."""
    out = console or Console()
    qb_badge = "[green]online[/green]" if report.qbittorrent_online else "[yellow]offline (disk mode)[/yellow]"

    summary_text = (
        f"qBittorrent: {qb_badge}  |  "
        f"Scan: [cyan]{report.scan_duration_ms:.1f} ms[/cyan]  |  "
        f"Synced: [green]{report.already_synced_count}[/green]  |  "
        f"Gaps: [bold cyan]{len(report.ready_to_sync)}[/bold cyan]  |  "
        f"Review: [bold yellow]{len(report.flagged_for_review)}[/bold yellow]  |  "
        f"Extras skipped: [dim]{len(report.skipped_extras)}[/dim]  |  "
        f"Conflicts: [bold red]{len(report.conflicts)}[/bold red]"
    )
    out.print(Panel(summary_text, title="homelab-media plan", border_style="blue"))

    if report.in_progress:
        out.print("\n[bold]In-Progress Torrents (Protected)[/bold]")
        for item in report.in_progress:
            out.print(
                f"[yellow]{escape(item.name)}[/yellow] / [cyan]{item.progress * 100:.1f}%[/cyan] "
                f"/ [white]{escape(item.state)}[/white] / [dim]{_format_bytes(item.size)}[/dim]",
                soft_wrap=True,
                highlight=False,
            )

    if report.ready_to_sync:
        grouped: dict[tuple[MediaKind, str, str], list[SyncAction]] = defaultdict(list)
        for act in report.ready_to_sync:
            grouped[(act.kind, act.torrent_name, _relative_target_folder(act))].append(act)

        out.print("\n[bold]Ready to Sync (/mnt/mango/media/...)[/bold]")
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
        out.print("\n[bold]Flagged for Review (Use --resolve ID=OPT)[/bold]")
        for rev in report.flagged_for_review:
            opts = " | ".join(f"[cyan]{c.option_id}[/cyan]: {escape(c.description)}" for c in rev.candidates)
            out.print(
                f"[bold yellow]{rev.id}[/bold yellow] / [white]{escape(rev.torrent_name)}[/white] "
                f"/ [yellow]{escape(rev.issue)}[/yellow] / {opts}",
                soft_wrap=True,
                highlight=False,
            )

    if report.conflicts:
        out.print("\n[bold]Conflicts (Protected - Existing Target Differs)[/bold]")
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

        out.print("\n[bold]Skipped Extras & Auxiliary Files[/bold]")
        for torrent_name in sorted(skipped_by_torrent, key=str.lower):
            items = skipped_by_torrent[torrent_name]
            link_path = items[0].source_file if len(items) == 1 else items[0].source_file.parent
            file_uri = link_path.absolute().as_uri()
            line = Text.assemble(
                Text(torrent_name, style="white"),
                Text(" / ", style="dim"),
                _format_skipped_summary(items, ls_colors),
                Text(" / ", style="dim"),
                Text("torrent", style=f"dim link {file_uri}"),
            )
            out.print(line, soft_wrap=True, highlight=False)


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
