"""Unit tests for homelab_core.docker."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from homelab_core.docker import (
    compose_stop,
    compose_up,
    exec_container,
    get_compose_container,
    get_docker_client,
    list_compose_containers,
    require_docker_client,
)
from homelab_core.errors import HomelabConnectionError, HomelabError
from homelab_core.services import Service

if TYPE_CHECKING:
    from pathlib import Path


def test_get_docker_client_no_docker_returns_none() -> None:
    assert get_docker_client(no_docker=True) is None


def test_get_docker_client_docker_host_override() -> None:
    mock_client = MagicMock()
    with patch("docker.DockerClient", return_value=mock_client) as mock_init:
        client = get_docker_client(docker_host="tcp://127.0.0.1:2375")
        assert client is mock_client
        mock_init.assert_called_once_with(base_url="tcp://127.0.0.1:2375", timeout=5)
        mock_client.ping.assert_called_once()


def test_get_docker_client_reuses_existing_healthy_socket(tmp_path: Path) -> None:
    sock_path = tmp_path / "homelab-docker-test.sock"
    sock_path.touch()

    mock_client = MagicMock()
    with (
        patch.dict("os.environ", {"XDG_RUNTIME_DIR": str(tmp_path)}),
        patch("os.getuid", return_value=1000),
        patch("os.getpid", return_value=2000),
    ):
        expected_sock = tmp_path / "homelab-docker-1000-2000.sock"
        expected_sock.touch()

        with patch("docker.DockerClient", return_value=mock_client) as mock_init:
            client = get_docker_client(lan_host="remote.lan")
            assert client is mock_client
            mock_init.assert_called_once_with(base_url=f"unix://{expected_sock}", timeout=1.0)
            mock_client.ping.assert_called_once()
            # Verify the socket was not deleted
            assert expected_sock.exists()


def test_require_docker_client() -> None:
    mock_client = MagicMock()
    with patch("homelab_core.docker.get_docker_client", return_value=mock_client):
        assert require_docker_client() is mock_client

    with (
        patch("homelab_core.docker.get_docker_client", return_value=None),
        pytest.raises(HomelabConnectionError, match="Failed to connect to Docker daemon"),
    ):
        require_docker_client()


def test_list_compose_containers() -> None:
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_client.containers.list.return_value = [mock_container]

    result = list_compose_containers(mock_client, Service.QUI)
    assert result == [mock_container]
    mock_client.containers.list.assert_called_once_with(
        all=True,
        filters={"label": ["com.docker.compose.service=qui"]},
    )


def test_get_compose_container() -> None:
    mock_client = MagicMock()
    c1 = MagicMock()
    c2 = MagicMock()

    # None found
    mock_client.containers.list.return_value = []
    assert get_compose_container(mock_client, "jellyfin") is None

    # Single container found
    mock_client.containers.list.return_value = [c1]
    assert get_compose_container(mock_client, "jellyfin") is c1

    # Multiple containers found
    mock_client.containers.list.return_value = [c1, c2]
    with pytest.raises(HomelabError, match="Expected at most one Compose container"):
        get_compose_container(mock_client, "jellyfin")


def test_exec_container() -> None:
    mock_container = MagicMock()
    mock_container.name = "test-container"

    # Successful execution
    mock_res = MagicMock()
    mock_res.exit_code = 0
    mock_res.output = b"hello world\n"
    mock_container.exec_run.return_value = mock_res

    code, out = exec_container(mock_container, ["echo", "hello"])
    assert code == 0
    assert out == "hello world\n"

    # Failed without check
    mock_res.exit_code = 1
    mock_res.output = b"command error"
    code, out = exec_container(mock_container, ["fail"], check=False)
    assert code == 1
    assert out == "command error"

    # Failed with check=True raises HomelabError
    with pytest.raises(HomelabError, match="command \\['fail'\\] failed with exit code 1"):
        exec_container(mock_container, ["fail"], check=True)


def test_compose_up_starts_existing_stopped_container() -> None:
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.status = "exited"
    mock_client.containers.list.return_value = [mock_container]

    compose_up("qbittorrent", client=mock_client)

    mock_container.reload.assert_called_once()
    mock_container.start.assert_called_once()


def test_compose_up_invokes_docker_compose_cli_when_missing(tmp_path: Path) -> None:
    mock_client = MagicMock()
    mock_client.containers.list.return_value = []
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("services: {}\n")

    with patch("subprocess.run") as mock_run:
        compose_up("qbittorrent", client=mock_client, compose_dir=tmp_path)
        mock_run.assert_called_once_with(
            ["docker", "compose", "up", "-d", "qbittorrent"],
            cwd=tmp_path,
            check=True,
        )


def test_compose_stop_stops_running_container() -> None:
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.status = "running"
    mock_client.containers.list.return_value = [mock_container]

    compose_stop("qbittorrent", client=mock_client)

    mock_container.reload.assert_called_once()
    mock_container.stop.assert_called_once()

