from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import httpx
from homelab_scripts.jellyfin import get_jellyfin_config, refresh
from rich.console import Console

if TYPE_CHECKING:
    import pytest


def test_get_jellyfin_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JELLYFIN_API_KEY", "env_secret_key")
    monkeypatch.setenv("HOSTNAME_BASE", "homelab.example")

    config = get_jellyfin_config()
    assert config == ("https://jellyfin.homelab.example", "env_secret_key")


def test_get_jellyfin_config_from_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JELLYFIN_API_KEY", raising=False)
    monkeypatch.delenv("HOSTNAME_BASE", raising=False)

    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "# Homelab Environment\n\nJELLYFIN_API_KEY=\"file_secret_abc\"\nHOSTNAME_BASE='cluster.lan'\n",
        encoding="utf-8",
    )

    config = get_jellyfin_config(env_file=fake_env)
    assert config == ("https://jellyfin.cluster.lan", "file_secret_abc")


def test_get_jellyfin_config_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JELLYFIN_API_KEY", raising=False)
    monkeypatch.delenv("HOSTNAME_BASE", raising=False)

    non_existent = tmp_path / "does_not_exist.env"
    assert get_jellyfin_config(env_file=non_existent) is None


def test_refresh_missing_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("homelab_scripts.jellyfin.get_jellyfin_config", lambda *args, **kwargs: None)
    dummy_console = Console(quiet=True)
    assert refresh(console=dummy_console, dry_run=False) is False


def test_refresh_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "homelab_scripts.jellyfin.get_jellyfin_config",
        lambda *args, **kwargs: ("https://jellyfin.example.com", "fake_key"),
    )
    mock_post = MagicMock()
    monkeypatch.setattr("httpx.post", mock_post)

    dummy_console = Console(quiet=True)
    success = refresh(console=dummy_console, dry_run=True)

    assert success is True
    mock_post.assert_not_called()


def test_refresh_success_http_204(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "homelab_scripts.jellyfin.get_jellyfin_config",
        lambda *args, **kwargs: ("https://jellyfin.example.com", "key_999"),
    )
    mock_post = MagicMock(return_value=httpx.Response(204))
    monkeypatch.setattr("httpx.post", mock_post)

    dummy_console = Console(quiet=True)
    assert refresh(console=dummy_console, dry_run=False) is True

    mock_post.assert_called_once_with(
        "https://jellyfin.example.com/Library/Refresh",
        headers={"Authorization": 'MediaBrowser Token="key_999"'},
        timeout=10.0,
    )


def test_refresh_failure_http_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "homelab_scripts.jellyfin.get_jellyfin_config",
        lambda *args, **kwargs: ("https://jellyfin.example.com", "key_999"),
    )
    mock_post = MagicMock(return_value=httpx.Response(401))
    monkeypatch.setattr("httpx.post", mock_post)

    dummy_console = Console(quiet=True)
    assert refresh(console=dummy_console, dry_run=False) is False


def test_refresh_network_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "homelab_scripts.jellyfin.get_jellyfin_config",
        lambda *args, **kwargs: ("https://jellyfin.example.com", "key_999"),
    )
    mock_post = MagicMock(side_effect=httpx.ConnectTimeout("Connection timed out"))
    monkeypatch.setattr("httpx.post", mock_post)

    dummy_console = Console(quiet=True)
    assert refresh(console=dummy_console, dry_run=False) is False
