"""Configuration and environment utilities for status inspector."""

from __future__ import annotations

import contextlib
import io
import ipaddress
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import dotenv_values
from pydantic import ValidationError
from rich.console import Console

from models import HomelabConfig, TargetConnection

console = Console(stderr=True)

if TYPE_CHECKING:
    import docker
    import docker.errors


def format_speed(bytes_per_sec: float) -> str:
    bps = float(bytes_per_sec)
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / (1024 * 1024):.2f} MB/s"


def format_size(bytes_val: float) -> str:
    n = float(bytes_val)
    if n >= 1024**4:
        return f"{n / (1024**4):.1f} TB"
    if n >= 1024**3:
        gb = n / (1024**3)
        return f"{gb:.0f} GB" if gb >= 10 else f"{gb:.1f} GB"
    if n >= 1024**2:
        return f"{n / (1024**2):.0f} MB"
    return f"{n / 1024:.0f} KB"


def render_sparkbar(pct: float, width: int = 10, bg: str = "grey27") -> str:
    """Render a fractional block sparkline gauge with seamless background color alignment."""
    blocks = ("", "▏", "▎", "▍", "▌", "▋", "▊", "▉")
    val = max(0.0, min(1.0, pct)) * width
    full = int(val)
    rem = val - full
    char_idx = round(rem * 8)
    if char_idx == 8:
        full += 1
        part = ""
    else:
        part = blocks[char_idx]

    full = min(full, width)
    if full == width:
        part = ""
    empty = max(0, width - full - (1 if part else 0))
    fg = "bold red" if pct >= 0.9 else ("bold yellow" if pct >= 0.7 else "bold cyan")

    filled = f"[{fg}]" + ("█" * full) + f"[/{fg}]" if full else ""
    partial = f"[{fg} on {bg}]{part}[/]" if part else ""
    unfilled = f"[{bg}]" + ("█" * empty) + f"[/{bg}]" if empty else ""
    return f"[{filled}{partial}{unfilled}]"


def get_env_setting(key: str, default: str = "") -> str:
    """Read configuration key from OS environment or local .env file."""
    if key in os.environ:
        return os.environ[key]

    search_paths = [
        Path.cwd() / ".env",
        Path.cwd() / "homelab" / ".env",
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent / "homelab" / ".env",
        Path.home() / "dotfiles" / "homelab" / ".env",
    ]
    for p in search_paths:
        if p.is_file():
            values = dotenv_values(p)
            if (val := values.get(key)) is not None:
                return str(val)

    return default


def get_ssh_user(explicit_user: str | None = None) -> str:
    """Resolve SSH user from explicit argument, HOMELAB_SSH_USER, or HOMELAB_USERNAME."""
    if explicit_user:
        return explicit_user
    if user := (get_env_setting("HOMELAB_SSH_USER") or get_env_setting("HOMELAB_USERNAME")):
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
    """Resolve target connection from explicit flag or HOMELAB_HOSTNAME.

    Fails explicitly if no target host is provided or configured.
    """
    if explicit_host:
        target_host = explicit_host
    elif env_host := (get_env_setting("HOMELAB_HOSTNAME") or get_env_setting("HOMELAB_HOST")):
        target_host = env_host
    else:
        console.print(
            "[bold red]Error:[/bold red] Target host not specified. "
            "Provide --host / -H or set HOMELAB_HOSTNAME in .env"
        )
        sys.exit(1)

    try:
        resolved_ip = socket.gethostbyname(target_host)
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
    """Resolve target host: explicit flag -> env var -> LAN host -> Tailscale."""
    return resolve_target_connection(explicit_host).host


def is_target_local(lan_host: str) -> bool:
    """Determine whether the specified lan_host refers to the local machine."""
    if lan_host in ("localhost", "127.0.0.1", "::1"):
        return True

    current_node = platform.node().lower()
    target_short = lan_host.split(".")[0].lower()
    if current_node in (target_short, lan_host.lower()):
        return True

    with contextlib.suppress(socket.gaierror, OSError):
        target_ip = socket.gethostbyname(lan_host)
        local_ips = {"127.0.0.1", "::1"}
        for info in socket.getaddrinfo(socket.gethostname(), None):
            local_ips.add(info[4][0])
        if target_ip in local_ips:
            return True

    return False


