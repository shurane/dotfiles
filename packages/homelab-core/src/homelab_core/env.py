"""Canonical environment and homelab root directory discovery utilities."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

from homelab_core.errors import HomelabConfigError

__all__ = [
    "ensure_state_dir",
    "find_homelab_env",
    "find_homelab_root",
    "get_env_setting",
    "load_homelab_env",
]


def find_homelab_env(explicit_path: Path | str | None = None) -> Path | None:
    """Locate the homelab .env file dynamically.

    Search precedence:
    1. Explicit path parameter (if given and exists).
    2. HOMELAB_ENV environment variable.
    3. $HOMELAB_DIR/.env (if HOMELAB_DIR is set).
    4. Guarded CWD lookup: CWD/homelab/.env or CWD/.env (only if CWD contains docker-compose.yml or is named 'homelab').
    5. Upward directory walk from this module and CWD until repo boundary (.git) or filesystem root.
    6. User home fallback (~/dotfiles/homelab/.env).
    """
    if explicit_path is not None:
        p = Path(explicit_path).resolve()
        return p if p.is_file() else None

    if env_var := os.environ.get("HOMELAB_ENV"):
        p = Path(env_var).resolve()
        if p.is_file():
            return p

    if homelab_dir := os.environ.get("HOMELAB_DIR"):
        p = (Path(homelab_dir) / ".env").resolve()
        if p.is_file():
            return p

    # Guarded CWD lookup: never blindly load an arbitrary .env from an unrelated project directory
    cwd = Path.cwd().resolve()
    if (cwd / "homelab" / ".env").is_file():
        return cwd / "homelab" / ".env"
    if (cwd.name == "homelab" or (cwd / "docker-compose.yml").is_file()) and (cwd / ".env").is_file():
        return cwd / ".env"

    # Upward tree walk from module and CWD
    search_starts = [Path(__file__).resolve(), cwd]
    for start in search_starts:
        for parent in start.parents:
            if (candidate := parent / "homelab" / ".env").is_file():
                return candidate
            if parent.name == "homelab" and (candidate := parent / ".env").is_file():
                return candidate
            if (parent / ".git").exists() or parent == parent.parent:
                break

    if (fallback := Path.home() / "dotfiles" / "homelab" / ".env").is_file():
        return fallback

    return None


def find_homelab_root(explicit_path: Path | str | None = None) -> Path:
    """Locate the homelab/ directory containing docker-compose.yml."""
    if explicit_path:
        p = Path(explicit_path).resolve()
        if p.is_dir():
            return p

    if env_dir := os.environ.get("HOMELAB_DIR"):
        p = Path(env_dir).resolve()
        if p.is_dir():
            return p

    search_starts = [Path(__file__).resolve(), Path.cwd().resolve()]
    for start in search_starts:
        for parent in start.parents:
            if (parent / "homelab" / "docker-compose.yml").is_file():
                return parent / "homelab"
            if parent.name == "homelab" and (parent / "docker-compose.yml").is_file():
                return parent
            if (parent / ".git").exists() or parent == parent.parent:
                break

    return Path.home() / "dotfiles" / "homelab"


def load_homelab_env(
    explicit_path: Path | str | None = None,
    required_keys: tuple[str, ...] = (),
    *,
    overlay_environ: bool = True,
) -> dict[str, str]:
    """Load configuration key-values from .env file optionally overlaid with current OS environment variables."""
    env_file = find_homelab_env(explicit_path)
    file_vars: dict[str, str] = {}
    if env_file is not None and env_file.is_file():
        file_vars = {k: str(v) for k, v in dotenv_values(env_file).items() if v is not None}

    merged = {**file_vars, **dict(os.environ)} if overlay_environ else dict(file_vars)

    if required_keys:
        missing = [key for key in required_keys if not merged.get(key)]
        if missing:
            checked_paths = [
                str(explicit_path) if explicit_path else "<none>",
                os.environ.get("HOMELAB_ENV", "<not set>"),
                str(Path.cwd() / "homelab" / ".env"),
                str(Path.home() / "dotfiles" / "homelab" / ".env"),
            ]
            msg = (
                f"Missing required homelab configuration key(s): {', '.join(missing)}.\n"
                f"Checked .env locations: {', '.join(checked_paths)}.\n"
                "Please configure ~/dotfiles/homelab/.env or export HOMELAB_ENV."
            )
            raise HomelabConfigError(msg)

    return merged


def get_env_setting(
    key: str,
    default: str = "",
    explicit_path: Path | str | None = None,
    *,
    env_path: Path | str | None = None,
) -> str:
    """Read configuration key from OS environment or local .env file."""
    path = env_path or explicit_path
    if key in os.environ:
        return os.environ[key]

    env_file = find_homelab_env(path)
    if env_file is not None and env_file.is_file():
        vals = dotenv_values(env_file)
        if (val := vals.get(key)) is not None:
            return str(val)

    return default


def ensure_state_dir(path: Path, root_path: Path | None = None) -> None:
    """Ensure directory exists. If running as root, chown to owner of homelab root."""
    path.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        target_root = root_path or find_homelab_root()
        root_stat = target_root.stat()
        os.chown(path, root_stat.st_uid, root_stat.st_gid)

