"""Regression tests for reason labels and multi-disc TMDB target construction."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from conftest import make_test_config as _cfg
from homelab_media.clients.tmdb import TmdbMatch
from homelab_media.executor import execute_sync
from homelab_media.models import ActionType, MediaKind, PathTraversalSecurityError, SyncAction
from homelab_media.parser import assert_safe_target, build_folder_index, resolve_parent_folder
from homelab_media.renderer import reason_label
from homelab_media.scanner import scan_media_gaps


@pytest.mark.parametrize(
    ("reason", "label"),
    [
        ("EXACT_EXISTING_MATCH", "existing"),
        ("PARSED_TITLE_YEAR", "parsed"),
        ("TMDB_MATCH", "tmdb"),
        ("EXTRA_KEYWORD:sample", "sample"),
        ("BLACKLISTED_DIR:Extras", "pruned dir"),
        ("NON_VIDEO_EXT:.nfo", "non-video"),
        ("SMALL_MOVIE_PROMO_OR_SAMPLE", "small promo"),
        ("TINY_OR_SPARSE_FILE", "<1 MiB"),
        ("NO_EPISODE_TAG", "no episode"),
        ("SYNCIGNORE_DIR", ".syncignore"),
        ("SYNCIGNORE_PATTERN:*.nfo", ".syncignore (*.nfo)"),
        ("SOMETHING_NEW", "something_new"),
        ("", ""),
    ],
)
def test_reason_label_snapshot(reason: str, label: str) -> None:
    assert reason_label(reason) == label


def test_tmdb_multidisc_movie_keeps_disc_suffix(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    torrent = cfg.torrents_movies_dir / "Some.Long.Movie.1080p"
    for name in ("Some.Long.Movie.CD1.mkv", "Some.Long.Movie.CD2.mkv"):
        torrent.mkdir(parents=True, exist_ok=True)
        with (torrent / name).open("wb") as f:
            f.truncate(100 * 1024 * 1024)

    tmdb = MagicMock()
    tmdb.is_configured = True
    tmdb.resolve.return_value = (
        TmdbMatch(tmdb_id=1, title="Some Long Movie", original_title="Some Long Movie", year=2001),
        [],
    )
    report = scan_media_gaps(cfg, tmdb_client=tmdb, use_qbittorrent=False)

    targets = sorted(a.target_file.name for a in report.ready_to_sync if a.target_file)
    assert targets == [
        "Some Long Movie (2001) - cd1.mkv",
        "Some Long Movie (2001) - cd2.mkv",
    ]
    assert report.conflicts == []


@pytest.mark.parametrize(
    ("title", "year", "expected_folder", "expected_reason"),
    [
        ("Dune", 2021, "Dune (2021)", "EXACT_EXISTING_MATCH"),
        ("Dune", 1984, "Dune (1984)", "STRUCTURAL_MISMATCH"),
        ("Dune", None, "Dune (2021)", "EXACT_EXISTING_MATCH"),
        ("Unyear Show", None, "Unyear Show", "EXACT_EXISTING_MATCH"),
        ("UnYear Show", 2019, "UnYear Show (2019)", "STRUCTURAL_MISMATCH"),
        ("Brand New", 2024, "Brand New (2024)", "PARSED_TITLE_YEAR"),
        ("Brand New", None, "Brand New", "MISSING_YEAR_QUERY_TMDB"),
    ],
)
def test_folder_index_matches_set_resolution(
    title: str,
    year: int | None,
    expected_folder: str,
    expected_reason: str,
) -> None:
    folders = {"Dune (2021)", "Unyear Show", "Another (1999)"}
    idx = build_folder_index(folders)

    from_set = resolve_parent_folder(MediaKind.TV, title, year, folders)
    from_idx = resolve_parent_folder(MediaKind.TV, title, year, idx)

    assert from_idx == from_set
    assert from_idx.folder_name == expected_folder
    assert from_idx.reason == expected_reason


def test_lexical_assert_safe_target_zero_lstat_and_rejects_escapes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "media" / "movies"
    lstats: list[str] = []
    real_lstat = os.lstat

    def counting_lstat(path: str | os.PathLike[str], *a: object, **k: object) -> os.stat_result:
        lstats.append(os.fspath(path))
        return real_lstat(path, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "lstat", counting_lstat)

    ok = assert_safe_target(root / "Dune (2021)" / "Dune (2021).mkv", root)
    assert ok == root / "Dune (2021)" / "Dune (2021).mkv"
    assert lstats == []

    for bad in (
        root,
        root / ".." / "tv" / "Show" / "ep.mkv",
        Path("/etc/passwd"),
        root / "Show\x00Evil" / "ep.mkv",
    ):
        with pytest.raises(PathTraversalSecurityError):
            assert_safe_target(bad, root)


def test_executor_blocks_symlink_escape_via_follow_symlinks(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    src = cfg.torrents_movies_dir / "Movie.2020.mkv"
    with src.open("wb") as f:
        f.truncate(1024)

    outside = tmp_path / "outside"
    outside.mkdir()
    escape_dir = cfg.media_movies_dir / "Movie (2020)"
    escape_dir.symlink_to(outside, target_is_directory=True)

    action = SyncAction(
        torrent_name="Movie.2020.mkv",
        source_file=src,
        target_file=escape_dir / "Movie (2020).mkv",
        kind=MediaKind.MOVIE,
        action_type=ActionType.SYNC,
        reason="PARSED_TITLE_YEAR",
    )
    summary = execute_sync([action], cfg, dry_run=False)
    assert summary.linked_count == 0
    assert len(summary.errors) == 1
    assert "escapes media root" in summary.errors[0]


def test_tmdb_preserves_season_zero_for_specials(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    show = cfg.torrents_tv_dir / "Darker.Than.Black.S01+S02+OVAs"
    ova = show / "Specials" / "Darker Than Black - S00E01 - OVA 1.mkv"
    ova.parent.mkdir(parents=True)
    with ova.open("wb") as f:
        f.truncate(100 * 1024 * 1024)

    tmdb = MagicMock()
    tmdb.is_configured = True
    tmdb.resolve.return_value = (
        TmdbMatch(tmdb_id=1, title="Darker than Black", original_title="Darker than Black", year=2007),
        [],
    )
    report = scan_media_gaps(cfg, tmdb_client=tmdb, use_qbittorrent=False)

    assert len(report.ready_to_sync) == 1
    assert report.ready_to_sync[0].target_file == (
        cfg.media_tv_dir / "Darker than Black (2007)" / "Season 00" / "S00E01.mkv"
    )
