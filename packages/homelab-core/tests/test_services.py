"""Unit tests for homelab_core.services."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from homelab_core.services import (
    ContainerName,
    Service,
    get_service_by_container,
    get_service_meta,
    make_jellyfin_auth_headers,
    resolve_service_health_url,
    resolve_service_url,
    wait_for_http,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_service_catalog() -> None:
    meta = get_service_meta(Service.QBITTORRENT)
    assert meta is not None
    assert meta.default_port == 8080
    assert meta.subdomain == "qbittorrent"
    assert meta.container_name == ContainerName.QBITTORRENT

    meta_str = get_service_meta("jellyfin")
    assert meta_str is not None
    assert meta_str.default_port == 8096

    assert get_service_meta("invalid-service") is None


def test_get_service_by_container() -> None:
    meta = get_service_by_container(ContainerName.JELLYFIN)
    assert meta is not None
    assert meta.service == Service.JELLYFIN

    assert get_service_by_container("nonexistent-container") is None


def test_resolve_service_url_env_override() -> None:
    with patch.dict("os.environ", {"QBITTORRENT_URL": "http://custom-host:9999/"}):
        assert resolve_service_url(Service.QBITTORRENT) == "http://custom-host:9999"


def test_resolve_service_url_base_domain() -> None:
    with patch.dict("os.environ", {}, clear=True):
        url = resolve_service_url(Service.JELLYFIN, base_domain="example.com")
        assert url == "https://jellyfin.example.com"


def test_resolve_service_url_sanitizes_scheme_in_domain() -> None:
    with patch.dict("os.environ", {}, clear=True):
        url = resolve_service_url(Service.JELLYFIN, base_domain="https://example.com/")
        assert url == "https://jellyfin.example.com"


def test_resolve_service_url_base_domain_http() -> None:
    with patch.dict("os.environ", {}, clear=True):
        url = resolve_service_url(Service.QUI, base_domain="example.com", use_https=False)
        assert url == "http://qui.example.com"


def test_resolve_service_url_host() -> None:
    with patch.dict("os.environ", {}, clear=True):
        url = resolve_service_url(Service.ARCANE, host="m70q.lan")
        assert url == "http://m70q.lan:3552"


def test_resolve_service_url_fallback(tmp_path: Path) -> None:
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("")
    with patch.dict("os.environ", {}, clear=True):
        url = resolve_service_url(Service.BOOKORBIT, env_path=empty_env)
        assert url == "http://bookorbit:3000"


def test_wait_for_http_success() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock(status_code=200)
    mock_client.get.return_value = mock_response

    wait_for_http(mock_client, "http://localhost:8080/health", timeout_seconds=1.0)
    mock_client.get.assert_called_once_with("http://localhost:8080/health")


def test_wait_for_http_timeout() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock(status_code=503)
    mock_client.get.return_value = mock_response

    with pytest.raises(RuntimeError, match="timed out waiting for"):
        wait_for_http(mock_client, "http://localhost:8080/health", timeout_seconds=0.01, poll_interval=0.01)


def test_make_jellyfin_auth_headers() -> None:
    headers_no_tok = make_jellyfin_auth_headers(client="test-client", device="test-dev", version="2.0")
    expected_auth = 'MediaBrowser Client="test-client", Device="test-dev", DeviceId="homelab", Version="2.0"'
    assert headers_no_tok["Authorization"] == expected_auth
    assert headers_no_tok["X-Emby-Authorization"] == expected_auth
    assert "X-Emby-Token" not in headers_no_tok

    headers_tok = make_jellyfin_auth_headers(token="secret-token-123", client="my-app")
    assert 'Token="secret-token-123"' in headers_tok["Authorization"]
    assert headers_tok["X-Emby-Token"] == "secret-token-123"


def test_resolve_service_health_url() -> None:
    with patch.dict("os.environ", {}, clear=True):
        url = resolve_service_health_url(Service.BOOKORBIT, base_domain="example.com")
        assert url == "https://bookorbit.example.com/api/v1/health"

        url_arcane = resolve_service_health_url(Service.ARCANE, base_domain="example.com")
        assert url_arcane == "https://arcane.example.com/api/health"

        url_qb = resolve_service_health_url(Service.QBITTORRENT, host="m70q.lan")
        assert url_qb == "http://m70q.lan:8080/api/v2/app/version"


def test_wait_for_http_with_predicate() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"status": "UP"}
    mock_client.get.return_value = mock_response

    wait_for_http(
        mock_client,
        "http://localhost:3552/api/health",
        timeout_seconds=1.0,
        predicate=lambda r: r.json().get("status") == "UP",
    )
    mock_client.get.assert_called_once_with("http://localhost:3552/api/health")


