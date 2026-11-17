"""Jellyfin REST API client for triggering library scans."""

from __future__ import annotations

import httpx
from homelab_core.services import make_jellyfin_auth_headers

from homelab_media.clients import DEFAULT_HTTP_TIMEOUT


class JellyfinClient:
    """Thin wrapper around the Jellyfin REST API for library refresh."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float | httpx.Timeout = DEFAULT_HTTP_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def trigger_refresh(self) -> tuple[bool, str]:
        """Trigger a full Jellyfin library refresh.

        Returns (success, message).
        """
        if not self.api_key:
            return False, "JELLYFIN_API_KEY is not configured"

        url = f"{self.base_url}/Library/Refresh"
        headers = make_jellyfin_auth_headers(token=self.api_key, client="homelab-media")
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, headers=headers)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            return False, f"Jellyfin refresh failed: {exc}"
        return True, f"Triggered Jellyfin library refresh at {url}"