def _load_raw_env(
    env_path: Path | None,
    lan_host: str,
    ssh_user: str | None = None,
) -> dict[str, str]:
    """Retrieve raw environment key-value pairs from local disk, remote host over SSH, or os.environ."""
    ssh_user = get_ssh_user(ssh_user)

    # 1. Explicit path
    if env_path and env_path.is_file():
        return {k: str(v) for k, v in dotenv_values(env_path).items() if v is not None}

    # 2. Local homelab/.env or ./.env
    search_paths = [
        Path.cwd() / ".env",
        Path.cwd() / "homelab" / ".env",
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent / "homelab" / ".env",
        Path.home() / "dotfiles" / "homelab" / ".env",
    ]
    for p in search_paths:
        if p.is_file():
            return {k: str(v) for k, v in dotenv_values(p).items() if v is not None}

    # 3. Fallback to reading remote .env over SSH from lan_host (if on remote workstation / peer machine)
    if not is_target_local(lan_host):
        ssh_cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=3",
            f"{ssh_user}@{lan_host}",
            f"cat /home/{ssh_user}/dotfiles/homelab/.env",
        ]
        with contextlib.suppress(subprocess.SubprocessError, OSError):
            res = subprocess.run(  # noqa: S603
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            if res.returncode == 0 and res.stdout:
                parsed = dotenv_values(stream=io.StringIO(res.stdout))
                return {k: str(v) for k, v in parsed.items() if v is not None}

    # 4. OS environment variables
    return dict(os.environ)


def load_env(
    env_path: Path | None,
    lan_host: str,
    ssh_user: str | None = None,
) -> HomelabConfig:
    """Load homelab .env file and validate with HomelabConfig."""
    raw = _load_raw_env(env_path, lan_host, ssh_user)
    try:
        return HomelabConfig.model_validate(raw)
    except ValidationError as err:
        console.print(f"[bold red]Configuration validation error:[/bold red]\n{err}")
        sys.exit(1)


def _get_ssh_tunnel_client(
    lan_host: str,
    ssh_user: str | None = None,
    timeout: float = 3.0,
) -> docker.DockerClient | None:
    """Establish or reuse a native OpenSSH UNIX socket tunnel to remote docker.sock."""
    import atexit

    import docker
    import docker.errors

    ssh_user = get_ssh_user(ssh_user)

    runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir()))
    sock_path = runtime_dir / f"homelab-docker-{os.getuid()}.sock"
    sock_str = str(sock_path)

    # 1. Reuse existing healthy socket if already alive
    if sock_path.exists():
        try:
            c = docker.DockerClient(base_url=f"unix://{sock_str}", timeout=1.0)
            c.ping()
            return c
        except Exception:
            with contextlib.suppress(OSError):
                sock_path.unlink(missing_ok=True)

    # 2. Spawn native OpenSSH tunnel in background
    cmd = [
        "ssh",
        "-N",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={max(int(timeout), 1)}",
        "-L",
        f"{sock_str}:/var/run/docker.sock",
        f"{ssh_user}@{lan_host}",
    ]
    try:
        proc = subprocess.Popen(  # noqa: S603
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None

    def _cleanup() -> None:
        try:
            proc.terminate()
            proc.wait(timeout=0.3)
        except Exception:
            with contextlib.suppress(Exception):
                proc.kill()
        with contextlib.suppress(OSError):
            sock_path.unlink(missing_ok=True)

    atexit.register(_cleanup)

    # Wait for the tunnel socket to be ready
    t_end = time.perf_counter() + timeout
    while time.perf_counter() < t_end:
        if sock_path.exists():
            with contextlib.suppress(docker.errors.DockerException, OSError):
                c = docker.DockerClient(base_url=f"unix://{sock_str}", timeout=1.0)
                c.ping()
                return c
        time.sleep(0.02)

    _cleanup()
    return None


def get_docker_client(
    docker_host: str | None = None,
    lan_host: str | None = None,
    no_docker: bool = False,
    ssh_user: str | None = None,
) -> docker.DockerClient | None:
    """Resolve Docker client using local socket, OpenSSH tunnel, or SSH bridge."""
    if no_docker:
        return None

    if lan_host is None:
        lan_host = resolve_target_host()

    ssh_user = get_ssh_user(ssh_user)

    import docker
    import docker.errors

    if docker_host:
        with contextlib.suppress(docker.errors.DockerException, OSError):
            c = docker.DockerClient(base_url=docker_host, timeout=5)
            c.ping()
            return c
        return None

    if os.environ.get("DOCKER_HOST"):
        with contextlib.suppress(docker.errors.DockerException, OSError):
            c = docker.from_env()
            c.ping()
            return c

    # Connect to local UNIX socket ONLY if target host is this local machine
    if is_target_local(lan_host):
        sock_p = Path("/var/run/docker.sock")
        if sock_p.exists() and os.access(sock_p, os.R_OK):
            with contextlib.suppress(docker.errors.DockerException, OSError):
                c = docker.from_env()
                c.ping()
                return c

    # Remote target host:
    # Use native OpenSSH UNIX socket tunnel (high-performance C multiplexing, zero locking)
    return _get_ssh_tunnel_client(lan_host, ssh_user, timeout=3.0)
