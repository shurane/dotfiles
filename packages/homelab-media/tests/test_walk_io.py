"""I/O-behaviour and boundary tests for the single-pass torrent walker and .syncignore handling."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from homelab_media.config import MediaConfig
from homelab_media.filter import SyncIgnore, load_syncignore
from homelab_media.models import ActionType
from homelab_media.scanner import scan_media_gaps


def _cfg(tmp_path: Path) -> MediaConfig:
    for d in ("torrents/tv", "torrents/movies", "media/tv", "media/movies"):
        (tmp_path / d).mkdir(parents=True)
    return MediaConfig(torrents_dir=tmp_path / "torrents", media_dir=tmp_path / "media")


def _video(path: Path, size: int = 100 * 1024 * 1024) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.truncate(size)
    return path


@pytest.fixture
def scandir_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real = os.scandir

    def counting(path: str | os.PathLike[str] = ".") -> os.scandir:  # type: ignore[type-arg]
        calls.append(os.fspath(path))
        return real(path)

    monkeypatch.setattr(os, "scandir", counting)
    return calls


def test_each_torrent_directory_scanned_exactly_once(tmp_path: Path, scandir_calls: list[str]) -> None:
    cfg = _cfg(tmp_path)
    show = cfg.torrents_tv_dir / "Show.2020.S01.1080p"
    for e in range(1, 4):
        _video(show / "Season 01" / f"Show.2020.S01E{e:02d}.mkv")
    _video(show / "Extras" / "bts.mkv")
    scandir_calls.clear()

    scan_media_gaps(cfg, use_qbittorrent=False)

    in_torrent = [c for c in scandir_calls if c.startswith(str(show))]
    assert sorted(in_torrent) == sorted([str(show), str(show / "Season 01"), str(show / "Extras")])


def test_single_file_movies_do_not_rescan_the_torrents_root(tmp_path: Path, scandir_calls: list[str]) -> None:
    cfg = _cfg(tmp_path)
    for i in range(5):
        _video(cfg.torrents_movies_dir / f"Movie.{i}.2019.1080p.mkv")
    scandir_calls.clear()

    scan_media_gaps(cfg, use_qbittorrent=False)

    assert scandir_calls.count(str(cfg.torrents_movies_dir)) == 1


def test_syncignore_is_read_once_per_torrent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _cfg(tmp_path)
    show = cfg.torrents_tv_dir / "Show.2020.S01.1080p"
    for e in range(1, 11):
        _video(show / f"Show.2020.S01E{e:02d}.mkv")
    (show / ".syncignore").write_text("*E05*\n", encoding="utf-8")

    reads: list[str] = []
    real = Path.read_text

    def counting(self: Path, *a: object, **k: object) -> str:
        if self.name == ".syncignore":
            reads.append(str(self))
        return real(self, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", counting)
    report = scan_media_gaps(cfg, use_qbittorrent=False)

    assert len(reads) == 1
    assert len(report.ignored_items) == 1
    assert len(report.ready_to_sync) == 9


def test_torrents_without_syncignore_never_attempt_a_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _cfg(tmp_path)
    _video(cfg.torrents_tv_dir / "Show.2020.S01.1080p" / "Show.2020.S01E01.mkv")
    attempts: list[str] = []
    real = Path.read_text

    def counting(self: Path, *a: object, **k: object) -> str:
        attempts.append(self.name)
        return real(self, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", counting)
    scan_media_gaps(cfg, use_qbittorrent=False)

    assert ".syncignore" not in attempts


def test_empty_syncignore_ignores_every_file_individually(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    show = cfg.torrents_tv_dir / "Show.2020.S01.1080p"
    for e in range(1, 4):
        _video(show / f"Show.2020.S01E{e:02d}.mkv")
    (show / ".syncignore").write_text("# nothing\n\n", encoding="utf-8")

    report = scan_media_gaps(cfg, use_qbittorrent=False)

    assert report.ready_to_sync == []
    assert {i.reason for i in report.ignored_items} == {"SYNCIGNORE_DIR"}
    assert all(i.action_type == ActionType.IGNORED for i in report.ignored_items)
    assert len(report.ignored_items) == 3


@pytest.mark.parametrize("marker", [".part", ".parts", ".!qB"])
def test_nested_partial_file_skips_whole_torrent(tmp_path: Path, marker: str) -> None:
    cfg = _cfg(tmp_path)
    show = cfg.torrents_tv_dir / "Show.2020.S01.1080p"
    _video(show / "Show.2020.S01E01.mkv")
    (show / "Season 01" / "deep").mkdir(parents=True)
    (show / "Season 01" / "deep" / f"Show.2020.S01E02.mkv{marker}").write_bytes(b"x")

    report = scan_media_gaps(cfg, use_qbittorrent=False)

    assert report.ready_to_sync == []
    assert report.skipped_extras == []
    assert report.already_synced_count == 0


def test_partial_marker_inside_pruned_dir_still_skips_torrent(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    show = cfg.torrents_tv_dir / "Show.2020.S01.1080p"
    _video(show / "Show.2020.S01E01.mkv")
    (show / "Extras").mkdir()
    (show / "Extras" / "bonus.mkv.!qB").write_bytes(b"x")

    assert scan_media_gaps(cfg, use_qbittorrent=False).ready_to_sync == []


def test_empty_directories_and_empty_torrent_dir(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    (cfg.torrents_tv_dir / "Empty.Show.S01").mkdir()
    (cfg.torrents_movies_dir / "Empty.Movie.2020").mkdir()

    report = scan_media_gaps(cfg, use_qbittorrent=False)

    assert report.ready_to_sync == []
    assert report.skipped_extras == []
    assert report.already_synced_count == 0


def test_symlinked_torrent_entry_is_ignored(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    real = tmp_path / "elsewhere" / "Show.2020.S01.1080p"
    _video(real / "Show.2020.S01E01.mkv")
    (cfg.torrents_tv_dir / "Show.2020.S01.1080p").symlink_to(real, target_is_directory=True)

    assert scan_media_gaps(cfg, use_qbittorrent=False).ready_to_sync == []


def test_load_syncignore_boundaries(tmp_path: Path) -> None:
    assert load_syncignore(tmp_path) is None  # no file
    (tmp_path / ".syncignore").write_text("", encoding="utf-8")
    assert load_syncignore(tmp_path) == SyncIgnore(())  # zero bytes -> ignore all
    (tmp_path / ".syncignore").write_text("# c\n  \n*.nfo\n/bonus/\n", encoding="utf-8")
    si = load_syncignore(tmp_path)
    assert si is not None
    assert si.patterns == ("*.nfo", "/bonus/")
    assert si.match(Path("a.nfo")) == "SYNCIGNORE_PATTERN:*.nfo"
    assert si.match(Path("bonus/x.mkv")) == "SYNCIGNORE_PATTERN:/bonus/"
    assert si.match(Path("ep.mkv")) == ""
