"""Configuration and environment utilities for status inspector."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import dotenv_values

if TYPE_CHECKING:
    import docker


def format_speed(bytes_per_sec: float) -> str:
    bps = float(bytes_per_sec)
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / (1024 * 1024):.2f} MB/s"


def load_env(env_path: Path | None, lan_host: str) -> dict[str, str]:
    """Load homelab .env file from local disk or via remote SFTP fallback."""
    # 1. Explicit path
    if env_path and env_path.is_file():
        return {k: v for k, v in dotenv_values(env_path).items() if v is not None}

    # 2. Local homelab/.env or ./.env
    search_paths = [
        Path.cwd() / ".env",
        Path.cwd() / "homelab" / ".env",
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / "homelab" / ".env",
    ]
    for p in search_paths:
        if p.is_file():
            return {k: v for k, v in dotenv_values(p).items() if v is not None}

    # 3. Fallback to reading remote .env over SFTP from lan_host (if on workstation)
    try:
        import paramiko

        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(lan_host, username="ehtesh", timeout=4)
        sftp = ssh.open_sftp()
        with sftp.file("/home/ehtesh/dotfiles/homelab/.env", "r") as f:
            content = f.read().decode("utf-8")
        parsed = dotenv_values(stream=io.StringIO(content))
        return {k: v for k, v in parsed.items() if v is not None}
    except Exception:
        pass

    # 4. OS environment variables
    return dict(os.environ)


def get_docker_client(
    docker_host: str | None = None,
    lan_host: str = "m70q.lan",
    no_docker: bool = False,
) -> docker.DockerClient | None:
    """Resolve Docker client using local socket, explicit host, or SSH bridge."""
    if no_docker:
        return None

    import docker

    if docker_host:
        try:
            c = docker.DockerClient(base_url=docker_host, timeout=5)
            c.ping()
            return c
        except Exception:
            return None

    if os.environ.get("DOCKER_HOST"):
        try:
            c = docker.from_env()
            c.ping()
            return c
        except Exception:
            pass

    # Try local UNIX socket
    sock_path = "/var/run/docker.sock"
    if os.path.exists(sock_path) and os.access(sock_path, os.R_OK):
        try:
            c = docker.from_env()
            c.ping()
            return c
        except Exception:
            pass

    # Fallback to SSH connection to target host
    try:
        c = docker.DockerClient(base_url=f"ssh://ehtesh@{lan_host}", timeout=5)
        c.ping()
        return c
    except Exception:
        pass

    return None
