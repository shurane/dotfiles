from __future__ import annotations

import os
from pathlib import Path

from homelab_core.env import find_homelab_env, find_homelab_root
from homelab_core.services import resolve_service_url

__all__ = [
    "HOMELAB_ENV",
    "ROOT",
    "find_homelab_root",
    "get_service_url",
]

ROOT = find_homelab_root()


def _get_homelab_env() -> Path:
    if found := find_homelab_env():
        return found
    return ROOT / ".env"


HOMELAB_ENV = _get_homelab_env()


def get_service_url(service_name: str, default_port: int, env_var: str) -> str:
    """Resolve the service HTTP base URL."""
    override = os.environ.get(env_var) if env_var else None
    return resolve_service_url(
        service_name,
        env_override=override,
        env_path=HOMELAB_ENV,
        default_port=default_port,
    )


def __getattr__(name: str) -> str:
    if name.endswith("_URL"):
        service_name = name.removesuffix("_URL").lower().replace("_", "-")
        return resolve_service_url(service_name, env_path=HOMELAB_ENV)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

