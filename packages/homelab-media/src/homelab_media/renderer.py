"""Rich terminal presentation for media gap reports and sync summaries."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markup import escape
from rich.text import Text

from homelab_media.models import MediaKind
from homelab_media.ui import (
    format_bytes,
    format_episode_ranges,
    ls_styled,
    parse_ls_colors,
    print_section_header,
    reason_label,
    relative_target_folder,
)

if TYPE_CHECKING:
    from homelab_media.executor import ExecutionSummary
    from homelab_media.models import GapReport, SyncAction


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

    if grouped:
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
    else:
        out.print("[green]No pending media gaps detected.[/green]")

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
            file_uri = link_path.absolute().as_uri()
            header_text = ls_styled(f"{torrent_name}/", ls_colors, is_dir=True)
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
                reason = reason_label(sk.reason)
                item_text = ls_styled(label, ls_colors, is_dir=is_dir, ext=ext)
                item_text.stylize(f"link {sk.source_file.absolute().as_uri()}")
                out.print(
                    Text.assemble(
                        Text("  "),
                        item_text,
                        Text(" · ", style="dim"),
                        Text(reason, style="yellow"),
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
        f"Errors: [bold red]{len(summary.errors)}[/bold red]",
    )
    for err in summary.errors:
        out.print(f"  [red]ERROR:[/red] {err}")
