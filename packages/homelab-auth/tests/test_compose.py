from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from homelab_auth.compose import compose_service, docker_client
from homelab_auth.config import get_service_url

if TYPE_CHECKING:
    from pathlib import Path


def test_compose_service_defaults_to_stack_name() -> None:
    assert compose_service("qui") == "qui"


def test_compose_service_allows_explicit_service_override() -> None:
    assert compose_service("bookorbit", "bookorbit-postgres") == "bookorbit-postgres"


def test_get_service_url_prefers_env_var(monkeypatch: object) -> None:
    with patch.dict("os.environ", {"QBITTORRENT_URL": "http://custom-host:9999"}):
        assert get_service_url("qbittorrent", 8080, "QBITTORRENT_URL") == "http://custom-host:9999"


def test_get_service_url_falls_back_to_default_hostname(tmp_path: Path) -> None:
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("")
    with patch("homelab_auth.config.HOMELAB_ENV", empty_env):
        assert get_service_url("qbittorrent", 8080, "NONEXISTENT_VAR") == "http://qbittorrent:8080"


def test_get_service_url_resolves_via_auth_env_base_domain(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("HOSTNAME_BASE=cluster.lan\n")
    with patch("homelab_auth.config.HOMELAB_ENV", env_file):
        assert get_service_url("qbittorrent", 8080, "NONEXISTENT_VAR") == "https://qbittorrent.cluster.lan"


def test_docker_client_delegates_to_homelab_core() -> None:
    mock_client = MagicMock()
    with patch("homelab_auth.compose.get_docker_client", return_value=mock_client):
        assert docker_client() is mock_client


def test_docker_client_raises_when_daemon_unavailable() -> None:
    with (
        patch("homelab_auth.compose.get_docker_client", return_value=None),
        pytest.raises(RuntimeError, match="failed to connect to Docker daemon"),
    ):
        docker_client()
