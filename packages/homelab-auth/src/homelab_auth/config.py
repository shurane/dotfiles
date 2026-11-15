import contextlib
import os
from pathlib import Path


def find_homelab_root() -> Path:
    """Locate the homelab/ directory containing docker-compose.yml.

    Searches upward from the current file until the repository root (.git) or filesystem root.
    Falls back to ~/dotfiles/homelab.
    """
    if env_dir := os.environ.get("HOMELAB_DIR"):
        return Path(env_dir).resolve()

    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "homelab" / "docker-compose.yml").is_file():
            return parent / "homelab"
        if parent.name == "homelab" and (parent / "docker-compose.yml").is_file():
            return parent
        if (parent / ".git").exists() or parent == parent.parent:
            break

    return Path.home() / "dotfiles" / "homelab"


ROOT = find_homelab_root()
AUTH_ENV = Path(os.environ.get("AUTH_ENV", ROOT / ".env"))


def get_service_url(service_name: str, default_port: int, env_var: str) -> str:
    """Resolve the service HTTP base URL."""
    if env_val := os.environ.get(env_var):
        return env_val.rstrip("/")

    from homelab_auth.compose import get_container_ip

    with contextlib.suppress(Exception):
        if ip := get_container_ip(service_name):
            return f"http://{ip}:{default_port}"

    with contextlib.suppress(Exception):
        from homelab_auth.common import load_env

        if AUTH_ENV.exists():
            env = load_env(AUTH_ENV)
            if base_domain := env.get("HOSTNAME_BASE"):
                return f"https://{service_name}.{base_domain}"
            if homelab_host := env.get("HOMELAB_HOSTNAME"):
                return f"http://{homelab_host}:{default_port}"

    return f"http://{service_name}:{default_port}"


def __getattr__(name: str) -> str:
    match name:
        case "QBITTORRENT_URL":
            return get_service_url("qbittorrent", 8080, "QBITTORRENT_URL")
        case "QUI_URL":
            return get_service_url("qui", 7476, "QUI_URL")
        case "ARCANE_URL":
            return get_service_url("arcane", 3552, "ARCANE_URL")
        case "JELLYFIN_URL":
            return get_service_url("jellyfin", 8096, "JELLYFIN_URL")
        case "BOOKORBIT_URL":
            return get_service_url("bookorbit", 3000, "BOOKORBIT_URL")
        case _:
            raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
