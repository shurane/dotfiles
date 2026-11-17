"""Unit tests for Typer CLI subcommands and remote SSH dispatcher."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from homelab_media import cli
from homelab_media.config import MediaConfig
from homelab_media.remote import SSH_BASE_OPTS, dispatch_remote
from typer.testing import CliRunner

runner = CliRunner()


def _setup_dirs(tmp_path: Path) -> MediaConfig:
    torrents = tmp_path / "torrents"
    media = tmp_path / "media"
    (torrents / "tv").mkdir(parents=True)
    (torrents / "movies").mkdir(parents=True)
    (media / "tv").mkdir(parents=True)
    (media / "movies").mkdir(parents=True)
    return MediaConfig(torrents_dir=torrents, media_dir=media)


def test_cli_plan_json_and_sync_resolve_preserves_season_rel_path(tmp_path: Path, monkeypatch) -> None:
    cfg = _setup_dirs(tmp_path)
    show_dir = cfg.torrents_tv_dir / "Mystery.Show"
    ep = show_dir / "Season 02" / "ep03.mkv"
    ep.parent.mkdir(parents=True)
    with ep.open("wb") as f:
        f.truncate(10 * 1024 * 1024)

    monkeypatch.setattr(cli, "load_config", lambda: cfg)

    res_plan = runner.invoke(cli.app, ["plan", "--json", "--offline"])
    assert res_plan.exit_code == 0
    payload = json.loads(res_plan.stdout)
    assert len(payload["flagged_for_review"]) == 1
    rev_id = payload["flagged_for_review"][0]["id"]

    res_sync = runner.invoke(
        cli.app,
        ["sync", "--apply", "--no-refresh", "--offline", "--resolve", f"{rev_id}=opt-1"],
    )
    assert res_sync.exit_code == 0
    expected_target = cfg.media_tv_dir / "Mystery Show" / "Season 02" / "S02E03.mkv"
    assert expected_target.exists()
    assert expected_target.stat().st_ino == ep.stat().st_ino


def test_cli_ignore_creates_syncignore(tmp_path: Path, monkeypatch) -> None:
    cfg = _setup_dirs(tmp_path)
    torrent_dir = cfg.torrents_tv_dir / "Unwanted.Show.2025"
    torrent_dir.mkdir()
    monkeypatch.setattr(cli, "load_config", lambda: cfg)

    res = runner.invoke(cli.app, ["ignore", "Unwanted.Show.2025", "--kind", "tv", "--pattern", "*.sample.*"])
    assert res.exit_code == 0
    assert (torrent_dir / ".syncignore").read_text(encoding="utf-8") == "*.sample.*\n"


def test_remote_dispatch_uses_connect_timeout(monkeypatch) -> None:
    assert "ConnectTimeout=5" in SSH_BASE_OPTS

    calls: list[list[str]] = []

    def fake_run(cmd, **_kw):
        calls.append(cmd)
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "{}"
        mock_res.stderr = ""
        return mock_res

    monkeypatch.setattr("subprocess.run", fake_run)
    cfg = MediaConfig()
    proc = dispatch_remote(cfg, ["plan", "--json"])
    assert proc.returncode == 0
    assert any("ConnectTimeout=5" in cmd for cmd in calls)
