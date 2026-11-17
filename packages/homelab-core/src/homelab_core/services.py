"""Homelab service catalog, ports, subdomains, and canonical URL resolution."""

from __future__ import annotations

import contextlib
import os
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import httpx

from homelab_core.env import get_env_setting

if TYPE_CHECKING:
    from collections.abc import Callable, Set
    from pathlib import Path

__all__ = [
    "SERVICE_CATALOG",
    "ContainerName",
    "Service",
    "ServiceMetadata",
    "get_service_by_container",
    "get_service_meta",
    "make_jellyfin_auth_headers",
    "resolve_service_health_url",
    "resolve_service_url",
    "wait_for_http",
]


class Service(StrEnum):
    QBITTORRENT = "qbittorrent"
    QUI = "qui"
    ARCANE = "arcane"
    JELLYFIN = "jellyfin"
    BOOKORBIT = "bookorbit"
    BOOKORBIT_POSTGRES = "bookorbit-postgres"
    CADDY = "caddy"
    GLANCE = "glance"
    GLUETUN = "gluetun"
    RETROARCH = "retroarch"
    SAMBA = "samba"
    WITHINGS_SYNC = "withings-sync"


class ContainerName(StrEnum):
    ARCANE = "homelab-arcane-1"
    BOOKORBIT = "homelab-bookorbit-1"
    BOOKORBIT_POSTGRES = "homelab-bookorbit-postgres-1"
    CADDY = "homelab-caddy-1"
    GLANCE = "homelab-glance-1"
    GLUETUN = "homelab-gluetun-1"
    JELLYFIN = "homelab-jellyfin-1"
    QBITTORRENT = "homelab-qbittorrent-1"
    QUI = "homelab-qui-1"
    RETROARCH = "homelab-rclone-retroarch-1"
    SAMBA = "homelab-samba-1"
    WITHINGS_SYNC = "homelab-withings-sync-1"


@dataclass(frozen=True, slots=True)
class ServiceMetadata:
    service: Service
    display_name: str
    default_port: int
    subdomain: str
    container_name: ContainerName | str
    health_path: str = "/"


SERVICE_CATALOG: dict[Service, ServiceMetadata] = {
    Service.QBITTORRENT: ServiceMetadata(
        service=Service.QBITTORRENT,
        display_name="qBittorrent",
        default_port=8080,
        subdomain="qbittorrent",
        container_name=ContainerName.QBITTORRENT,
        health_path="/api/v2/app/version",
    ),
    Service.QUI: ServiceMetadata(
        service=Service.QUI,
        display_name="Qui",
        default_port=7476,
        subdomain="qui",
        container_name=ContainerName.QUI,
        health_path="/",
    ),
    Service.ARCANE: ServiceMetadata(
        service=Service.ARCANE,
        display_name="Arcane",
        default_port=3552,
        subdomain="arcane",
        container_name=ContainerName.ARCANE,
        health_path="/api/health",
    ),
    Service.JELLYFIN: ServiceMetadata(
        service=Service.JELLYFIN,
        display_name="Jellyfin",
        default_port=8096,
        subdomain="jellyfin",
        container_name=ContainerName.JELLYFIN,
        health_path="/System/Ping",
    ),
    Service.BOOKORBIT: ServiceMetadata(
        service=Service.BOOKORBIT,
        display_name="BookOrbit",
        default_port=3000,
        subdomain="bookorbit",
        container_name=ContainerName.BOOKORBIT,
        health_path="/api/v1/health",
    ),
    Service.BOOKORBIT_POSTGRES: ServiceMetadata(
        service=Service.BOOKORBIT_POSTGRES,
        display_name="BookOrbit PostgreSQL",
        default_port=5432,
        subdomain="bookorbit-db",
        container_name=ContainerName.BOOKORBIT_POSTGRES,
        health_path="",
    ),
    Service.CADDY: ServiceMetadata(
        service=Service.CADDY,
        display_name="Caddy Reverse Proxy",
        default_port=443,
        subdomain="caddy",
        container_name=ContainerName.CADDY,
        health_path="/",
    ),
    Service.GLANCE: ServiceMetadata(
        service=Service.GLANCE,
        display_name="Glance",
        default_port=8080,
        subdomain="glance",
        container_name=ContainerName.GLANCE,
        health_path="/",
    ),
    Service.GLUETUN: ServiceMetadata(
        service=Service.GLUETUN,
        display_name="Gluetun VPN",
        default_port=8000,
        subdomain="gluetun",
        container_name=ContainerName.GLUETUN,
        health_path="/v1/publicip/ip",
    ),
    Service.RETROARCH: ServiceMetadata(
        service=Service.RETROARCH,
        display_name="RetroArch Cloud Sync",
        default_port=8080,
        subdomain="retroarch",
        container_name=ContainerName.RETROARCH,
        health_path="/",
    ),
    Service.SAMBA: ServiceMetadata(
        service=Service.SAMBA,
        display_name="Samba SMB",
        default_port=445,
        subdomain="samba",
        container_name=ContainerName.SAMBA,
        health_path="",
    ),
    Service.WITHINGS_SYNC: ServiceMetadata(
        service=Service.WITHINGS_SYNC,
        display_name="Withings Sync",
        default_port=8080,
        subdomain="withings",
        container_name=ContainerName.WITHINGS_SYNC,
        health_path="",
    ),
}


