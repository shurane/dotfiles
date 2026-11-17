"""Service clients for qBittorrent and Jellyfin."""

from __future__ import annotations

from homelab_media.clients.jellyfin import JellyfinClient
from homelab_media.clients.qbittorrent import QBittorrentClient

__all__ = ["JellyfinClient", "QBittorrentClient"]
