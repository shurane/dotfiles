import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUTH_ENV = Path(os.environ.get("AUTH_ENV", ROOT / ".env"))


def get_service_url(service_name: str, default_port: int, env_var: str) -> str:
    """Resolve the service HTTP base URL.

    1. Uses explicit environment variable override if provided.
    2. Uses container hostname if running inside a Docker container (/.dockerenv exists).
    3. Queries local Docker engine for the container's bridge IP on proxy-tier when on host.
    4. Falls back to http://{service_name}:{default_port}.
    """
    env_val = os.environ.get(env_var)
    if env_val:
        return env_val.rstrip("/")

    if Path("/.dockerenv").exists():
        return f"http://{service_name}:{default_port}"

    try:
        from .compose import get_container_ip

        ip = get_container_ip(service_name)
        if ip:
            return f"http://{ip}:{default_port}"
    except Exception:
        pass

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
        case _:
            raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

