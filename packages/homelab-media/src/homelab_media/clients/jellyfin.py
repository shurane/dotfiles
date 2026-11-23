"""Jellyfin REST API client for triggering library scans and identifying unmatched items."""

from __future__ import annotations

from typing import Any

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
                        "Fields": "ProviderIds,ProductionYear,ImageTags",
                    },
                )
                resp.raise_for_status()
                items = resp.json().get("Items", [])
            except (httpx.HTTPError, ValueError):
                return identified

            for item in items:
                item_id = item.get("Id")
                name = item.get("Name")
                item_type = item.get("Type")
                if not item_id or not name or item_type not in ("Series", "Movie"):
                    continue

                if item.get("ProviderIds"):
                    if not item.get("ImageTags"):
                        try:
                            imgs = client.get(
                                f"/Items/{item_id}/RemoteImages",
                                params={"Type": "Primary", "Limit": 1},
                            )
                            top_url = (
                                imgs.json().get("Images", [{}])[0].get("Url")
                                if imgs.is_success and imgs.json().get("Images")
                                else None
                            )
                            if top_url:
                                dl = client.post(
                                    f"/Items/{item_id}/RemoteImages/Download",
                                    params={"Type": "Primary", "ImageUrl": top_url},
                                )
                                if dl.is_success:
                                    identified.append(str(name))
                        except (httpx.HTTPError, ValueError):
                            pass
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

    def fetch_inventory_items(self) -> list[dict[str, Any]]:
        """Fetch all Movie and Episode items with MediaSources, SeriesName, and Path."""
        if not self.api_key:
            return []

        with httpx.Client(base_url=self.base_url, headers=self._headers(), timeout=_APPLY_TIMEOUT) as client:
            resp = client.get(
                "/Items",
                params={
                    "Recursive": "true",
                    "IncludeItemTypes": "Movie,Episode",
                    "Fields": "MediaSources,SeriesName,Path",
                },
            )
            resp.raise_for_status()
            return list(resp.json().get("Items", []))

    def probe_missing_media_info(self) -> int:
        """Trigger PlaybackInfo on Movie/Episode items lacking video stream metadata."""
        if not self.api_key:
            return 0

        probed = 0
        with httpx.Client(base_url=self.base_url, headers=self._headers(), timeout=_APPLY_TIMEOUT) as client:
            for item in self.fetch_inventory_items():
                sources = item.get("MediaSources") or []
                streams = sources[0].get("MediaStreams") or [] if sources else []
                video = next((s for s in streams if s.get("Type") == "Video"), None)
                if video and video.get("Width"):
                    continue
                item_id = item.get("Id")
                if not item_id:
                    continue
                try:
                    resp = client.post(f"/Items/{item_id}/PlaybackInfo")
                    if resp.is_success:
                        probed += 1
                except httpx.HTTPError:
                    continue
        return probed
