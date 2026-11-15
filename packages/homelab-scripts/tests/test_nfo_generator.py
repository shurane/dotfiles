import xml.etree.ElementTree as ET
from pathlib import Path

from homelab_scripts.download_anpanman import EpisodeFile, ensure_media_link_and_nfo, format_media_filename
from homelab_scripts.sync_maruko import generate_nfo_content


def test_sync_maruko_generate_nfo_content_basic() -> None:
    xml_str = generate_nfo_content(
        title="Okaasan no Hi",
        original_title="お母さんの日",
        season=1,
        episode=18,
    )

    root = ET.fromstring(xml_str)
    assert root.tag == "episodedetails"
    assert root.findtext("title") == "Okaasan no Hi"
    assert root.findtext("originaltitle") == "お母さんの日"
    assert root.findtext("season") == "1"
    assert root.findtext("episode") == "18"
    assert root.find("aired") is None
    assert root.find("plot") is None


def test_sync_maruko_generate_nfo_content_optional_fields_and_escaping() -> None:
    xml_str = generate_nfo_content(
        title='Tom & Jerry in "Cat & Mouse" <Adventures>',
        original_title="トム & ジェリー",
        season=2,
        episode=5,
        air_date="1990-05-13",
        plot="A tale of 'friendship' & rivalry.",
    )

    root = ET.fromstring(xml_str)
    assert root.findtext("title") == 'Tom & Jerry in "Cat & Mouse" <Adventures>'
    assert root.findtext("originaltitle") == "トム & ジェリー"
    assert root.findtext("aired") == "1990-05-13"
    assert root.findtext("plot") == "A tale of 'friendship' & rivalry."


def test_download_anpanman_format_media_filename() -> None:
    file_info = EpisodeFile(
        name="0001a.mp4",
        size=1000,
        md5=None,
        episode_number=1,
        segment="a",
        season=1,
    )
    metadata = {
        "0001a": {
            "title_ro": "Anpanman Tanjou",
            "title_ja": "アンパンマン誕生",
        }
    }

    assert format_media_filename(file_info, metadata) == "Soreike! Anpanman - S01E01a - Anpanman Tanjou.mp4"

    # Missing metadata entry fallback
    assert format_media_filename(file_info, {}) == "Soreike! Anpanman - S01E01a.mp4"


def test_download_anpanman_ensure_media_link_and_nfo(tmp_path: Path) -> None:
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    source_path = downloads_dir / "0001a.mp4"
    source_path.write_bytes(b"test mp4 video content")

    media_dir = tmp_path / "media"
    file_info = EpisodeFile(
        name="0001a.mp4",
        size=source_path.stat().st_size,
        md5=None,
        episode_number=1,
        segment="a",
        season=1,
    )
    metadata = {
        "0001a": {
            "title_ro": "Anpanman Tanjou",
            "title_ja": "アンパンマン誕生",
        }
    }

    link_filename = ensure_media_link_and_nfo(source_path, media_dir, file_info, metadata)
    assert link_filename == "Soreike! Anpanman - S01E01a - Anpanman Tanjou.mp4"

    season_dir = media_dir / "Season 01"
    link_path = season_dir / link_filename
    assert link_path.exists()
    assert link_path.stat().st_ino == source_path.stat().st_ino  # Hardlink verified

    nfo_path = season_dir / "Soreike! Anpanman - S01E01a - Anpanman Tanjou.nfo"
    assert nfo_path.exists()

    root = ET.fromstring(nfo_path.read_text(encoding="utf-8"))
    assert root.tag == "episodedetails"
    assert root.findtext("title") == "Anpanman Tanjou"
    assert root.findtext("originaltitle") == "アンパンマン誕生"
    assert root.findtext("season") == "1"
    assert root.findtext("episode") == "1"

    # Idempotency test: preserve existing nfo content
    nfo_path.write_text("<custom>existing</custom>", encoding="utf-8")
    ensure_media_link_and_nfo(source_path, media_dir, file_info, metadata)
    assert nfo_path.read_text(encoding="utf-8") == "<custom>existing</custom>"
