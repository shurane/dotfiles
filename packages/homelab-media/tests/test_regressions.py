"""Regression tests for reason labels and multi-disc TMDB target construction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from homelab_media.clients.tmdb import TmdbMatch
from homelab_media.config import MediaConfig
from homelab_media.scanner import scan_media_gaps
from homelab_media.ui import reason_label


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


def _cfg(tmp_path: Path) -> MediaConfig:
    for d in ("torrents/tv", "torrents/movies", "media/tv", "media/movies"):
        (tmp_path / d).mkdir(parents=True)
    return MediaConfig(torrents_dir=tmp_path / "torrents", media_dir=tmp_path / "media")


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
