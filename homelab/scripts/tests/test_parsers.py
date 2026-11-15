import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from download_anpanman import parse_range_spec as parse_anpanman_range
from download_numberblocks import SEASON_PLAYLISTS, parse_seasons
from sync_maruko import (
    clean_ass_text,
    extract_english_title_from_mkv,
    extract_english_title_via_ffmpeg,
    extract_english_title_via_py_extractor,
)
from sync_maruko import (
    parse_range_spec as parse_maruko_range,
)


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
    with pytest.raises(ValueError, match="Invalid inverted range"):
        parse_maruko_range("10-5")


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
    with pytest.raises(ValueError, match="Invalid inverted range"):
        parse_anpanman_range("20-1")


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
    with pytest.raises(ValueError, match="Invalid inverted season range"):
        parse_seasons("5-2")


def test_clean_ass_text() -> None:
    assert clean_ass_text(r"{\pos(640,400)}Maruko Goes to the Market") == "Maruko Goes to the Market"
    assert clean_ass_text(r"{\an5\c&H00FFFF&}Part 1\NPart 2") == "Part 1 Part 2"
    assert clean_ass_text(r"Part 1\h\hPart 2") == "Part 1 Part 2"
    assert clean_ass_text(r"Part 1\nPart 2") == "Part 1 Part 2"
    assert clean_ass_text("Simple Title") == "Simple Title"
    assert clean_ass_text(r"{\b1}Title{\b0} With {\i1}Styles{\i0}") == "Title With Styles"
    assert clean_ass_text(r"Literal\Path\ToFile") == r"Literal\Path\ToFile"
    assert clean_ass_text("  Multiple   spaces   everywhere  ") == "Multiple spaces everywhere"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg CLI required to generate test MKV")
def test_mkv_extractors_reconciliation(tmp_path: Path) -> None:
    ass_path = tmp_path / "test.ass"
    ass_content = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: EpTitle,Arial,48,&H00FFFF00,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,3,2,10,10,40,1\n"
        "Style: Default,Arial,36,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,20,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        r"Dialogue: 0,0:00:00.10,0:00:00.40,EpTitle,,0,0,0,,{\pos(640,400)}Maruko Goes Shopping\NAnd Finds a Cat"
        "\n"
        r"Dialogue: 0,0:00:00.45,0:00:00.70,Default,,0,0,0,,Good morning everyone!"
        "\n"
        r"Dialogue: 0,0:00:00.75,0:00:00.95,EpTitle,,0,0,0,,Sister Learns to Cook\h\hQuickly"
        "\n"
    )
    ass_path.write_text(ass_content, encoding="utf-8")

    mkv_path = tmp_path / "test.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=320x240:rate=5",
            "-i",
            str(ass_path),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:s",
            "ass",
            str(mkv_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    expected = "Maruko Goes Shopping And Finds a Cat & Sister Learns to Cook Quickly"

    # 1. Verify both extractors return identical results independently
    py_result = extract_english_title_via_py_extractor(mkv_path)
    ff_result = extract_english_title_via_ffmpeg(mkv_path)

    assert py_result == expected
    assert ff_result == expected
    assert py_result == ff_result

    # 2. Verify master extractor in normal mode defaults to py-extractor
    assert extract_english_title_from_mkv(mkv_path, reconcile=False) == expected

    # 3. Verify master extractor in reconciliation mode runs both and matches
    assert extract_english_title_from_mkv(mkv_path, reconcile=True) == expected

    # 4. Verify reconciliation prefers ffmpeg on discrepancy
    with patch("sync_maruko.extract_english_title_via_py_extractor", return_value="Divergent Title"):
        reconciled = extract_english_title_from_mkv(mkv_path, reconcile=True)
        assert reconciled == expected
