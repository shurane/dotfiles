"""Service check registry and exports."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from .arcane import check_arcane
from .bookorbit import check_bookorbit
from .caddy import check_caddy
from .glance import check_glance
from .jellyfin import check_jellyfin
from .postgres import check_postgres
from .qbittorrent import check_qbittorrent
from .qui import check_qui
from .retroarch import check_retroarch
from .samba import check_samba
from .withings_sync import check_withings_sync

if TYPE_CHECKING:
    from ..models import ServiceResult, StatusContext

CheckFn = Callable[["StatusContext"], Coroutine[Any, Any, "ServiceResult"]]

CHECK_REGISTRY: dict[str, CheckFn] = {
    "jellyfin": check_jellyfin,
    "bookorbit": check_bookorbit,
    "qbittorrent": check_qbittorrent,
    "retroarch": check_retroarch,
    "caddy": check_caddy,
    "samba": check_samba,
    "arcane": check_arcane,
    "qui": check_qui,
    "glance": check_glance,
    "withings-sync": check_withings_sync,
    "postgres": check_postgres,
}

__all__ = [
    "CHECK_REGISTRY",
    "check_arcane",
    "check_bookorbit",
    "check_caddy",
    "check_glance",
    "check_jellyfin",
    "check_postgres",
    "check_qbittorrent",
    "check_qui",
    "check_retroarch",
    "check_samba",
    "check_withings_sync",
]
