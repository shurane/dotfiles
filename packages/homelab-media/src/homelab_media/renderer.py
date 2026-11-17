"""Rich terminal presentation for media gap reports and sync summaries."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

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


def _format_skipped_summary(items: list[SyncAction]) -> str:
    """Summarize skipped extras/auxiliary items for a single torrent into a compact label."""
    named: list[str] = []
    non_video_exts: set[str] = set()
    non_video_count = 0

    for sk in items:
        name = escape(sk.source_file.name)
        if sk.reason.startswith("NON_VIDEO_EXT:"):
            ext = sk.reason.split(":", 1)[1]
            non_video_exts.add(ext)
            non_video_count += 1
        elif sk.reason.startswith("BLACKLISTED_DIR:"):
            named.append(f"{name}/ (dir)")
        elif sk.reason.startswith("EXTRA_KEYWORD:"):
            kw = sk.reason.split(":", 1)[1]
            named.append(f"{name} ({kw})")
        elif sk.reason == "SMALL_MOVIE_PROMO_OR_SAMPLE":
            named.append(f"{name} (promo)")
        elif sk.reason == "TINY_OR_SPARSE_FILE":
            named.append(f"{name} (<1 MiB)")
        elif sk.reason == "NO_EPISODE_TAG":
            named.append(f"{name} (no episode)")
        else:
            named.append(f"{name} ({sk.reason.lower()})")

    parts = sorted(named)
    if non_video_count > 0:
        exts_str = ", ".join(sorted(non_video_exts))
        parts.append(f"{non_video_count}x ({exts_str})")
    return ", ".join(parts)


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
        t_prog = Table(title="In-Progress Torrents (Protected)", show_lines=False)
        t_prog.add_column("Torrent", style="yellow")
        t_prog.add_column("Progress", justify="right")
        t_prog.add_column("State")
        t_prog.add_column("Size", justify="right")
        for item in report.in_progress:
            t_prog.add_row(
                item.name,
                f"{item.progress * 100:.1f}%",
                item.state,
                _format_bytes(item.size),
            )
        out.print(t_prog)

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
        t_rev = Table(title="Flagged for Review (Use --resolve ID=OPT)", show_lines=True)
        t_rev.add_column("ID", style="bold yellow")
        t_rev.add_column("Torrent")
        t_rev.add_column("Issue")
        t_rev.add_column("Candidates")
        for rev in report.flagged_for_review:
            opts = "\n".join(f"{c.option_id}: {c.description}" for c in rev.candidates)
            t_rev.add_row(rev.id, rev.torrent_name, f"{rev.issue}\n{rev.message}", opts)
        out.print(t_rev)

    if report.conflicts:
        t_conf = Table(title="Conflicts (Protected - Existing Target Differs)", show_lines=False)
        t_conf.add_column("Target", style="red")
        t_conf.add_column("Source")
        t_conf.add_column("Reason")
        for conf in report.conflicts:
            t_conf.add_row(str(conf.target_file or "-"), str(conf.source_file), conf.reason)
        out.print(t_conf)

    if verbose and report.skipped_extras:
        skipped_by_torrent: dict[str, list[SyncAction]] = defaultdict(list)
        for sk in report.skipped_extras:
            skipped_by_torrent[sk.torrent_name].append(sk)

        out.print("\n[bold]Skipped Extras & Auxiliary Files[/bold]")
        for torrent_name in sorted(skipped_by_torrent):
            items = skipped_by_torrent[torrent_name]
            link_path = items[0].source_file if len(items) == 1 else items[0].source_file.parent
            file_uri = link_path.absolute().as_uri()
            summary = _format_skipped_summary(items)
            out.print(
                f"[white]{escape(torrent_name)}[/white] / [yellow]{summary}[/yellow] "
                f"/ [dim][link={file_uri}]torrent[/link][/dim]",
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
