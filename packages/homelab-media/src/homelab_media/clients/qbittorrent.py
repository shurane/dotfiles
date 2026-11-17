"""qBittorrent WebUI REST API client for querying torrent download states."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from homelab_media.models import TorrentItem

DEFAULT_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


class QBittorrentClient:
    """Client for qBittorrent v2 WebUI REST API."""

    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        *,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout

    def fetch_torrents(self) -> tuple[bool, list[TorrentItem]]:
        """Authenticate and fetch all torrents from qBittorrent.

        Returns (is_online, list_of_torrents). Falls back gracefully on network/auth errors.
        """
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
                if self.username and self.password:
                    login_resp = client.post(
                        "/api/v2/auth/login",
                        data={"username": self.username, "password": self.password},
                    )
                    if not login_resp.is_success or login_resp.text.strip() == "Fails.":
                        return False, []

                resp = client.get("/api/v2/torrents/info")
                resp.raise_for_status()
                raw_items: list[dict[str, Any]] = resp.json()
        except (httpx.HTTPError, ValueError):
            return False, []

        return True, [
            TorrentItem(
                hash=str(item.get("hash", "")),
                name=str(item.get("name", "")),
                category=str(item.get("category", "")),
                progress=float(item.get("progress", 0.0)),
                state=str(item.get("state", "")),
                dlspeed=int(item.get("dlspeed", 0)),
                eta=int(item.get("eta", 0)),
                size=int(item.get("size", 0)),
                content_path=Path(str(item.get("content_path", ""))),
            )
            for item in raw_items
        ]
