"""HTTP API clients for qBittorrent, Jellyfin, and TMDB."""

from __future__ import annotations

import httpx

DEFAULT_HTTP_TIMEOUT = httpx.Timeout(5.0, connect=2.0)

__all__ = ["DEFAULT_HTTP_TIMEOUT"]
