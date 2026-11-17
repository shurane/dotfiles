from __future__ import annotations

from homelab_core.models import HomelabAuth
from homelab_core.services import Service
from pydantic import BaseModel

__all__ = [
    "AUTH_SERVICES",
    "SERVICE_NAMES",
    "BootstrapOptions",
    "HomelabAuth",
    "Service",
]

AUTH_SERVICES = (
    Service.QBITTORRENT,
    Service.QUI,
    Service.ARCANE,
    Service.JELLYFIN,
    Service.BOOKORBIT,
)

SERVICE_NAMES = tuple(service.value for service in AUTH_SERVICES)


class BootstrapOptions(BaseModel):
    apply: bool = False
    parallel: bool = False
    skip_backup: bool = False
    services: tuple[Service, ...]
