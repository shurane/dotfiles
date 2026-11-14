import pytest

from download_anpanman import parse_range_spec as parse_anpanman_range
from download_numberblocks import SEASON_PLAYLISTS, parse_seasons
from sync_maruko import parse_range_spec as parse_maruko_range


def test_sync_maruko_parse_range_single_and_list() -> None:
    assert parse_maruko_range("12") == {12}
    assert parse_maruko_range("1, 3, 5") == {1, 3, 5}


def test_sync_maruko_parse_range_hyphenated_and_compound() -> None:
    assert parse_maruko_range("1-10") == set(range(1, 11))
    assert parse_maruko_range("1-5, 8, 12-14") == {1, 2, 3, 4, 5, 8, 12, 13, 14}
    assert parse_maruko_range("  1 - 3 ,  7  ") == {1, 2, 3, 7}


def test_sync_maruko_parse_range_invalid() -> None:
    with pytest.raises(ValueError, match=r"invalid literal for int"):
        parse_maruko_range("abc")
    with pytest.raises(ValueError, match=r"invalid literal for int"):
        parse_maruko_range("1-foo")


def test_download_anpanman_parse_range_standard() -> None:
    assert parse_anpanman_range("1-5") == {1, 2, 3, 4, 5}
    assert parse_anpanman_range("10, 20, 30") == {10, 20, 30}


def test_download_anpanman_parse_range_all_wildcard() -> None:
    expected = set(range(1, 601))
    assert parse_anpanman_range("all") == expected
    assert parse_anpanman_range("ALL") == expected
    assert parse_anpanman_range("All") == expected
    assert parse_anpanman_range("*") == expected


def test_download_anpanman_parse_range_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid range specification"):
        parse_anpanman_range("xyz")
    with pytest.raises(ValueError, match=r"invalid literal for int"):
        parse_anpanman_range("1-bar")


def test_download_numberblocks_parse_seasons_basic() -> None:
    assert parse_seasons("3") == [3]
    assert parse_seasons("1, 4, 6") == [1, 4, 6]
    assert parse_seasons("2-5") == [2, 3, 4, 5]


def test_download_numberblocks_parse_seasons_all_wildcard() -> None:
    all_seasons = sorted(SEASON_PLAYLISTS.keys())
    assert parse_seasons("all") == all_seasons
    assert parse_seasons("ALL") == all_seasons
    assert parse_seasons("*") == all_seasons


def test_download_numberblocks_parse_seasons_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid season specification"):
        parse_seasons("foo")
    with pytest.raises(ValueError, match=r"invalid literal for int"):
        parse_seasons("1-bar")
