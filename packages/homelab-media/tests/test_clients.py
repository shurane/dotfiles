"""Unit tests for TMDB, qBittorrent, and Jellyfin HTTP clients."""

from __future__ import annotations

import httpx
from homelab_media.clients.jellyfin import JellyfinClient
from homelab_media.clients.qbittorrent import QBittorrentClient
from homelab_media.clients.tmdb import TmdbClient
from homelab_media.models import MediaKind


def test_tmdb_client_caches_and_resolves_exact_match() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.headers["Authorization"] == "Bearer tok123"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": 1001,
                        "name": "NIPPON SANGOKU: The Three Nations",
                        "original_name": "日本三国",
                        "first_air_date": "2026-04-05",
                    }
                ]
            },
        )

    client = TmdbClient(read_token="tok123", transport=httpx.MockTransport(handler))

    match, _ = client.resolve(MediaKind.TV, "Nippon Sangoku")
    assert match is not None
    assert match.year == 2026
    assert match.folder_name == "NIPPON SANGOKU - The Three Nations (2026)"

    match2, _ = client.resolve(MediaKind.TV, "Nippon Sangoku")
    assert match2 == match
    assert calls == 1


def test_tmdb_client_ambiguous_returns_candidates() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"id": 438631, "title": "Dune", "original_title": "Dune", "release_date": "2021-09-15"},
                    {"id": 841, "title": "Dune", "original_title": "Dune", "release_date": "1984-12-14"},
                ]
            },
        )

    client = TmdbClient(api_key="key123", transport=httpx.MockTransport(handler))

    best, candidates = client.resolve(MediaKind.MOVIE, "Dune")
    assert best is None
    assert len(candidates) == 2
    assert candidates[0].folder_name == "Dune (2021)"
    assert candidates[1].folder_name == "Dune (1984)"


def test_tmdb_client_handles_http_error_gracefully() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"status_message": "Rate limit"})

    client = TmdbClient(api_key="key123", transport=httpx.MockTransport(handler))

    best, candidates = client.resolve(MediaKind.TV, "Some Show")
    assert best is None
    assert candidates == []


def test_qbittorrent_accepts_204_login_and_parses_torrents(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(204)
        if request.url.path == "/api/v2/torrents/info":
            return httpx.Response(
                200,
                json=[
                    {
                        "hash": "abc",
                        "name": "Ramy (2019)",
                        "progress": 1.0,
                        "state": "stalledUP",
                        "size": 1234,
                        "content_path": "/mnt/mango/torrents/tv/Ramy (2019)",
                    }
                ],
            )
        return httpx.Response(404)

    orig_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: orig_client(transport=httpx.MockTransport(handler), **kw),
    )
    qb = QBittorrentClient("https://qb.local", "ehtesh", "secret")
    online, items = qb.fetch_torrents()
    assert online is True
    assert len(items) == 1
    assert items[0].name == "Ramy (2019)"


def test_qbittorrent_rejects_fails_and_handles_timeout(monkeypatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Fails.")

    orig_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: orig_client(transport=httpx.MockTransport(handler), **kw),
    )
    qb = QBittorrentClient("https://qb.local", "ehtesh", "wrong")
    online, items = qb.fetch_torrents()
    assert online is False
    assert items == []


def test_jellyfin_client_missing_key_and_success(monkeypatch) -> None:
    jf_no_key = JellyfinClient("https://jf.local", "")
    ok, msg = jf_no_key.trigger_refresh()
    assert ok is False
    assert "JELLYFIN_API_KEY" in msg

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/Library/Refresh"
        return httpx.Response(204)

    orig_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: orig_client(transport=httpx.MockTransport(handler), **kw),
    )
    jf = JellyfinClient("https://jf.local", "secret-token")
    ok, _ = jf.trigger_refresh()
    assert ok is True
