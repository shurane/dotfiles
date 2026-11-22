"""Jellyfin REST API client for triggering library scans and identifying unmatched items."""

from __future__ import annotations

import httpx
from homelab_core.services import make_jellyfin_auth_headers

from homelab_media.clients import DEFAULT_HTTP_TIMEOUT

_APPLY_TIMEOUT = httpx.Timeout(30.0, connect=2.0)


class JellyfinClient:
    """Thin wrapper around the Jellyfin REST API for library refresh and identification."""

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

    def _headers(self) -> dict[str, str]:
        return make_jellyfin_auth_headers(token=self.api_key, client="homelab-media")

    def trigger_refresh(self) -> tuple[bool, str]:
        """Trigger a full Jellyfin library refresh.

        Returns (success, message).
        """
        if not self.api_key:
            return False, "JELLYFIN_API_KEY is not configured"

        url = f"{self.base_url}/Library/Refresh"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, headers=self._headers())
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            return False, f"Jellyfin refresh failed: {exc}"
        return True, f"Triggered Jellyfin library refresh at {url}"

    def identify_unmatched(self) -> list[str]:
        """Find Series/Movie items with empty ProviderIds and apply their top RemoteSearch match.

        Returns the list of newly identified item names.
        """
        if not self.api_key:
            return []

        identified: list[str] = []
        with httpx.Client(base_url=self.base_url, headers=self._headers(), timeout=_APPLY_TIMEOUT) as client:
            try:
                resp = client.get(
                    "/Items",
                    params={
                        "Recursive": "true",
                        "IncludeItemTypes": "Series,Movie",
                        "Fields": "ProviderIds,ProductionYear",
                    },
                )
                resp.raise_for_status()
                items = resp.json().get("Items", [])
            except (httpx.HTTPError, ValueError):
                return identified

            for item in items:
                if item.get("ProviderIds"):
                    continue
                item_id = item.get("Id")
                name = item.get("Name")
                item_type = item.get("Type")
                if not item_id or not name or item_type not in ("Series", "Movie"):
                    continue

                search_info: dict[str, object] = {"Name": name}
                if year := item.get("ProductionYear"):
                    search_info["Year"] = year

                try:
                    sr = client.post(
                        f"/Items/RemoteSearch/{item_type}",
                        json={"SearchInfo": search_info, "IncludeDisabledProviders": False},
                    )
                    sr.raise_for_status()
                    results = sr.json()
                except (httpx.HTTPError, ValueError):
                    continue

                if not results:
                    continue

                try:
                    ap = client.post(
                        f"/Items/RemoteSearch/Apply/{item_id}",
                        params={"ReplaceAllImages": "true"},
                        json=results[0],
                    )
                    ap.raise_for_status()
                except httpx.HTTPError:
                    # Jellyfin downloads images synchronously during Apply, which can
                    # hit a proxy 502 or read timeout even though the apply succeeds.
                    pass
                identified.append(str(name))

        return identified
