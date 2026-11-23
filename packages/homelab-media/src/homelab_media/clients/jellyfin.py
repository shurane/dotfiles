"""Jellyfin REST API client for triggering library scans and reconciling metadata/images."""

from __future__ import annotations

from typing import Any

import httpx
from homelab_core.services import make_jellyfin_auth_headers

from homelab_media.clients import DEFAULT_HTTP_TIMEOUT

_APPLY_TIMEOUT = httpx.Timeout(30.0, connect=2.0)


class JellyfinClient:
    """Thin wrapper around the Jellyfin REST API for library refresh and reconciliation."""

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
                    "Fields": "MediaSources,SeriesName,Path,ImageTags",
                },
            )
            resp.raise_for_status()
            return list(resp.json().get("Items", []))

    @staticmethod
    def _identify_item(client: httpx.Client, item: dict[str, Any]) -> bool:
        """Run RemoteSearch + Apply on a single unmatched Series or Movie."""
        search_info: dict[str, object] = {"Name": item["Name"]}
        if year := item.get("ProductionYear"):
            search_info["Year"] = year
        try:
            sr = client.post(
                f"/Items/RemoteSearch/{item['Type']}",
                json={"SearchInfo": search_info, "IncludeDisabledProviders": False},
            )
            sr.raise_for_status()
            results = sr.json()
        except (httpx.HTTPError, ValueError):
            return False
        if not results:
            return False
        try:
            ap = client.post(
                f"/Items/RemoteSearch/Apply/{item['Id']}",
                params={"ReplaceAllImages": "true"},
                json=results[0],
            )
            ap.raise_for_status()
        except httpx.HTTPError:
            # Jellyfin downloads images synchronously during Apply, which can
            # hit a proxy 502 or read timeout even though the apply succeeds.
            pass
        return True

    @staticmethod
    def _download_missing_poster(client: httpx.Client, item_id: str) -> bool:
        """Fetch the top Primary RemoteImage URL and download it directly."""
        try:
            imgs = client.get(f"/Items/{item_id}/RemoteImages", params={"Type": "Primary", "Limit": 1})
            if not imgs.is_success:
                return False
            img_list = imgs.json().get("Images") or []
            top_url = img_list[0].get("Url") if img_list else None
            if not top_url:
                return False
            dl = client.post(
                f"/Items/{item_id}/RemoteImages/Download",
                params={"Type": "Primary", "ImageUrl": top_url},
            )
            return dl.is_success
        except (httpx.HTTPError, ValueError):
            return False

    @staticmethod
    def _refresh_incomplete_series(client: httpx.Client, episodes: list[dict[str, Any]]) -> list[str]:
        """Trigger FullRefresh on series with unnumbered episodes or duplicate/missing episode thumbs."""
        needs_refresh: dict[str, str] = {}
        thumbs_by_series: dict[str, list[str | None]] = {}
        series_names: dict[str, str] = {}

        for ep in episodes:
            if ep.get("Type") != "Episode":
                continue
            sid = ep.get("SeriesId")
            if not sid:
                continue
            sid_str = str(sid)
            sname = str(ep.get("SeriesName") or sid_str)
            series_names[sid_str] = sname
            if ep.get("ParentIndexNumber") is None or ep.get("IndexNumber") is None:
                needs_refresh[sid_str] = sname
            thumbs_by_series.setdefault(sid_str, []).append((ep.get("ImageTags") or {}).get("Primary"))

        for sid_str, tags in thumbs_by_series.items():
            if len(tags) > 1 and len({t for t in tags if t}) < len(tags):
                needs_refresh.setdefault(sid_str, series_names[sid_str])

        refreshed: list[str] = []
        for sid, sname in needs_refresh.items():
            try:
                r = client.post(
                    f"/Items/{sid}/Refresh",
                    params={
                        "MetadataRefreshMode": "FullRefresh",
                        "ImageRefreshMode": "FullRefresh",
                        "ReplaceAllImages": "true",
                    },
                )
                if r.is_success:
                    refreshed.append(sname)
            except httpx.HTTPError:
                continue
        return refreshed

    @staticmethod
    def _probe_missing_media_info(client: httpx.Client, items: list[dict[str, Any]]) -> int:
        """Trigger PlaybackInfo on Movie/Episode items lacking video stream metadata."""
        probed = 0
        for item in items:
            sources = item.get("MediaSources") or []
            streams = sources[0].get("MediaStreams") or [] if sources else []
            video = next((s for s in streams if s.get("Type") == "Video"), None)
            if video and video.get("Width"):
                continue
            if item_id := item.get("Id"):
                try:
                    if client.post(f"/Items/{item_id}/PlaybackInfo").is_success:
                        probed += 1
                except httpx.HTTPError:
                    continue
        return probed

    def reconcile_library(self) -> tuple[list[str], int]:
        """Reconcile unmatched items, missing posters, incomplete series, and unprobed media.

        Returns (updated_names, probed_count).
        """
        if not self.api_key:
            return [], 0

        updated: list[str] = []
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
                top_items = resp.json().get("Items", [])
            except (httpx.HTTPError, ValueError):
                top_items = []

            for item in top_items:
                item_id = item.get("Id")
                name = item.get("Name")
                if not item_id or not name or item.get("Type") not in ("Series", "Movie"):
                    continue
                if not item.get("ProviderIds"):
                    if self._identify_item(client, item):
                        updated.append(str(name))
                elif not item.get("ImageTags") and self._download_missing_poster(client, str(item_id)):
                    updated.append(str(name))

            try:
                media_items = self.fetch_inventory_items()
            except (httpx.HTTPError, ValueError):
                media_items = []

            updated.extend(self._refresh_incomplete_series(client, media_items))
            probed = self._probe_missing_media_info(client, media_items)

        return updated, probed
