from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ServiceName(StrEnum):
    QBITTORRENT = "qbittorrent"
    QUI = "qui"
    ARCANE = "arcane"
    JELLYFIN = "jellyfin"


SERVICE_NAMES = tuple(service.value for service in ServiceName)


class HomelabAuth(BaseModel):
    model_config = ConfigDict(extra="ignore")

    username: str = Field(alias="HOMELAB_AUTH_USERNAME", min_length=1)
    password: str = Field(alias="HOMELAB_AUTH_PASSWORD", min_length=8)


class BootstrapOptions(BaseModel):
    parallel: bool = False
    skip_backup: bool = False
    services: tuple[ServiceName, ...]
