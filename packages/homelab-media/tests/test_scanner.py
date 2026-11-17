"""Unit and integration tests for POSIX media scanner and hardlink executor."""

from __future__ import annotations

import os
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

from homelab_media.clients.tmdb import TmdbMatch
from homelab_media.config import MediaConfig
from homelab_media.executor import execute_sync
from homelab_media.models import ActionType, TorrentItem
from homelab_media.renderer import render_gap_report
from homelab_media.scanner import scan_media_gaps
from rich.console import Console


def _make_dummy_video(path: Path, size: int = 100 * 1024 * 1024) -> None:
    """Create a sparse regular file of the given size for testing without disk bloat."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.truncate(size)


def _make_config(tmp_path: Path) -> MediaConfig:
    torrents = tmp_path / "torrents"
    media = tmp_path / "media"
    (torrents / "tv").mkdir(parents=True)
    (torrents / "movies").mkdir(parents=True)
    (media / "tv").mkdir(parents=True)
    (media / "movies").mkdir(parents=True)
    return MediaConfig(torrents_dir=torrents, media_dir=media)


def test_inode_alias_discovery_marks_already_synced(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    src = cfg.torrents_tv_dir / "Anpanman (1988)" / "Anpanman.S01E01.mkv"
    dst = cfg.media_tv_dir / "Soreike! Anpanman (1988)" / "Season 01" / "S01E01.mkv"
    _make_dummy_video(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.link(src, dst)

    report = scan_media_gaps(cfg, use_qbittorrent=False)
    assert report.already_synced_count == 1
    assert report.ready_to_sync == []


def test_partial_season_fill_detects_missing_episode(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    show_dir = cfg.torrents_tv_dir / "Ramy.S01.1080p"
    ep5 = show_dir / "Ramy.S01E05.mkv"
    ep6 = show_dir / "Ramy.S01E06.mkv"
    _make_dummy_video(ep5)
    _make_dummy_video(ep6)

    media_season = cfg.media_tv_dir / "Ramy (2019)" / "Season 01"
    media_season.mkdir(parents=True)
    os.link(ep5, media_season / "S01E05.mkv")

    report = scan_media_gaps(cfg, use_qbittorrent=False)
    assert report.already_synced_count == 1
    assert len(report.ready_to_sync) == 1
    action = report.ready_to_sync[0]
    assert action.source_file == ep6
    assert action.target_file == media_season / "S01E06.mkv"
    assert action.episode == 6


def test_in_progress_torrents_protected(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    _make_dummy_video(cfg.torrents_tv_dir / "Journal.with.Witch.2026" / "Ep01.mkv")
    _make_dummy_video(cfg.torrents_movies_dir / "The.Lego.Movie.2014.mkv")

    mock_qb = MagicMock()
    mock_qb.fetch_torrents.return_value = (
        True,
        [
            TorrentItem(
                hash="aaa",
                name="Journal.with.Witch.2026",
                progress=0.45,
                state="downloading",
            ),
            TorrentItem(
                hash="bbb",
                name="The.Lego.Movie.2014.mkv",
                progress=1.0,
                state="stalledUP",
            ),
        ],
    )

    report = scan_media_gaps(cfg, qb_client=mock_qb, use_qbittorrent=True)
    assert report.qbittorrent_online is True
    assert len(report.in_progress) == 1
    assert report.in_progress[0].name == "Journal.with.Witch.2026"
    assert len(report.ready_to_sync) == 1
    assert report.ready_to_sync[0].torrent_name == "The.Lego.Movie.2014.mkv"


def test_offline_qbittorrent_fallback_and_untracked_items(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    _make_dummy_video(cfg.torrents_movies_dir / "Ponyo.2008.1080p.mkv")

    mock_qb = MagicMock()
    mock_qb.fetch_torrents.return_value = (False, [])

    report = scan_media_gaps(cfg, qb_client=mock_qb, use_qbittorrent=True)
    assert report.qbittorrent_online is False
    assert len(report.ready_to_sync) == 1
    assert report.ready_to_sync[0].tracked_by_qbittorrent is False


def test_conflict_detection_never_overwrites(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    src = cfg.torrents_movies_dir / "Supergirl.2026.1080p.mkv"
    dst = cfg.media_movies_dir / "Supergirl (2026)" / "Supergirl (2026).mkv"
    _make_dummy_video(src)
    _make_dummy_video(dst)

    report = scan_media_gaps(cfg, use_qbittorrent=False)
    assert report.ready_to_sync == []
    assert len(report.conflicts) == 1
    assert report.conflicts[0].action_type == ActionType.CONFLICT
    assert report.conflicts[0].reason == "TARGET_EXISTS_DIFFERENT_INODE"

    forced = report.conflicts[0].model_copy(update={"action_type": ActionType.SYNC})
    summary = execute_sync([forced], cfg)
    assert summary.linked_count == 0
    assert len(summary.errors) == 1
    assert "Conflict" in summary.errors[0]


def test_symlink_refusal(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    real_file = tmp_path / "outside.mkv"
    _make_dummy_video(real_file)
    symlink_path = cfg.torrents_movies_dir / "Fake.Movie.2024.mkv"
    symlink_path.symlink_to(real_file)

    report = scan_media_gaps(cfg, use_qbittorrent=False)
    assert report.ready_to_sync == []


def test_execute_sync_and_idempotency(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    src = cfg.torrents_movies_dir / "The.Lego.Batman.Movie.2017.1080p.mkv"
    _make_dummy_video(src)

    report1 = scan_media_gaps(cfg, use_qbittorrent=False)
    assert len(report1.ready_to_sync) == 1

    dry_summary = execute_sync(report1.ready_to_sync, cfg, dry_run=True)
    assert dry_summary.linked_count == 1
    assert not (cfg.media_movies_dir / "The Lego Batman Movie (2017)").exists()

    real_summary = execute_sync(report1.ready_to_sync, cfg, dry_run=False)
    assert real_summary.linked_count == 1
    assert real_summary.errors == []
    target = cfg.media_movies_dir / "The Lego Batman Movie (2017)" / "The Lego Batman Movie (2017).mkv"
    assert target.exists()
    assert target.stat().st_ino == src.stat().st_ino

    report2 = scan_media_gaps(cfg, use_qbittorrent=False)
    assert report2.ready_to_sync == []
    assert report2.already_synced_count == 1


def test_tmdb_resolves_missing_year_show(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    src = cfg.torrents_tv_dir / "[SubsPlease] Kore Kaite Shine (01-12)" / "[SubsPlease] Kore Kaite Shine - 01.mkv"
    _make_dummy_video(src)

    mock_tmdb = MagicMock()
    mock_tmdb.is_configured = True
    mock_tmdb.resolve.return_value = (
        TmdbMatch(tmdb_id=99999, title="Kore Kaite Shine", original_title="これ描いて死ね", year=2026),
        [],
    )

    report = scan_media_gaps(cfg, tmdb_client=mock_tmdb, use_qbittorrent=False)
    assert report.flagged_for_review == []
    assert len(report.ready_to_sync) == 1
    assert report.ready_to_sync[0].reason == "TMDB_MATCH"
    assert (
        report.ready_to_sync[0].target_file
        == cfg.media_tv_dir / "Kore Kaite Shine (2026)" / "Season 01" / "S01E01.mkv"
    )


def test_tmdb_ambiguous_populates_review_candidates(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    src = cfg.torrents_movies_dir / "Dune.1080p.mkv"
    _make_dummy_video(src)

    mock_tmdb = MagicMock()
    mock_tmdb.is_configured = True
    mock_tmdb.resolve.return_value = (
        None,
        [
            TmdbMatch(tmdb_id=438631, title="Dune", original_title="Dune", year=2021),
            TmdbMatch(tmdb_id=841, title="Dune", original_title="Dune", year=1984),
        ],
    )

    report = scan_media_gaps(cfg, tmdb_client=mock_tmdb, use_qbittorrent=False)
    assert report.ready_to_sync == []
    assert len(report.flagged_for_review) == 1
    rev = report.flagged_for_review[0]
    assert len(rev.candidates) == 2
    assert "Dune (2021)" in rev.candidates[0].description
    assert "Dune (1984)" in rev.candidates[1].description


def test_pruned_extra_dirs_reported_in_skipped_extras(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    movie_dir = cfg.torrents_movies_dir / "Cars (2006)"
    _make_dummy_video(movie_dir / "Cars (2006).mkv")
    _make_dummy_video(movie_dir / "Featurettes" / "Deleted Scenes.mkv")

    report = scan_media_gaps(cfg, use_qbittorrent=False)
    assert len(report.ready_to_sync) == 1
    assert any(s.reason == "BLACKLISTED_DIR:Featurettes" for s in report.skipped_extras)


def test_end_to_end_realistic_library_sync_and_render(tmp_path: Path) -> None:
    """Anonymized end-to-end test covering reasons, conflicts, in-progress, and --verbose output."""
    cfg = _make_config(tmp_path)

    # 1. Existing synced movie + movie with pruned Featurettes and Sample
    existing_movie = cfg.torrents_movies_dir / "Movie.Existing.2012.1080p"
    _make_dummy_video(existing_movie / "Movie.Existing.2012.1080p.mkv")
    _make_dummy_video(existing_movie / "Movie.Existing.2012.Sample.mkv")
    _make_dummy_video(existing_movie / "Featurettes" / "MakingOf.mkv")
    (existing_movie / "readme.txt").write_text("info", encoding="utf-8")
    (cfg.media_movies_dir / "Movie Existing (2012)").mkdir(parents=True)
    os.link(
        existing_movie / "Movie.Existing.2012.1080p.mkv",
        cfg.media_movies_dir / "Movie Existing (2012)" / "Movie Existing (2012).mkv",
    )

    # 2. Unsynced movies (parsed) + 1 movie conflict (existing different inode)
    _make_dummy_video(cfg.torrents_movies_dir / "Movie One (2014) [2160p]" / "Movie.One.2014.mkv")
    _make_dummy_video(cfg.torrents_movies_dir / "Movie Two (2026) [1080p]" / "Movie.Two.2026.mp4")
    _make_dummy_video(cfg.torrents_movies_dir / "Movie.Conflict.2025.1080p.mkv")
    _make_dummy_video(cfg.media_movies_dir / "Movie Conflict (2025)" / "Movie Conflict (2025).mkv")

    # 3. Partial TV season missing 1 episode (existing)
    show_alpha = cfg.torrents_tv_dir / "Show.Alpha.2019.S01.1080p"
    alpha_media = cfg.media_tv_dir / "Show Alpha (2019)" / "Season 01"
    alpha_media.mkdir(parents=True)
    for ep in range(1, 6):
        src = show_alpha / f"Show.Alpha.S01E{ep:02d}.mkv"
        _make_dummy_video(src)
        os.link(src, alpha_media / f"S01E{ep:02d}.mkv")
    _make_dummy_video(show_alpha / "Show.Alpha.S01E06.mkv")

    # 4. Full season TV show with year in torrent name (parsed)
    show_beta = cfg.torrents_tv_dir / "Show.Beta.2026.S01.1080p"
    for ep in range(1, 5):
        _make_dummy_video(show_beta / f"Show.Beta.S01E{ep:02d}.mkv")

    # 5. Missing-year anime resolved via TMDB (including colon sanitization)
    show_gamma = cfg.torrents_tv_dir / "[Group] Show Gamma (01-03) [Batch]"
    for ep in range(1, 4):
        _make_dummy_video(show_gamma / f"[Group] Show Gamma - {ep:02d} (1080p).mkv")

    show_delta = cfg.torrents_tv_dir / "Show Delta"
    for ep in range(1, 3):
        _make_dummy_video(show_delta / f"Show.Delta.S01E{ep:02d}.mkv")

    # 6. In-progress torrent (must be protected)
    _make_dummy_video(cfg.torrents_tv_dir / "Show.Active.2026" / "Show.Active.S01E01.mkv")

    mock_qb = MagicMock()
    mock_qb.fetch_torrents.return_value = (
        True,
        [
            TorrentItem(hash="1", name="Show.Active.2026", progress=0.62, state="downloading"),
            TorrentItem(hash="2", name="Show.Alpha.2019.S01.1080p", progress=1.0, state="stalledUP"),
        ],
    )

    mock_tmdb = MagicMock()
    mock_tmdb.is_configured = True
    mock_tmdb.resolve.side_effect = lambda _kind, q: (
        (TmdbMatch(tmdb_id=101, title="Show Gamma", original_title="Show Gamma", year=2026), [])
        if "Gamma" in q
        else (
            TmdbMatch(tmdb_id=102, title="Show Delta: Subtitle", original_title="Show Delta", year=2026),
            [],
        )
    )

    report1 = scan_media_gaps(cfg, qb_client=mock_qb, tmdb_client=mock_tmdb, use_qbittorrent=True)
    assert report1.already_synced_count == 6  # 1 movie + 5 Show Alpha episodes
    assert len(report1.in_progress) == 1
    assert report1.flagged_for_review == []
    assert len(report1.conflicts) == 1
    assert report1.conflicts[0].reason == "TARGET_EXISTS_DIFFERENT_INODE"
    assert len(report1.ready_to_sync) == 12  # 2 movies + 1 Alpha + 4 Beta + 3 Gamma + 2 Delta
    assert len(report1.skipped_extras) == 3  # Sample.mkv, Featurettes/, readme.txt

    reasons_by_torrent = {a.torrent_name: a.reason for a in report1.ready_to_sync}
    assert reasons_by_torrent["Movie One (2014) [2160p]"] == "PARSED_TITLE_YEAR"
    assert reasons_by_torrent["Show.Alpha.2019.S01.1080p"] == "EXACT_EXISTING_MATCH"
    assert reasons_by_torrent["Show Delta"] == "TMDB_MATCH"

    buf = StringIO()
    render_gap_report(
        report1,
        console=Console(file=buf, force_terminal=True, color_system="truecolor", width=180),
        verbose=True,
    )
    rendered = buf.getvalue()
    print(rendered)
    assert "movies/Movie One (2014)" in rendered
    assert "parsed" in rendered
    assert "tv/Show Alpha (2019)" in rendered
    assert "existing" in rendered
    assert "S01E06" in rendered
    assert "tv/Show Beta (2026)" in rendered
    assert "S01E01-E04" in rendered
    assert "tv/Show Delta - Subtitle (2026)" in rendered
    assert "tmdb" in rendered
    assert "Conflicts" in rendered
    assert "TARGET_EXISTS_DIFFERENT_INODE" in rendered
    assert "Skipped Extras & Auxiliary Files" in rendered
    assert "Featurettes/" in rendered
    assert "pruned dir" in rendered
    assert "Movie.Existing.2012.Sample.mkv" in rendered
    assert "sample" in rendered
    assert "readme.txt" in rendered
    assert "non-video" in rendered

    summary = execute_sync(report1.ready_to_sync, cfg, dry_run=False)
    assert summary.linked_count == 12
    assert summary.errors == []
    assert (alpha_media / "S01E06.mkv").stat().st_ino == (show_alpha / "Show.Alpha.S01E06.mkv").stat().st_ino

    report2 = scan_media_gaps(cfg, qb_client=mock_qb, tmdb_client=mock_tmdb, use_qbittorrent=True)
    assert report2.ready_to_sync == []
    assert report2.already_synced_count == 18
    assert len(report2.conflicts) == 1
