"""Standalone deep inspection command for ProtonVPN + Gluetun + qBittorrent."""

from __future__ import annotations

import datetime
import json
import sys
from dataclasses import asdict
from pathlib import Path

import anyio
import typer
from rich.console import Console

from common import require_env
from config import get_docker_client, load_env, resolve_target_connection
from models import StatusContext
from services.gluetun import render_vpn_deep_report, run_vpn_deep_check

console = Console()


def vpn_command(
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
        help="Target host for VPN connection (auto-resolves from HOMELAB_HOSTNAME, LAN, or Tailscale)",
    ),
    timeout: float = typer.Option(
        10.0,
        "--timeout",
        "-t",
        help="Check timeout in seconds",
    ),
) -> None:
    """Deep inspection of ProtonVPN tunnel, Gluetun kill switch, port forwarding, and qBittorrent."""
    conn = resolve_target_connection(lan_host)
    env = load_env(env_file, conn.host)
    username = env.get("HOMELAB_USERNAME", "username")
    password = require_env(env, "HOMELAB_PASSWORD")
    base_domain = require_env(env, "HOSTNAME_BASE")

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

    report = anyio.run(run_vpn_deep_check, ctx)

    if json_output:
        out_dict = {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "connection": asdict(conn) if conn else None,
            "all_passed": report.all_passed,
            "host_ip": asdict(report.host_ip) if report.host_ip else None,
            "vpn_ip": asdict(report.vpn_ip) if report.vpn_ip else None,
            "forwarded_port": report.forwarded_port,
            "qbittorrent_port": report.qbittorrent_port,
            "interface_bound": report.interface_bound,
            "checks": [asdict(c) for c in report.checks],
        }
        print(json.dumps(out_dict, indent=2))
        sys.exit(0 if report.all_passed else 1)

    render_vpn_deep_report(report, console)
    sys.exit(0 if report.all_passed else 1)
