"""Standalone deep inspection command for Jellyfin media server and hardware acceleration."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import anyio
import typer
from rich.console import Console
from whenever import Instant

from homelab_status.models import StatusContext
from homelab_status.services.jellyfin import render_jellyfin_deep_report, run_jellyfin_deep_check

console = Console()


def jellyfin_command(
    limit: int = typer.Option(
        10,
        "--limit",
        "-n",
        help="Number of recent playback history entries to display [default: 10]",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output raw check results as formatted JSON",
    ),
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        "-e",
        help="Path to homelab .env file",
    ),
    docker_host: str | None = typer.Option(
        None,
        "--docker-host",
        help="Override Docker daemon URL (e.g. ssh://user@server.lan)",
    ),
    no_docker: bool = typer.Option(
        False,
        "--no-docker",
        help="Skip Docker inspection and execute network/HTTP checks only",
    ),
    lan_host: str | None = typer.Option(
        None,
        "--lan-host",
        "--host",
        "-H",
        help="Target host for Jellyfin connection (auto-resolves from HOMELAB_HOSTNAME, LAN, or Tailscale)",
    ),
    timeout: float = typer.Option(
        10.0,
        "--timeout",
        "-t",
        help="Check timeout in seconds",
    ),
) -> None:
    """Deep inspection of Jellyfin container, Intel QuickSync (QSV) transcode, memory cgroup, and sessions."""
    ctx = StatusContext.build(
        lan_host=lan_host,
        env_file=env_file,
        docker_host=docker_host,
        no_docker=no_docker,
        timeout=timeout,
    )
    conn = ctx.connection

    report = anyio.run(run_jellyfin_deep_check, ctx, limit)

    if json_output:
        out_dict = {
            "timestamp": Instant.now().format_iso(),
            "connection": asdict(conn) if conn else None,
            "all_passed": report.all_passed,
            "version": report.version,
            "qsv_speed": report.qsv_speed,
            "memory": asdict(report.memory) if report.memory else None,
            "item_counts": report.item_counts,
            "active_sessions": [asdict(s) for s in report.active_sessions],
            "connected_clients_24h": [asdict(c) for c in report.connected_clients_24h],
            "recent_playback": [asdict(p) for p in report.recent_playback],
            "plays_last_24h_count": report.plays_last_24h_count,
            "plays_by_client_24h": report.plays_by_client_24h,
            "checks": [asdict(c) for c in report.checks],
        }
        print(json.dumps(out_dict, indent=2))
        sys.exit(0 if report.all_passed else 1)

    render_jellyfin_deep_report(report, console)
    sys.exit(0 if report.all_passed else 1)
