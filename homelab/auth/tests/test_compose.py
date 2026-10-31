from unittest.mock import MagicMock, patch

from bootstrap_auth.compose import compose_service, get_container_ip
from bootstrap_auth.config import get_service_url


def test_compose_service_defaults_to_stack_name() -> None:
    assert compose_service("qui") == "qui"


def test_compose_service_allows_explicit_service_override() -> None:
    assert compose_service("bookorbit", "bookorbit-postgres") == "bookorbit-postgres"


def test_get_service_url_prefers_env_var(monkeypatch: object) -> None:
    with patch.dict("os.environ", {"QBITTORRENT_URL": "http://custom-host:9999"}):
        assert get_service_url("qbittorrent", 8080, "QBITTORRENT_URL") == "http://custom-host:9999"


def test_get_service_url_resolves_via_get_container_ip() -> None:
    with patch("bootstrap_auth.compose.get_container_ip", return_value="172.20.0.99"):
        assert get_service_url("qbittorrent", 8080, "NONEXISTENT_VAR") == "http://172.20.0.99:8080"


def test_get_service_url_falls_back_to_default_hostname() -> None:
    with patch("bootstrap_auth.compose.get_container_ip", return_value=None):
        assert get_service_url("qbittorrent", 8080, "NONEXISTENT_VAR") == "http://qbittorrent:8080"


def test_get_container_ip_extracts_ip_from_container() -> None:
    mock_container = MagicMock()
    mock_container.attrs = {
        "NetworkSettings": {
            "Networks": {
                "proxy-tier": {
                    "IPAddress": "172.20.0.42"
                }
            }
        }
    }
    mock_client = MagicMock()
    mock_client.containers.list.return_value = [mock_container]

    with patch("bootstrap_auth.compose.docker_client", return_value=mock_client):
        assert get_container_ip("test-service") == "172.20.0.42"
        mock_client.containers.list.assert_called_once_with(
            filters={"label": ["com.docker.compose.service=test-service"]}
        )


def test_get_container_ip_returns_none_when_no_container() -> None:
    mock_client = MagicMock()
    mock_client.containers.list.return_value = []

    with patch("bootstrap_auth.compose.docker_client", return_value=mock_client):
        assert get_container_ip("nonexistent") is None
