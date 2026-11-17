"""Network target classification, SSH user resolution, and routing utilities."""

from __future__ import annotations

import contextlib
import ipaddress
import platform
import socket
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homelab_core.env import get_env_setting
from homelab_core.errors import HomelabConfigError

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "TargetConnection",
    "classify_route",
    "get_ssh_user",
    "is_target_local",
    "resolve_target_connection",
    "resolve_target_host",
    "run_ssh_command",
]


@dataclass(slots=True)
class TargetConnection:
    host: str
    ip: str
    route: str  # "local", "lan", "tailscale", "wan"
    description: str  # e.g. "Local Host (UNIX socket)", "Direct LAN", "Tailscale MagicDNS"
    is_local: bool = False


def is_target_local(lan_host: str) -> bool:
    """Determine whether the specified lan_host refers to the local machine."""
    if lan_host in ("localhost", "127.0.0.1", "::1"):
        return True

    current_node = platform.node().lower()
    target_short = lan_host.split(".")[0].lower()
    if current_node in (target_short, lan_host.lower()):
        return True

    with contextlib.suppress(socket.gaierror, OSError):
        target_info = socket.getaddrinfo(lan_host, None)
        target_ip = target_info[0][4][0] if target_info else None
        if target_ip:
            local_ips = {"127.0.0.1", "::1"}
            for info in socket.getaddrinfo(socket.gethostname(), None):
                local_ips.add(info[4][0])
            if target_ip in local_ips:
                return True

    return False


def get_ssh_user(
    explicit_user: str | None = None,
    env_path: Path | str | None = None,
) -> str:
    """Resolve SSH user from explicit argument, HOMELAB_SSH_USER, or HOMELAB_USERNAME."""
    if explicit_user:
        return explicit_user
    if user := (
        get_env_setting("HOMELAB_SSH_USER", explicit_path=env_path)
        or get_env_setting("HOMELAB_USERNAME", explicit_path=env_path)
    ):
        return user
    return "homelab"


def classify_route(host: str, ip: str, is_local: bool) -> tuple[str, str]:
    """Classify the network route to the target host.

    Returns:
        tuple[route_type, description]
        route_type: "local" | "lan" | "tailscale" | "wan"
        description: Human-readable badge text
    """
    if is_local:
        return "local", "Local Host (UNIX socket)"

    if host.endswith((".ts.net", ".ts.net.")):
        return "tailscale", "Tailscale MagicDNS"

    with contextlib.suppress(ValueError):
        addr = ipaddress.ip_address(ip)
        # Tailscale IPv4 CGNAT (100.64.0.0/10) or Tailscale IPv6 ULA (fd7a:115c:a1e0::/48)
        if addr in ipaddress.ip_network("100.64.0.0/10") or addr in ipaddress.ip_network(
            "fd7a:115c:a1e0::/48"
        ):
            return "tailscale", "Tailscale MagicDNS"
        if addr.is_loopback:
            return "local", "Local Host"
        if addr.is_private:
            return "lan", "Direct LAN"

    if host.endswith((".lan", ".local", ".home.arpa")):
        return "lan", "Direct LAN"

    return "wan", "WAN / Remote"


def resolve_target_connection(explicit_host: str | None = None) -> TargetConnection:
    """Resolve target connection from explicit parameter or HOMELAB_HOSTNAME."""
    target_host = explicit_host or get_env_setting("HOMELAB_HOSTNAME")
    if not target_host:
        raise HomelabConfigError(
            "Target host not specified. Provide explicit host or set HOMELAB_HOSTNAME."
        )

    try:
        addrs = socket.getaddrinfo(target_host, None)
        resolved_ip = str(addrs[0][4][0]) if addrs else "unknown"
    except Exception:
        resolved_ip = "unknown"

    local = is_target_local(target_host)
    route, desc = classify_route(target_host, resolved_ip, local)

    return TargetConnection(
        host=target_host,
        ip=resolved_ip,
        route=route,
        description=desc,
        is_local=local,
    )


def resolve_target_host(explicit_host: str | None = None) -> str:
    """Resolve target host: explicit parameter -> HOMELAB_HOSTNAME -> localhost."""
    return resolve_target_connection(explicit_host).host


def run_ssh_command(
    host: str,
    command: str,
    *,
    user: str | None = None,
    timeout: float = 5.0,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Execute a remote shell command over OpenSSH with hardened defaults."""
    ssh_user = get_ssh_user(user)
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={max(int(timeout), 1)}",
        "-o",
        "ServerAliveInterval=5",
        f"{ssh_user}@{host}",
        command,
    ]
    return subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout + 2.0,
        check=check,
    )
