"""Unit tests for homelab_core.network."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from homelab_core.network import (
    classify_route,
    get_ssh_user,
    is_target_local,
    resolve_target_connection,
    run_ssh_command,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_is_target_local() -> None:
    assert is_target_local("localhost") is True
    assert is_target_local("127.0.0.1") is True
    assert is_target_local("::1") is True
    assert is_target_local("remote-nonexistent-node-12345.example.com") is False


def test_get_ssh_user(tmp_path: Path) -> None:
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("")

    assert get_ssh_user("custom_user") == "custom_user"

    with patch.dict("os.environ", {"HOMELAB_SSH_USER": "ssh_override"}):
        assert get_ssh_user(env_path=empty_env) == "ssh_override"

    with patch.dict("os.environ", {"HOMELAB_USERNAME": "homelab_user"}, clear=True):
        assert get_ssh_user(env_path=empty_env) == "homelab_user"

    with patch.dict("os.environ", {}, clear=True):
        assert get_ssh_user(env_path=empty_env) == "homelab"


def test_classify_route() -> None:
    route, desc = classify_route("localhost", "127.0.0.1", is_local=True)
    assert route == "local"
    assert "Local Host" in desc

    route_ts, _ = classify_route("server.ts.net", "100.64.1.2", is_local=False)
    assert route_ts == "tailscale"

    route_ts_v6, _ = classify_route("server", "fd7a:115c:a1e0::1", is_local=False)
    assert route_ts_v6 == "tailscale"

    route_lan, _ = classify_route("m70q.lan", "192.168.1.100", is_local=False)
    assert route_lan == "lan"

    route_wan, _ = classify_route("example.com", "8.8.8.8", is_local=False)
    assert route_wan == "wan"


def test_resolve_target_connection() -> None:
    conn = resolve_target_connection("localhost")
    assert conn.host == "localhost"
    assert conn.is_local is True
    assert conn.route == "local"


def test_resolve_target_connection_ipv6_loopback() -> None:
    conn = resolve_target_connection("::1")
    assert conn.host == "::1"
    assert conn.is_local is True
    assert conn.route == "local"


def test_run_ssh_command() -> None:
    mock_res = MagicMock(returncode=0, stdout="test-output\n")
    with patch("subprocess.run", return_value=mock_res) as mock_run:
        res = run_ssh_command("server.lan", "echo hello", user="myuser", timeout=3.0)
        assert res.returncode == 0
        assert res.stdout == "test-output\n"
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "myuser@server.lan" in args
        assert "echo hello" in args
