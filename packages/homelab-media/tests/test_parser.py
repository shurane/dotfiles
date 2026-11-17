"""Unit tests for media filename/title parsing and destination resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
from homelab_media.models import MediaKind, PathTraversalSecurityError
from homelab_media.parser import (
    _format_episode_tag,
    assert_safe_target,
    parse_movie_target,
    parse_torrent_metadata,
    parse_tv_target,
    resolve_parent_folder,
    sanitize_folder_name,
)


def test_movie_standard_title_and_year(tmp_path: Path) -> None:
    res = parse_movie_target(
        "The.Lego.Movie.2014.1080p.BluRay.x264",
        "The.Lego.Movie.2014.1080p.BluRay.x264.mkv",
        existing_movies=set(),
        media_movies_dir=tmp_path,
    )
    assert res.parent.folder_name == "The Lego Movie (2014)"
    assert res.parent.confidence == 1.0
    assert res.target_path == tmp_path / "The Lego Movie (2014)" / "The Lego Movie (2014).mkv"


def test_movie_title_with_year_number_fantasia_2000(tmp_path: Path) -> None:
    res = parse_movie_target(
        "Fantasia.2000.1999.1080p.BluRay.mkv",
        "Fantasia.2000.1999.1080p.BluRay.mkv",
        existing_movies=set(),
        media_movies_dir=tmp_path,
    )
    assert res.parent.folder_name == "Fantasia 2000 (1999)"
    assert res.target_path == tmp_path / "Fantasia 2000 (1999)" / "Fantasia 2000 (1999).mkv"


def test_movie_special_characters_preserved(tmp_path: Path) -> None:
    kiki = parse_movie_target(
        "Kiki's.Delivery.Service.1989.1080p.mkv",
        "Kiki's.Delivery.Service.1989.1080p.mkv",
        existing_movies=set(),
        media_movies_dir=tmp_path,
    )
    assert kiki.parent.folder_name == "Kiki's Delivery Service (1989)"

    ralph = parse_movie_target(
        "Wreck-It.Ralph.2012.1080p.mkv",
        "Wreck-It.Ralph.2012.1080p.mkv",
        existing_movies=set(),
        media_movies_dir=tmp_path,
    )
    assert ralph.parent.folder_name == "Wreck-It Ralph (2012)"

    gladiator = parse_movie_target(
        "Gladiator.II.2024.1080p.mkv",
        "Gladiator.II.2024.1080p.mkv",
        existing_movies=set(),
        media_movies_dir=tmp_path,
    )
    assert gladiator.parent.folder_name == "Gladiator II (2024)"


def test_movie_multi_disc_cd1_cd2(tmp_path: Path) -> None:
    cd1 = parse_movie_target(
        "Some.Epic.2003.DVDRip",
        "Some.Epic.2003.CD1.avi",
        existing_movies=set(),
        media_movies_dir=tmp_path,
    )
    cd2 = parse_movie_target(
        "Some.Epic.2003.DVDRip",
        "Some.Epic.2003.CD2.avi",
        existing_movies=set(),
        media_movies_dir=tmp_path,
    )
    assert cd1.target_path.name == "Some Epic (2003) - cd1.avi"
    assert cd2.target_path.name == "Some Epic (2003) - cd2.avi"
    assert cd1.target_path != cd2.target_path


def test_tv_existing_show_match_and_partial_season(tmp_path: Path) -> None:
    res = parse_tv_target(
        "Ramy.S01.1080p.HULU.WEB-DL",
        "Ramy.S01E06.1080p.mkv",
        "Ramy.S01E06.1080p.mkv",
        existing_shows={"Ramy (2019)", "Talentless Nana (2020)"},
        media_tv_dir=tmp_path,
    )
    assert res is not None
    assert res.parent.folder_name == "Ramy (2019)"
    assert res.parent.reason == "EXACT_EXISTING_MATCH"
    assert res.season == 1
    assert res.episode_label == "S01E06"
    assert res.target_path == tmp_path / "Ramy (2019)" / "Season 01" / "S01E06.mkv"


def test_tv_multi_episode_span(tmp_path: Path) -> None:
    res = parse_tv_target(
        "SpongeBob.SquarePants.1999",
        "SpongeBob.S01E24-E25.1080p.mkv",
        "SpongeBob.S01E24-E25.1080p.mkv",
        existing_shows={"SpongeBob SquarePants (1999)"},
        media_tv_dir=tmp_path,
    )
    assert res is not None
    assert res.episode_label == "S01E24-E25"
    assert res.target_path == tmp_path / "SpongeBob SquarePants (1999)" / "Season 01" / "S01E24-E25.mkv"


def test_tv_multi_season_batch_routing(tmp_path: Path) -> None:
    s6 = parse_tv_target(
        "Daniel.Tigers.Neighborhood.S06-S07.1080p",
        "Season 06/Daniel.Tiger.S06E03.mkv",
        "Daniel.Tiger.S06E03.mkv",
        existing_shows={"Daniel Tiger's Neighborhood (2012)"},
        media_tv_dir=tmp_path,
    )
    s7 = parse_tv_target(
        "Daniel.Tigers.Neighborhood.S06-S07.1080p",
        "Season 07/Daniel.Tiger.S07E01.mkv",
        "Daniel.Tiger.S07E01.mkv",
        existing_shows={"Daniel Tiger's Neighborhood (2012)"},
        media_tv_dir=tmp_path,
    )
    assert s6 is not None and s6.season == 6
    assert s7 is not None and s7.season == 7
    assert s6.target_path.parent.name == "Season 06"
    assert s7.target_path.parent.name == "Season 07"


def test_tv_video_without_episode_tag_returns_none(tmp_path: Path) -> None:
    res = parse_tv_target(
        "Transformers.Rescue.Bots",
        "Random.Promo.Video.mkv",
        "Random.Promo.Video.mkv",
        existing_shows=set(),
        media_tv_dir=tmp_path,
    )
    assert res is None


def test_structural_mismatch_flagged() -> None:
    res = resolve_parent_folder(
        MediaKind.TV,
        "Some Show",
        2020,
        existing_folders={"Some Show"},
    )
    assert res.confidence == 0.70
    assert res.reason == "STRUCTURAL_MISMATCH"
    assert res.existing_mismatch == "Some Show"


def test_missing_year_flagged_for_tmdb() -> None:
    res = resolve_parent_folder(
        MediaKind.TV,
        "Kore Kaite Shine",
        None,
        existing_folders=set(),
    )
    assert res.confidence == 0.70
    assert res.reason == "MISSING_YEAR_QUERY_TMDB"


def test_path_traversal_guard(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    evil = media_root / ".." / "etc" / "passwd"
    with pytest.raises(PathTraversalSecurityError):
        assert_safe_target(evil, media_root)


def test_sanitize_folder_name_handles_slashes_and_colons() -> None:
    assert sanitize_folder_name("Face/Off") == "Face-Off"
    assert sanitize_folder_name("NIPPON SANGOKU: The Three Nations") == "NIPPON SANGOKU - The Three Nations"
    assert sanitize_folder_name('Bad*Name?"<>|') == "BadName"


def test_fast_path_skips_guessit_for_foldered_movie_and_anime_episode(tmp_path: Path, monkeypatch) -> None:
    torrent_name_m = "The Lego Movie (2014) [2160p]"
    meta_m = parse_torrent_metadata(torrent_name_m, MediaKind.MOVIE)

    torrent_name_tv = "[SubsPlease] Kore Kaite Shine (01-12) (1080p) [Batch]"
    meta_tv = parse_torrent_metadata(torrent_name_tv, MediaKind.TV)

    monkeypatch.setattr(
        "homelab_media.parser._guess_metadata",
        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("unexpected guessit call")),
    )

    res_m = parse_movie_target(
        torrent_name_m,
        "The.Lego.Movie.2014.2160p.mkv",
        existing_movies=set(),
        media_movies_dir=tmp_path,
        torrent_meta=meta_m,
    )
    assert res_m.target_path == tmp_path / "The Lego Movie (2014)" / "The Lego Movie (2014).mkv"

    res_tv = parse_tv_target(
        torrent_name_tv,
        "[SubsPlease] Kore Kaite Shine - 05 (1080p) [ABCD].mkv",
        "[SubsPlease] Kore Kaite Shine - 05 (1080p) [ABCD].mkv",
        existing_shows=set(),
        media_tv_dir=tmp_path,
        torrent_meta=meta_tv,
    )
    assert res_tv is not None
    assert res_tv.target_path == tmp_path / "Kore Kaite Shine" / "Season 01" / "S01E05.mkv"


@pytest.mark.parametrize(
    ("season", "ep_start", "ep_end", "expected_tag", "expected_val"),
    [
        (1, 5, None, "S01E05", 5),
        (2, 3, 3, "S02E03", 3),
        (1, 24, 25, "S01E24-E25", "24-25"),
        (3, 10, 8, "S03E08-E10", "8-10"),
        (1, 105, None, "S01E105", 105),
        (1, 99, 101, "S01E99-E101", "99-101"),
    ],
)
def test_format_episode_tag_edge_cases(
    season: int,
    ep_start: int,
    ep_end: int | None,
    expected_tag: str,
    expected_val: int | str,
) -> None:
    assert _format_episode_tag(season, ep_start, ep_end) == (expected_tag, expected_val)
