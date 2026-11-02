"""Configuration and environment utilities for status inspector."""

from __future__ import annotations

import io
import ipaddress
import json
import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import dotenv_values

from .models import TargetConnection

if TYPE_CHECKING:
    import docker


def format_speed(bytes_per_sec: float) -> str:
    bps = float(bytes_per_sec)
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / (1024 * 1024):.2f} MB/s"


def discover_tailscale_suffix() -> str | None:
    """Dynamically discover the Tailscale MagicDNS suffix for the current machine/tailnet."""
    # 1. Environment variable override
    if env_suffix := (os.environ.get("HOMELAB_TAILSCALE_SUFFIX") or os.environ.get("TAILSCALE_SUFFIX")):
        return env_suffix.strip()

    # 2. Fast check: parse /etc/resolv.conf search/domain directive
    resolv = Path("/etc/resolv.conf")
    if resolv.is_file():
        try:
            for line in resolv.read_text().splitlines():
                line = line.strip()
                if line.startswith(("search", "domain")):
                    for word in line.split()[1:]:
                        if word.endswith(".ts.net"):
                            return word
        except Exception:
            pass

    # 3. Fast check: canonical hostname lookup for short name 'm70q'
    try:
        cname, _, _ = socket.gethostbyname_ex("m70q")
        if cname.endswith(".ts.net") and "." in cname:
            return cname.split(".", 1)[1]
    except Exception:
        pass

    # 4. Tailscale CLI check (tailscale status --json)
    for binary in ("tailscale", "tailscale.exe", "/mnt/c/Program Files/Tailscale/tailscale.exe"):
        exe = shutil.which(binary) or (binary if os.path.exists(binary) else None)
        if exe:
            try:
                res = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=1.5)
                if res.returncode == 0:
                    data = json.loads(res.stdout)
                    if suffix := data.get("MagicDNSSuffix"):
                        return suffix
            except Exception:
                pass

    return None


def classify_route(host: str, ip: str, is_local: bool) -> tuple[str, str]:
    """Classify the network route to the target host.

    Returns:
        tuple[route_type, description]
        route_type: "local" | "lan" | "tailscale" | "wan"
        description: Human-readable badge text
    """
    if is_local:
        return "local", "Local Host (UNIX socket)"

    # Check for Tailscale MagicDNS or CGNAT range (100.64.0.0/10)
    if host.endswith(".ts.net"):
        return "tailscale", "Tailscale MagicDNS"

    try:
        addr = ipaddress.ip_address(ip)
        if addr in ipaddress.ip_network("100.64.0.0/10"):
            return "tailscale", "Tailscale MagicDNS"
        if addr.is_loopback:
            return "local", "Local Host"
        if addr.is_private:
            return "lan", "Direct LAN"
    except ValueError:
        pass

    if host.endswith((".lan", ".local", ".home.arpa")):
        return "lan", "Direct LAN"

    return "wan", "WAN / Remote"


def resolve_target_connection(explicit_host: str | None = None) -> TargetConnection:
    """Resolve target connection with dynamic candidate discovery and route classification.

    Candidate fallback order when no explicit host is provided:
      1. Explicit flag or HOMELAB_HOST env var
      2. m70q.lan (Direct LAN)
      3. m70q.<magicdns_suffix> (Tailscale MagicDNS)
      4. m70q (MagicDNS short name)
    """
    candidates: list[str] = []
    if explicit_host:
        candidates = [explicit_host]
    elif env_host := os.environ.get("HOMELAB_HOST"):
        candidates = [env_host]
    else:
        candidates.append("m70q.lan")
        suffix = discover_tailscale_suffix()
        if suffix:
            candidates.append(f"m70q.{suffix}")
        candidates.append("m70q")

    selected_host = candidates[0]
    resolved_ip = ""

    for cand in candidates:
        try:
            resolved_ip = socket.gethostbyname(cand)
            selected_host = cand
            break
        except Exception:
            continue

    if not resolved_ip:
        selected_host = candidates[0]
        try:
            resolved_ip = socket.gethostbyname(selected_host)
        except Exception:
            resolved_ip = "unknown"

    local = is_target_local(selected_host)
    route, desc = classify_route(selected_host, resolved_ip, local)

    return TargetConnection(
        host=selected_host,
        ip=resolved_ip,
        route=route,
        description=desc,
        is_local=local,
    )


def resolve_target_host(explicit_host: str | None = None) -> str:
    """Resolve target host: explicit flag -> env var -> m70q.lan (LAN) -> m70q (Tailscale)."""
    return resolve_target_connection(explicit_host).host


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
        Path(__file__).resolve().parent.parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / "homelab" / ".env",
        Path.home() / "dotfiles" / "homelab" / ".env",
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
