import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from homelab_scripts.download_anpanman import (
    METADATA_URL,
    EpisodeFile,
    compute_file_md5,
    ensure_hardlink,
    fetch_archive_files,
)


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


@pytest.mark.anyio
async def test_fetch_archive_files_parsing_and_sorting(tmp_path: Path) -> None:
    mock_payload = {
        "files": [
            {"name": "Anpanman - 150.mp4", "size": "150000000", "md5": "md5_150"},
            {"name": "Anpanman - 001a_512kb.mp4", "size": "10000000", "md5": "md5_deriv"},
            {"name": "Anpanman - 580.mp4", "size": "180000000", "md5": "md5_580"},
            {"name": "metadata.xml", "size": "500"},
            {"name": "unrelated_video.mp4", "size": "12345"},
            {"name": "Anpanman - 001B.mp4", "size": "55000000", "md5": "md5_001b"},
            {"name": "Anpanman - 001a.mp4", "size": "50000000", "md5": "md5_001a"},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == METADATA_URL
        return httpx.Response(200, json=mock_payload)

    cache_file = tmp_path / "metadata_cache.json"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        episodes = await fetch_archive_files(client, cache_path=cache_file)

    # Filtering checks: derivatives (_512kb), non-mp4, and unmatched names skipped
    assert len(episodes) == 4

    # Sorting checks: (episode_number, segment)
    assert [ep.name for ep in episodes] == [
        "Anpanman - 001a.mp4",
        "Anpanman - 001B.mp4",
        "Anpanman - 150.mp4",
        "Anpanman - 580.mp4",
    ]

    # EpisodeFile attributes and season calculation checks
    ep_001a = episodes[0]
    assert ep_001a.episode_number == 1
    assert ep_001a.segment == "a"
    assert ep_001a.season == 1
    assert ep_001a.size == 50000000
    assert ep_001a.md5 == "md5_001a"

    ep_001b = episodes[1]
    assert ep_001b.episode_number == 1
    assert ep_001b.segment == "b"  # Segment case-normalized
    assert ep_001b.season == 1

    ep_150 = episodes[2]
    assert ep_150.episode_number == 150
    assert ep_150.segment == ""
    assert ep_150.season == 2  # min(6, max(1, ((150-1)//100)+1)) = 2

    ep_580 = episodes[3]
    assert ep_580.episode_number == 580
    assert ep_580.segment == ""
    assert ep_580.season == 6  # min(6, max(1, ((580-1)//100)+1)) = 6

    # Verify cache file written to disk
    assert cache_file.exists()
    cached_data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert len(cached_data["files"]) == len(mock_payload["files"])


@pytest.mark.anyio
async def test_fetch_archive_files_cache_hit(tmp_path: Path) -> None:
    cached_payload = {
        "files": [
            {"name": "Anpanman - 042.mp4", "size": "42000000", "md5": "md5_42"},
        ]
    }
    cache_file = tmp_path / "existing_cache.json"
    cache_file.write_text(json.dumps(cached_payload), encoding="utf-8")

    # If network request is made, fail immediately
    def failing_handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("Network request should not have been made on fresh cache hit")

    async with httpx.AsyncClient(transport=httpx.MockTransport(failing_handler)) as client:
        episodes = await fetch_archive_files(client, cache_path=cache_file)

    assert len(episodes) == 1
    assert episodes[0].episode_number == 42
    assert episodes[0].name == "Anpanman - 042.mp4"


@pytest.mark.anyio
async def test_fetch_archive_files_dry_run_does_not_cache(tmp_path: Path) -> None:
    mock_payload = {
        "files": [
            {"name": "Anpanman - 099.mp4", "size": "99000000", "md5": "md5_99"},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_payload)

    cache_file = tmp_path / "dry_run_cache.json"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        episodes = await fetch_archive_files(client, cache_path=cache_file, dry_run=True)

    assert len(episodes) == 1
    assert episodes[0].episode_number == 99
    assert not cache_file.exists()
