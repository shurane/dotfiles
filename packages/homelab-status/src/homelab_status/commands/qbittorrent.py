"""Standalone deep inspection command for qBittorrent client, VPN binding, and swarm health."""

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
from homelab_status.services.qbittorrent import render_qbittorrent_deep_report, run_qbittorrent_deep_check

console = Console()


def qbittorrent_command(
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
        help="Target host for qBittorrent connection (auto-resolves from HOMELAB_HOSTNAME, LAN, or Tailscale)",
    ),
    timeout: float = typer.Option(
        10.0,
        "--timeout",
        "-t",
        help="Check timeout in seconds",
    ),
) -> None:
    """Deep inspection of qBittorrent container, VPN tunnel binding, port alignment, and torrent catalog."""
    ctx = StatusContext.build(
        lan_host=lan_host,
        env_file=env_file,
        docker_host=docker_host,
        no_docker=no_docker,
        timeout=timeout,
    )
    conn = ctx.connection

    report = anyio.run(run_qbittorrent_deep_check, ctx)

    if json_output:
        out_dict = {
            "timestamp": Instant.now().format_iso(),
            "connection": asdict(conn) if conn else None,
            "all_passed": report.all_passed,
            "version": report.version,
            "catalog": asdict(report.catalog),
            "server_state": asdict(report.server_state),
            "preferences": asdict(report.preferences),
            "checks": [asdict(c) for c in report.checks],
            "raw_data": report.raw_data,
        }
        print(json.dumps(out_dict, indent=2))
        sys.exit(0 if report.all_passed else 1)

    render_qbittorrent_deep_report(report, console)
    sys.exit(0 if report.all_passed else 1)
