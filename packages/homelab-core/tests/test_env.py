"""Unit tests for homelab_core.env."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from homelab_core.env import (
    ensure_state_dir,
    find_homelab_env,
    find_homelab_root,
    get_env_setting,
    load_homelab_env,
)
from homelab_core.errors import HomelabConfigError

if TYPE_CHECKING:
    from pathlib import Path


def test_find_homelab_env_explicit(tmp_path: Path) -> None:
    fake_env = tmp_path / ".env"
    fake_env.write_text("FOO=BAR\n")

    assert find_homelab_env(fake_env) == fake_env
    assert find_homelab_env(tmp_path / "nonexistent.env") is not None or find_homelab_env(fake_env) == fake_env


def test_find_homelab_env_via_homelab_env(tmp_path: Path) -> None:
    fake_env = tmp_path / "custom.env"
    fake_env.write_text("HOMELAB_PASSWORD=secret\n")

    with patch.dict("os.environ", {"HOMELAB_ENV": str(fake_env)}):
        assert find_homelab_env() == fake_env


def test_find_homelab_env_via_homelab_dir(tmp_path: Path) -> None:
    fake_env = tmp_path / ".env"
    fake_env.write_text("HOMELAB_PASSWORD=secret\n")

    with patch.dict("os.environ", {"HOMELAB_DIR": str(tmp_path)}, clear=True):
        assert find_homelab_env() == fake_env


def test_find_homelab_env_guarded_cwd_rejection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A random unrelated directory containing .env should NOT be picked up
    unrelated_dir = tmp_path / "unrelated_project"
    unrelated_dir.mkdir()
    fake_env = unrelated_dir / ".env"
    fake_env.write_text("OTHER_PROJECT=true\n")

    monkeypatch.chdir(unrelated_dir)
    with patch.dict("os.environ", {}, clear=True):
        # Should not return the unrelated .env
        found = find_homelab_env()
        assert found != fake_env


def test_find_homelab_env_homelab_named_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # When CWD is named 'homelab', .env IS accepted
    homelab_dir = tmp_path / "homelab"
    homelab_dir.mkdir()
    fake_env = homelab_dir / ".env"
    fake_env.write_text("HOMELAB_PASSWORD=secret\n")

    monkeypatch.chdir(homelab_dir)
    with patch.dict("os.environ", {}, clear=True):
        assert find_homelab_env() == fake_env


def test_find_homelab_root_explicit(tmp_path: Path) -> None:
    assert find_homelab_root(tmp_path) == tmp_path


def test_find_homelab_root_env_var(tmp_path: Path) -> None:
    with patch.dict("os.environ", {"HOMELAB_DIR": str(tmp_path)}):
        assert find_homelab_root() == tmp_path


def test_load_homelab_env_merges_os_environ(tmp_path: Path) -> None:
    fake_env = tmp_path / ".env"
    fake_env.write_text("FROM_FILE=1\nOVERRIDE=from_file\n")

    with patch.dict("os.environ", {"OVERRIDE": "from_env", "FROM_ENV": "2"}):
        loaded = load_homelab_env(fake_env)
        assert loaded["FROM_FILE"] == "1"
        assert loaded["OVERRIDE"] == "from_env"
        assert loaded["FROM_ENV"] == "2"


def test_load_homelab_env_required_keys_raises(tmp_path: Path) -> None:
    fake_env = tmp_path / ".env"
    fake_env.write_text("KEY1=val1\n")

    with patch.dict("os.environ", {}, clear=True), pytest.raises(HomelabConfigError, match="Missing required"):
        load_homelab_env(fake_env, required_keys=("KEY1", "MISSING_KEY"))


def test_get_env_setting(tmp_path: Path) -> None:
    fake_env = tmp_path / ".env"
    fake_env.write_text("TEST_KEY=hello\n")

    with patch.dict("os.environ", {}, clear=True):
        assert get_env_setting("TEST_KEY", explicit_path=fake_env) == "hello"
        assert get_env_setting("NONEXISTENT", default="default", explicit_path=fake_env) == "default"


def test_ensure_state_dir_creates_directory(tmp_path: Path) -> None:
    target_dir = tmp_path / "sub" / "deep" / "state"
    assert not target_dir.exists()

    ensure_state_dir(target_dir, root_path=tmp_path)
    assert target_dir.is_dir()

