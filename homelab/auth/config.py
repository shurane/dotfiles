import contextlib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTH_ENV = Path(os.environ.get("AUTH_ENV", ROOT / ".env"))


def get_service_url(service_name: str, default_port: int, env_var: str) -> str:
    """Resolve the service HTTP base URL."""
    if env_val := os.environ.get(env_var):
        return env_val.rstrip("/")

    from compose import get_container_ip

    with contextlib.suppress(Exception):
        if ip := get_container_ip(service_name):
            return f"http://{ip}:{default_port}"

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
