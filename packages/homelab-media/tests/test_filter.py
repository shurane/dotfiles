"""Unit tests for extra/auxiliary filtering and .syncignore handling."""

from __future__ import annotations

from pathlib import Path

import pytest
from homelab_media.filter import check_syncignore, is_extra_or_auxiliary, is_pruned_dir
from homelab_media.models import MediaKind

LARGE_VIDEO = 800 * 1024 * 1024  # 800 MiB
MEDIUM_EPISODE = 250 * 1024 * 1024  # 250 MiB


@pytest.mark.parametrize(
    ("dirname", "expected"),
    [
        ("Featurettes", True),
        ("Extras", True),
        ("Subs", True),
        ("Sample", True),
        ("Screens", True),
        ("Trailers", True),
        ("Bonus", True),
        ("Season 01", False),
        ("Specials", False),
    ],
)
def test_is_pruned_dir(dirname: str, expected: bool) -> None:
    assert is_pruned_dir(dirname) is expected


@pytest.mark.parametrize(
    ("filename", "kind"),
    [
        ("The.Lego.Movie.2014.1080p.mkv", MediaKind.MOVIE),
        ("Supergirl.2026.2160p.WEB-DL.mp4", MediaKind.MOVIE),
        ("Ramy.S01E06.1080p.avi", MediaKind.TV),
        ("Show.S01E01.m4v", MediaKind.TV),
        ("Show.S01E02.webm", MediaKind.TV),
        ("Show.S01E03.ts", MediaKind.TV),
    ],
)
def test_valid_video_extensions_accepted(filename: str, kind: MediaKind) -> None:
    size = LARGE_VIDEO if kind == MediaKind.MOVIE else MEDIUM_EPISODE
    skip, reason = is_extra_or_auxiliary(filename, filename, size, kind)
    assert skip is False, f"Unexpectedly skipped {filename}: {reason}"


@pytest.mark.parametrize(
    "filename",
    [
        "movie.nfo",
        "readme.txt",
        "poster.jpg",
        "fanart.jpeg",
        "thumb.png",
        "video.mkv.parts",
        "download.part",
        "english.srt",
        "file.torrent",
        "checksum.sfv",
        "Dockerfile",
    ],
)
def test_auxiliary_extensions_skipped(filename: str) -> None:
    skip, reason = is_extra_or_auxiliary(filename, filename, LARGE_VIDEO, MediaKind.MOVIE)
    assert skip is True
    assert reason.startswith("NON_VIDEO_EXT:")


@pytest.mark.parametrize(
    "rel_path",
    [
        "Featurettes/Making Of.mkv",
        "Extras/Deleted Scenes.mp4",
        "Subs/English.mkv",
        "Screens/screen1.mkv",
        "Sample/sample.mkv",
        "Trailers/trailer.mp4",
        "Bonus/interview.mkv",
    ],
)
def test_blacklisted_subdirectories_skipped(rel_path: str) -> None:
    filename = Path(rel_path).name
    skip, reason = is_extra_or_auxiliary(rel_path, filename, LARGE_VIDEO, MediaKind.MOVIE)
    assert skip is True
    assert reason.startswith("BLACKLISTED_DIR:")


@pytest.mark.parametrize(
    "filename",
    [
        "Gladiator.II.2024.Sample.mkv",
        "sample-clip.mp4",
        "promo_trailer.mp4",
        "Official.Teaser.mkv",
        "Exclusive.Clip.2025.mp4",
        "Cars.Featurette.mkv",
    ],
)
def test_extra_keywords_skipped(filename: str) -> None:
    skip, reason = is_extra_or_auxiliary(filename, filename, LARGE_VIDEO, MediaKind.MOVIE)
    assert skip is True
    assert reason.startswith("EXTRA_KEYWORD:")


def test_tiny_release_group_movie_promo_skipped() -> None:
    skip, reason = is_extra_or_auxiliary("ETRG.mp4", "ETRG.mp4", 12 * 1024 * 1024, MediaKind.MOVIE)
    assert skip is True
    assert reason == "SMALL_MOVIE_PROMO_OR_SAMPLE"


def test_zero_byte_or_sparse_file_skipped() -> None:
    skip, reason = is_extra_or_auxiliary("S01E01.mkv", "S01E01.mkv", 512 * 1024, MediaKind.TV)
    assert skip is True
    assert reason == "TINY_OR_SPARSE_FILE"


def test_syncignore_empty_ignores_entire_dir(tmp_path: Path) -> None:
    torrent_dir = tmp_path / "Some Show"
    torrent_dir.mkdir()
    (torrent_dir / ".syncignore").write_text("# comment only\n\n", encoding="utf-8")

    ignored, reason = check_syncignore(torrent_dir, Path("S01E01.mkv"))
    assert ignored is True
    assert reason == "SYNCIGNORE_DIR"


def test_syncignore_pattern_matching(tmp_path: Path) -> None:
    torrent_dir = tmp_path / "Some Show"
    torrent_dir.mkdir()
    (torrent_dir / ".syncignore").write_text(
        "# Skip promos and bonus folder\n*.sample.*\nbonus/*\nSpecial.mkv\n",
        encoding="utf-8",
    )

    assert check_syncignore(torrent_dir, Path("ep1.sample.mkv"))[0] is True
    assert check_syncignore(torrent_dir, Path("bonus/clip.mkv"))[0] is True
    assert check_syncignore(torrent_dir, Path("Special.mkv"))[0] is True
    assert check_syncignore(torrent_dir, Path("S01E01.mkv"))[0] is False