def get_service_meta(service: Service | str) -> ServiceMetadata | None:
    """Retrieve service metadata by Service enum or raw string name."""
    with contextlib.suppress(ValueError):
        enum_val = Service(service)
        return SERVICE_CATALOG.get(enum_val)
    return None


def get_service_by_container(container_name: str) -> ServiceMetadata | None:
    """Find service metadata matching a Docker container name."""
    for meta in SERVICE_CATALOG.values():
        if meta.container_name == container_name:
            return meta
    return None


def resolve_service_url(
    service: Service | str,
    base_domain: str | None = None,
    host: str | None = None,
    *,
    use_https: bool = True,
    env_override: str | None = None,
    env_path: Path | None = None,
    default_port: int | None = None,
) -> str:
    """Resolve canonical service URL.

    Precedence:
    1. Explicit env override argument.
    2. Explicit environment variable: <SERVICE>_URL or HOMELAB_<SERVICE>_URL.
    3. Caddy reverse-proxied domain: https://<subdomain>.<base_domain>.
    4. Direct LAN host: http://<host>:<port>.
    5. Fallback: http://<service>:<port>.
    """
    if env_override:
        return env_override.rstrip("/")

    svc_name = service.value if isinstance(service, Service) else str(service)
    meta = get_service_meta(svc_name)

    env_var_name = f"{svc_name.replace('-', '_').upper()}_URL"
    if env_val := (os.environ.get(env_var_name) or os.environ.get(f"HOMELAB_{env_var_name}")):
        return env_val.rstrip("/")

    subdomain = meta.subdomain if meta else svc_name
    port = meta.default_port if meta else (default_port or 80)

    if base_domain:
        clean_domain = base_domain.removeprefix("https://").removeprefix("http://").rstrip("/")
        scheme = "https" if use_https else "http"
        return f"{scheme}://{subdomain}.{clean_domain}"

    if host:
        return f"http://{host}:{port}"

    if env_domain := get_env_setting("HOSTNAME_BASE", env_path=env_path):
        clean_domain = env_domain.removeprefix("https://").removeprefix("http://").rstrip("/")
        scheme = "https" if use_https else "http"
        return f"{scheme}://{subdomain}.{clean_domain}"

    if env_host := get_env_setting("HOMELAB_HOSTNAME", env_path=env_path):
        return f"http://{env_host}:{port}"

    return f"http://{svc_name}:{port}"


def resolve_service_health_url(
    service: Service | str,
    base_domain: str | None = None,
    host: str | None = None,
    *,
    use_https: bool = True,
    env_override: str | None = None,
    env_path: Path | None = None,
) -> str:
    """Resolve canonical HTTP health check URL for a service (base URL + health_path)."""
    base = resolve_service_url(
        service,
        base_domain=base_domain,
        host=host,
        use_https=use_https,
        env_override=env_override,
        env_path=env_path,
    )
    meta = get_service_meta(service)
    path = meta.health_path if meta else "/"
    return f"{base.rstrip('/')}/{path.lstrip('/')}" if path else base.rstrip("/")


def wait_for_http(
    client: httpx.Client,
    url: str,
    ready_statuses: Set[int] | tuple[int, ...] = (200,),
    timeout_seconds: float = 60.0,
    poll_interval: float = 2.0,
    predicate: Callable[[httpx.Response], bool] | None = None,
) -> None:
    """Poll an HTTP URL until it returns one of the ready_statuses (and satisfies predicate) or times out."""
    deadline = time.monotonic() + timeout_seconds
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            response = client.get(url)
            last_error = f"HTTP {response.status_code}"
            if response.status_code in ready_statuses and (predicate is None or predicate(response)):
                return
        except (httpx.HTTPError, ValueError) as error:
            last_error = str(error)
        time.sleep(poll_interval)
    raise RuntimeError(f"timed out waiting for {url}; last result: {last_error}")


def make_jellyfin_auth_headers(
    token: str | None = None,
    *,
    client: str = "homelab",
    device: str = "homelab",
    device_id: str = "homelab",
    version: str = "1.0.0",
) -> dict[str, str]:
    """Construct standard Jellyfin/Emby authorization headers."""
    auth_parts = [
        f'MediaBrowser Client="{client}"',
        f'Device="{device}"',
        f'DeviceId="{device_id}"',
        f'Version="{version}"',
    ]
    if token:
        auth_parts.append(f'Token="{token}"')
    auth_header = ", ".join(auth_parts)
    headers = {
        "Authorization": auth_header,
        "X-Emby-Authorization": auth_header,
    }
    if token:
        headers["X-Emby-Token"] = token
    return headers

