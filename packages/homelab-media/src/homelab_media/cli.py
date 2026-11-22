"""Typer CLI entrypoint for homelab-media."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer
from rich.console import Console

from homelab_media.clients.jellyfin import JellyfinClient
from homelab_media.config import MediaConfig, is_local_target, load_config
from homelab_media.executor import execute_sync
from homelab_media.models import ActionType, GapReport, MediaKind, SyncAction
from homelab_media.parser import resolve_target_with_folder
from homelab_media.remote import dispatch_remote
from homelab_media.renderer import render_execution_summary, render_gap_report
from homelab_media.scanner import scan_media_gaps

app = typer.Typer(
    name="media",
    help="Audit media library gaps, filter extras, and hardlink completed torrents for Jellyfin.",
    no_args_is_help=True,
)
console = Console()


def _maybe_dispatch_remote(config: MediaConfig, raw_args: list[str] | None = None) -> bool:
    """If the media filesystem is not local, run the exact CLI command on the storage host."""
    if os.environ.get("HOMELAB_MEDIA_LOCAL") == "1" or is_local_target(config):
        return False

    proc = dispatch_remote(config, raw_args if raw_args is not None else sys.argv[1:])
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    raise typer.Exit(code=proc.returncode)


def _resolve_review_specs(
    resolve_specs: list[str],
    report: GapReport,
    config: MediaConfig,
) -> list[SyncAction]:
    """Validate `--resolve ID=OPT` specs against `report.flagged_for_review` and return SYNC actions."""
    resolutions: dict[str, str] = {}
    for item in resolve_specs:
        rev_id, sep, opt_id = item.partition("=")
        if not sep or not rev_id.strip() or not opt_id.strip():
            console.print(f"[red]Invalid --resolve format '{item}'. Expected ID=OPT.[/red]")
            raise typer.Exit(code=2)
        resolutions[rev_id.strip()] = opt_id.strip()

    rev_map = {r.id: r for r in report.flagged_for_review}
    resolved_actions: list[SyncAction] = []

    for rev_id, opt_id in resolutions.items():
        rev = rev_map.get(rev_id)
        if rev is None:
            console.print(f"[red]Unknown review ID '{rev_id}'.[/red]")
            raise typer.Exit(code=2)
        cand = next((c for c in rev.candidates if c.option_id == opt_id), None)
        if cand is None:
            console.print(f"[red]Unknown option '{opt_id}' for {rev_id}.[/red]")
            raise typer.Exit(code=2)

        chosen_folder = cand.target_path.name
        media_subdir = config.media_root(rev.kind)
        torrent_dir = config.torrents_root(rev.kind) / rev.torrent_name

        for src in rev.source_files:
            try:
                rel_path = src.relative_to(torrent_dir).as_posix()
            except ValueError:
                rel_path = src.name

            resolved = resolve_target_with_folder(
                rev.kind,
                rev.torrent_name,
                rel_path,
                src.name,
                chosen_folder,
                media_subdir,
            )
            if resolved is None:
                continue
            tgt, season_num, ep_val = resolved
            resolved_actions.append(
                SyncAction(
                    torrent_name=rev.torrent_name,
                    source_file=src,
                    target_file=tgt,
                    kind=rev.kind,
                    action_type=ActionType.SYNC,
                    reason=f"RESOLVED:{rev_id}={opt_id}",
                    season=season_num,
                    episode=ep_val,
                )
            )

    return resolved_actions


@app.command()
def plan(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON GapReport."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show skipped extras and details."),
    offline: bool = typer.Option(False, "--offline", help="Skip qBittorrent status check."),
) -> None:
    """Preview planned hardlinks, in-progress torrents, review flags, and skipped extras."""
    config = load_config()
    _maybe_dispatch_remote(config)

    report = scan_media_gaps(config, use_qbittorrent=not offline)
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
        return
    render_gap_report(report, console=console, verbose=verbose)


@app.command()
def sync(
    apply: bool = typer.Option(False, "--apply", help="Create hardlinks on disk (default is dry-run)."),
    no_refresh: bool = typer.Option(False, "--no-refresh", help="Skip Jellyfin library refresh after linking."),
    offline: bool = typer.Option(False, "--offline", help="Skip qBittorrent status check."),
    resolve: list[str] | None = typer.Option(
        None,
        "--resolve",
        help="Resolve flagged review item (e.g. rev-001=opt-1).",
    ),
) -> None:
    """Hardlink ready media gaps into /mnt/mango/media and refresh Jellyfin."""
    config = load_config()
    _maybe_dispatch_remote(config)

    report = scan_media_gaps(config, use_qbittorrent=not offline)
    actions = list(report.ready_to_sync)
    if resolve:
        actions.extend(_resolve_review_specs(resolve, report, config))

    summary = execute_sync(actions, config, dry_run=not apply)
    render_execution_summary(summary, dry_run=not apply, console=console)

    if apply and summary.linked_count > 0 and not no_refresh:
        jf = JellyfinClient(config.jellyfin_url, config.jellyfin_api_key)
        ok, msg = jf.trigger_refresh()
        style = "green" if ok else "yellow"
        console.print(f"[{style}]{msg}[/{style}]")
        if ok and (identified := jf.identify_unmatched()):
            console.print(f"[green]Identified {len(identified)} unmatched item(s): {', '.join(identified)}[/green]")

    if summary.errors:
        raise typer.Exit(code=1)


@app.command()
def refresh() -> None:
    """Trigger a Jellyfin library refresh and identify any unmatched series/movies."""
    config = load_config()
    jf = JellyfinClient(config.jellyfin_url, config.jellyfin_api_key)
    ok, msg = jf.trigger_refresh()
    style = "green" if ok else "red"
    console.print(f"[{style}]{msg}[/{style}]")
    if not ok:
        raise typer.Exit(code=1)
    if identified := jf.identify_unmatched():
        console.print(f"[green]Identified {len(identified)} unmatched item(s): {', '.join(identified)}[/green]")


@app.command()
def ignore(
    torrent_dir: str = typer.Argument(..., help="Torrent folder name under torrents/{tv,movies} or full path."),
    pattern: str = typer.Option("", "--pattern", "-p", help="Glob pattern to ignore (omit to ignore entire dir)."),
    kind: MediaKind = typer.Option(MediaKind.TV, "--kind", "-k", help="Media category (tv or movies)."),
) -> None:
    """Add a .syncignore file or pattern inside a torrent directory."""
    config = load_config()
    _maybe_dispatch_remote(config)

    base = config.torrents_root(kind)
    target_dir = Path(torrent_dir) if Path(torrent_dir).is_absolute() else (base / torrent_dir)
    if not target_dir.is_dir():
        console.print(f"[red]Torrent directory not found: {target_dir}[/red]")
        raise typer.Exit(code=1)

    syncignore_path = target_dir / ".syncignore"
    if not pattern:
        if not syncignore_path.exists():
            syncignore_path.write_text("# Ignore entire directory\n", encoding="utf-8")
        console.print(f"[green]Ignored entire directory via {syncignore_path}[/green]")
        return

    existing = syncignore_path.read_text(encoding="utf-8") if syncignore_path.exists() else ""
    if pattern not in existing.splitlines():
        with syncignore_path.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(f"{pattern}\n")
    console.print(f"[green]Added pattern '{pattern}' to {syncignore_path}[/green]")
