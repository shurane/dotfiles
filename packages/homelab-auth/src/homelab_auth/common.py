from __future__ import annotations

from typing import TYPE_CHECKING

import typer
from homelab_core.db import wait_for_sqlite_table
from homelab_core.env import ensure_state_dir, load_homelab_env
from homelab_core.formatting import format_path
from homelab_core.services import Service, wait_for_http

from homelab_auth.models import SERVICE_NAMES, BootstrapOptions

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "build_options",
    "ensure_state_dir",
    "format_path",
    "load_env",
    "wait_for_http",
    "wait_for_sqlite_table",
]


def load_env(path: Path) -> dict[str, str]:
    """Parse key-value pairs from .env file."""
    return load_homelab_env(path, overlay_environ=False)


def build_options(
    skip_backup: bool,
    parallel: bool,
    services_value: str,
    apply: bool = False,
) -> BootstrapOptions:
    service_values = tuple(
        service.strip().lower() for service in services_value.split(",") if service.strip()
    )
    unknown_services = sorted(set(service_values) - set(SERVICE_NAMES))
    if unknown_services:
        raise typer.BadParameter(
            f"unknown services: {', '.join(unknown_services)}", param_hint="--services"
        )
    if not service_values:
        raise typer.BadParameter("must include at least one service", param_hint="--services")
    return BootstrapOptions(
        apply=apply,
        parallel=parallel,
        skip_backup=skip_backup,
        services=tuple(Service(service) for service in service_values),
    )
