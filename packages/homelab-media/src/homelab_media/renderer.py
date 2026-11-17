"""Rich terminal presentation for media gap reports and sync summaries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from homelab_media.executor import ExecutionSummary
    from homelab_media.models import GapReport


def _format_bytes(num_bytes: int) -> str:
    """Format byte count into human-readable IEC units."""
    val = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if val < 1024.0 or unit == "TiB":
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return f"{num_bytes} B"


def render_gap_report(
    report: GapReport,
    console: Console | None = None,
    *,
    verbose: bool = False,
) -> None:
    """Render a GapReport as structured Rich panels and tables."""
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
    out.print(Panel(summary_text, title="homelab-media status", border_style="blue"))

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
        t_sync = Table(title="Ready to Sync (Missing Hardlinks)", show_lines=False)
        t_sync.add_column("Kind", style="magenta", width=7)
        t_sync.add_column("Source", style="white")
        t_sync.add_column("Target", style="green")
        t_sync.add_column("Size", justify="right")
        t_sync.add_column("Reason", style="dim")
        for act in report.ready_to_sync:
            src_disp = (
                f"{act.torrent_name}/{act.source_file.name}"
                if act.source_file.name != act.torrent_name
                else act.torrent_name
            )
            tgt_disp = str(act.target_file) if act.target_file else "-"
            t_sync.add_row(
                act.kind.value,
                src_disp,
                tgt_disp,
                _format_bytes(act.file_size),
                act.reason,
            )
        out.print(t_sync)
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
        t_skip = Table(title="Skipped Extras & Auxiliary Files", show_lines=False)
        t_skip.add_column("Torrent", style="dim")
        t_skip.add_column("File")
        t_skip.add_column("Reason", style="yellow")
        for sk in report.skipped_extras:
            t_skip.add_row(sk.torrent_name, sk.source_file.name, sk.reason)
        out.print(t_skip)


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
