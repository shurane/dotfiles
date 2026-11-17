"""Unit tests for Typer CLI subcommands and remote SSH dispatcher."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

from homelab_media import cli
from homelab_media.config import MediaConfig
from homelab_media.models import ActionType, GapReport, MediaKind, SyncAction
from homelab_media.remote import SSH_BASE_OPTS, dispatch_remote
from homelab_media.renderer import _format_episode_ranges, render_gap_report
from rich.console import Console
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


def test_format_episode_ranges_compacts_contiguous_and_gaps() -> None:
    actions = [
        SyncAction(
            torrent_name="Show",
            source_file=Path(f"ep{ep}.mkv"),
            kind=MediaKind.TV,
            action_type=ActionType.SYNC,
            reason="PARSED_TITLE_YEAR",
            season=1,
            episode=ep,
        )
        for ep in (1, 2, 3, 5, 6, 8)
    ]
    assert _format_episode_ranges(actions) == "S01E01-E03,E05-E06,E08"


def test_render_gap_report_emits_osc8_torrent_link(tmp_path: Path) -> None:
    src = tmp_path / "torrents" / "movies" / "Supergirl (2026)" / "Supergirl.mp4"
    tgt = tmp_path / "media" / "movies" / "Supergirl (2026)" / "Supergirl (2026).mp4"
    report = GapReport(
        ready_to_sync=[
            SyncAction(
                torrent_name="Supergirl (2026)",
                source_file=src,
                target_file=tgt,
                kind=MediaKind.MOVIE,
                action_type=ActionType.SYNC,
                reason="PARSED_TITLE_YEAR",
                file_size=2 * 1024 * 1024 * 1024,
            )
        ]
    )
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, color_system="truecolor", width=160)
    render_gap_report(report, console=console)
    output = buf.getvalue()
    assert "\x1b]8;" in output
    assert "file://" in output
    assert "torrent" in output


def test_render_gap_report_verbose_compacts_skipped_extras(tmp_path: Path) -> None:
    report = GapReport(
        skipped_extras=[
            SyncAction(
                torrent_name="Wreck-It.Ralph.2012",
                source_file=tmp_path / "Wreck-It.Ralph.2012" / "ETRG.mp4",
                kind=MediaKind.MOVIE,
                action_type=ActionType.SKIP_EXTRA,
                reason="SMALL_MOVIE_PROMO_OR_SAMPLE",
            ),
            SyncAction(
                torrent_name="Wreck-It.Ralph.2012",
                source_file=tmp_path / "Wreck-It.Ralph.2012" / "readme.txt",
                kind=MediaKind.MOVIE,
                action_type=ActionType.SKIP_EXTRA,
                reason="NON_VIDEO_EXT:.txt",
            ),
            SyncAction(
                torrent_name="Wreck-It.Ralph.2012",
                source_file=tmp_path / "Wreck-It.Ralph.2012" / "poster.png",
                kind=MediaKind.MOVIE,
                action_type=ActionType.SKIP_EXTRA,
                reason="NON_VIDEO_EXT:.png",
            ),
        ]
    )
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, color_system="truecolor", width=160)
    render_gap_report(report, console=console, verbose=True)
    output = buf.getvalue()
    assert "Wreck-It.Ralph.2012" in output
    assert "ETRG.mp4 (promo)" in output
    assert "2x (.png, .txt)" in output
