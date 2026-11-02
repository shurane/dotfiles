"""Configuration and environment utilities for status inspector."""

from __future__ import annotations

import io
import os
import platform
import socket
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


def resolve_target_host(explicit_host: str | None = None) -> str:
    """Resolve target host: explicit flag -> env var -> m70q.lan (LAN) -> m70q (Tailscale)."""
    if explicit_host:
        return explicit_host

    if env_host := os.environ.get("HOMELAB_HOST"):
        return env_host

    # Try resolving candidate hostnames: LAN domain first, then Tailscale MagicDNS
    for candidate in ("m70q.lan", "m70q"):
        try:
            socket.gethostbyname(candidate)
            return candidate
        except Exception:
            pass

    return "m70q.lan"


def is_target_local(lan_host: str) -> bool:
    """Determine whether the specified lan_host refers to the local machine."""
    if lan_host in ("localhost", "127.0.0.1", "::1"):
        return True

    current_node = platform.node().lower()
    target_short = lan_host.split(".")[0].lower()
    if current_node in (target_short, lan_host.lower()):
        return True

    try:
        target_ip = socket.gethostbyname(lan_host)
        local_ips = {"127.0.0.1", "::1"}
        for info in socket.getaddrinfo(socket.gethostname(), None):
            local_ips.add(info[4][0])
        if target_ip in local_ips:
            return True
    except Exception:
        pass

    return False


def load_env(
    env_path: Path | None,
    lan_host: str,
    ssh_user: str = "ehtesh",
) -> dict[str, str]:
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

    # 3. Fallback to reading remote .env over SFTP from lan_host (if on remote workstation / peer machine)
    if not is_target_local(lan_host):
        try:
            import paramiko

            ssh = paramiko.SSHClient()
            ssh.load_system_host_keys()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(lan_host, username=ssh_user, timeout=4)
            sftp = ssh.open_sftp()
            with sftp.file(f"/home/{ssh_user}/dotfiles/homelab/.env", "r") as f:
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
    ssh_user: str = "ehtesh",
) -> docker.DockerClient | None:
    """Resolve Docker client using local socket (if target is local) or SSH bridge."""
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

    # Connect to local UNIX socket ONLY if target host is this local machine
    if is_target_local(lan_host):
        sock_path = "/var/run/docker.sock"
        if os.path.exists(sock_path) and os.access(sock_path, os.R_OK):
            try:
                c = docker.from_env()
                c.ping()
                return c
            except Exception:
                pass

    # Remote target host: connect via SSH bridge to target machine
    try:
        c = docker.DockerClient(base_url=f"ssh://{ssh_user}@{lan_host}", timeout=5)
        c.ping()
        return c
    except Exception:
        pass

    return None
