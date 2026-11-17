"""TMDB v3 API client for resolving missing release years and canonical titles."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Self

import httpx

from homelab_media.clients import DEFAULT_HTTP_TIMEOUT as DEFAULT_TIMEOUT
from homelab_media.models import MediaKind
from homelab_media.parser import normalize_title_key, sanitize_folder_name


@dataclass(frozen=True, slots=True)
class TmdbMatch:
    """Represents a single search result from TMDB."""

    tmdb_id: int
    title: str
    original_title: str
    year: int | None

    @property
    def folder_name(self) -> str:
        """Format sanitized canonical <Title> (<Year>) directory name."""
        clean = sanitize_folder_name(self.title)
        return f"{clean} ({self.year})" if self.year is not None else clean


class TmdbClient:
    """Cached, connection-pooled client for TMDB v3 /search/tv and /search/movie endpoints."""

    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(
        self,
        *,
        api_key: str = "",
        read_token: str = "",
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.read_token = read_token
        self.timeout = timeout
        self._transport = transport
        self._cache: dict[tuple[MediaKind, str], list[TmdbMatch]] = {}
        self._lock = threading.Lock()
        self._client: httpx.Client | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the pooled HTTP client if open."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            headers: dict[str, str] = {"Accept": "application/json"}
            if self.read_token:
                headers["Authorization"] = f"Bearer {self.read_token}"
            self._client = httpx.Client(
                base_url=self.BASE_URL,
                headers=headers,
                timeout=self.timeout,
                transport=self._transport,
            )
        return self._client

    @property
    def is_configured(self) -> bool:
        """Return True if either a TMDB read token or API key is available."""
        return bool(self.read_token or self.api_key)

    def search(self, kind: MediaKind, query: str) -> list[TmdbMatch]:
        """Search TMDB for TV shows or movies matching query, with per-scan caching."""
        cache_key = (kind, normalize_title_key(query))
        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        if not self.is_configured:
            return []

        endpoint = "/search/tv" if kind == MediaKind.TV else "/search/movie"
        params: dict[str, str] = {"query": query, "include_adult": "false"}
        if not self.read_token and self.api_key:
            params["api_key"] = self.api_key

        try:
            with self._lock:
                client = self._get_client()
            resp = client.get(endpoint, params=params)
            resp.raise_for_status()
            payload: dict[str, Any] = resp.json()
        except (httpx.HTTPError, ValueError):
            with self._lock:
                self._cache[cache_key] = []
            return []

        matches: list[TmdbMatch] = []
        for raw in payload.get("results", [])[:5]:
            title = str(raw.get("name") or raw.get("title") or "").strip()
            orig_title = str(raw.get("original_name") or raw.get("original_title") or title).strip()
            date_str = str(raw.get("first_air_date") or raw.get("release_date") or "")
            year = int(date_str[:4]) if len(date_str) >= 4 and date_str[:4].isdigit() else None
            if title:
                matches.append(
                    TmdbMatch(
                        tmdb_id=int(raw.get("id", 0)),
                        title=title,
                        original_title=orig_title,
                        year=year,
                    )
                )

        with self._lock:
            self._cache[cache_key] = matches
        return matches

    def resolve(self, kind: MediaKind, query: str) -> tuple[TmdbMatch | None, list[TmdbMatch]]:
        """Attempt to resolve a single confident match, or return candidate matches if ambiguous."""
        matches = [m for m in self.search(kind, query) if m.year is not None]
        if not matches:
            return None, []

        q_norm = normalize_title_key(query)
        exact = [
            m
            for m in matches
            if normalize_title_key(m.title) == q_norm or normalize_title_key(m.original_title) == q_norm
        ]
        if len(exact) == 1:
            return exact[0], matches
        if len(exact) > 1:
            return None, exact[:3]
        if len(matches) == 1:
            return matches[0], matches

        return None, matches[:3]
