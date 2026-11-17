"""Configuration and environment utilities for status inspector."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values
from homelab_core.docker import get_docker_client
from homelab_core.env import find_homelab_env, get_env_setting, load_homelab_env
from homelab_core.errors import HomelabConfigError
from homelab_core.formatting import format_size, format_speed, render_sparkbar
from homelab_core.models import HomelabConfig
from homelab_core.network import (
    TargetConnection,
    classify_route,
    get_ssh_user,
    is_target_local,
    run_ssh_command,
)
from homelab_core.network import (
    resolve_target_connection as _core_resolve_target_connection,
)
from pydantic import ValidationError
from rich.console import Console

console = Console(stderr=True)

__all__ = [
    "TargetConnection",
    "classify_route",
    "find_homelab_env",
    "format_size",
    "format_speed",
    "get_docker_client",
    "get_env_setting",
    "get_ssh_user",
    "is_target_local",
    "load_env",
    "render_sparkbar",
    "resolve_target_connection",
    "resolve_target_host",
]


def resolve_target_connection(explicit_host: str | None = None) -> TargetConnection:
    """Resolve target connection from explicit flag or HOMELAB_HOSTNAME.

    Fails explicitly if no target host is provided or configured.
    """
    try:
        return _core_resolve_target_connection(explicit_host)
    except HomelabConfigError:
        console.print(
            "[bold red]Error:[/bold red] Target host not specified. Provide --host / -H or set HOMELAB_HOSTNAME in .env"
        )
        sys.exit(1)


def resolve_target_host(explicit_host: str | None = None) -> str:
    """Resolve target host: explicit flag -> env var."""
    return resolve_target_connection(explicit_host).host


def _load_raw_env(
    env_path: Path | None,
    lan_host: str,
    ssh_user: str | None = None,
) -> dict[str, str]:
    """Retrieve raw environment key-value pairs from local disk, remote host over SSH, or os.environ."""
    resolved_ssh_user = get_ssh_user(ssh_user)

    # 1. Local homelab/.env or explicit path
    if (found := find_homelab_env(env_path)) is not None:
        return load_homelab_env(found)

    # 2. Fallback to reading remote .env over SSH from lan_host (if on remote workstation / peer machine)
    if not is_target_local(lan_host):
        with contextlib.suppress(subprocess.SubprocessError, OSError):
            res = run_ssh_command(
                lan_host,
                'cat "${HOME}/dotfiles/homelab/.env"',
                user=resolved_ssh_user,
                timeout=4.0,
            )
            if res.returncode == 0 and res.stdout:
                parsed = dotenv_values(stream=io.StringIO(res.stdout))
                return {k: str(v) for k, v in parsed.items() if v is not None}

    # 3. OS environment variables
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
