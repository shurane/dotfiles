"""Standalone deep inspection command for Samba SMB/CIFS server, authentication, and storage mounts."""

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
from services.samba import render_samba_deep_report, run_samba_deep_check

console = Console()


def samba_command(
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
        help="Override Docker daemon URL (e.g. ssh://ehtesh@m70q.lan)",
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
        help="Target host for Samba connection (auto-resolves m70q.lan or m70q on Tailscale)",
    ),
    timeout: float = typer.Option(
        10.0,
        "--timeout",
        "-t",
        help="Check timeout in seconds",
    ),
) -> None:
    """Deep inspection of Samba container, port 445 connectivity, authenticated SMB, drive mounts, and locks."""
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

    report = anyio.run(run_samba_deep_check, ctx)

    if json_output:
        out_dict = {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "connection": asdict(conn) if conn else None,
            "all_passed": report.all_passed,
            "version": report.version,
            "shares": report.shares,
            "accounts": report.accounts,
            "drive_mount_mode": report.drive_mount_mode,
            "active_clients": [asdict(c) for c in report.active_clients],
            "active_locks": [asdict(lock) for lock in report.active_locks],
            "checks": [asdict(c) for c in report.checks],
        }
        print(json.dumps(out_dict, indent=2))
        sys.exit(0 if report.all_passed else 1)

    render_samba_deep_report(report, console)
    sys.exit(0 if report.all_passed else 1)
