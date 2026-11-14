"""Standalone deep inspection command for qBittorrent client, VPN binding, and swarm health."""

from __future__ import annotations

import datetime
import json
import sys
from dataclasses import asdict
from pathlib import Path

import anyio
import typer
from rich.console import Console

from config import get_docker_client, load_env, resolve_target_connection
from models import StatusContext
from services.qbittorrent import render_qbittorrent_deep_report, run_qbittorrent_deep_check

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
    conn = resolve_target_connection(lan_host)
    env = load_env(env_file, conn.host)
    username = env.get("HOMELAB_USERNAME", "username")
    password = env.get("HOMELAB_PASSWORD", "")
    base_domain = env.get("HOSTNAME_BASE", "example.com")

    docker_client = get_docker_client(docker_host, conn.host, no_docker)

    ctx = StatusContext(
        env=env,
        username=username,
        password=password,
        base_domain=base_domain,
        lan_host=conn.host,
        docker_client=docker_client,
        http_timeout=timeout,
        no_docker=no_docker,
        connection=conn,
    )

    report = anyio.run(run_qbittorrent_deep_check, ctx)

    if json_output:
        out_dict = {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
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
