import hashlib
from pathlib import Path
from urllib.parse import quote

from download_anpanman import EpisodeFile, compute_file_md5, ensure_hardlink


def test_episode_file_attributes_and_url_encoding() -> None:
    # Standard ASCII filename
    ep_ascii = EpisodeFile(
        name="0001a.mp4",
        size=1024,
        md5="fake_md5",
        episode_number=1,
        segment="a",
        season=1,
    )
    assert ep_ascii.download_url == "https://archive.org/download/anpanman-episodes-1-600/0001a.mp4"
    assert ep_ascii.display_tag == "Ep 001A"

    # Japanese filename requiring percent-encoding
    jp_name = "アンパンマン_第1話.mp4"
    ep_jp = EpisodeFile(
        name=jp_name,
        size=2048,
        md5=None,
        episode_number=1,
        segment="",
        season=1,
    )
    assert ep_jp.download_url == f"https://archive.org/download/anpanman-episodes-1-600/{quote(jp_name)}"
    assert ep_jp.display_tag == "Ep 001"


def test_compute_file_md5_empty_and_large(tmp_path: Path) -> None:
    # Empty file
    empty_file = tmp_path / "empty.bin"
    empty_file.write_bytes(b"")
    assert compute_file_md5(empty_file) == "d41d8cd98f00b204e9800998ecf8427e"

    # Multi-block file (>1MB to test streaming chunks)
    data = b"0123456789ABCDEF" * (100 * 1024)  # 1.6 MB
    large_file = tmp_path / "large.bin"
    large_file.write_bytes(data)

    expected_md5 = hashlib.md5(data, usedforsecurity=False).hexdigest().lower()
    assert compute_file_md5(large_file) == expected_md5


def test_ensure_hardlink_operations(tmp_path: Path) -> None:
    src = tmp_path / "source.mp4"
    src.write_bytes(b"sample video bytes")

    dst = tmp_path / "links" / "target.mp4"

    # Initial creation
    assert ensure_hardlink(src, dst) is True
    assert dst.exists()
    assert dst.stat().st_ino == src.stat().st_ino

    # Idempotent call
    assert ensure_hardlink(src, dst) is False
    assert dst.stat().st_ino == src.stat().st_ino

    # Overwrite if target is not linked to source
    other_src = tmp_path / "other.mp4"
    other_src.write_bytes(b"different content")
    assert ensure_hardlink(other_src, dst) is True
    assert dst.stat().st_ino == other_src.stat().st_ino
    assert dst.stat().st_ino != src.stat().st_ino
