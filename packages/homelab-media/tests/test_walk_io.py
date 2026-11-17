"""I/O-behaviour and boundary tests for the single-pass torrent walker and .syncignore handling."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import make_sparse_video as _video
from conftest import make_test_config as _cfg
from homelab_media import parser as hm_parser
from homelab_media.filter import SyncIgnore, load_syncignore
from homelab_media.models import ActionType, ReasonCode
from homelab_media.scanner import scan_media_gaps


@pytest.fixture
def scandir_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real = os.scandir

    def counting(path: str | os.PathLike[str] = ".") -> os.scandir:  # type: ignore[type-arg]
        calls.append(os.fspath(path))
        return real(path)

    monkeypatch.setattr(os, "scandir", counting)
    return calls


def test_each_torrent_directory_scanned_exactly_once_and_pruned_dirs_never_opened(
    tmp_path: Path,
    scandir_calls: list[str],
) -> None:
    cfg = _cfg(tmp_path)
    show = cfg.torrents_tv_dir / "Show.2020.S01.1080p"
    for e in range(1, 4):
        _video(show / "Season 01" / f"Show.2020.S01E{e:02d}.mkv")
    _video(show / "Extras" / "bts.mkv")
    scandir_calls.clear()

    scan_media_gaps(cfg, use_qbittorrent=False)

    in_torrent = [c for c in scandir_calls if c.startswith(str(show))]
    assert sorted(in_torrent) == sorted([str(show), str(show / "Season 01")])


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


def test_empty_syncignore_short_circuits_and_reports_syncignore(
    tmp_path: Path,
    scandir_calls: list[str],
) -> None:
    cfg = _cfg(tmp_path)
    show = cfg.torrents_tv_dir / "Show.2020.S01.1080p"
    for e in range(1, 4):
        _video(show / "Season 01" / f"Show.2020.S01E{e:02d}.mkv")
    (show / ".syncignore").write_text("# nothing\n\n", encoding="utf-8")
    scandir_calls.clear()

    report = scan_media_gaps(cfg, use_qbittorrent=False)

    assert report.ready_to_sync == []
    assert len(report.ignored_items) == 1
    assert report.ignored_items[0].source_file == show / ".syncignore"
    assert report.ignored_items[0].reason == ReasonCode.SYNCIGNORE_DIR
    assert report.ignored_items[0].action_type == ActionType.IGNORED
    # Subdirectory Season 01 was never opened because root .syncignore short-circuited!
    assert str(show / "Season 01") not in scandir_calls


def test_resolve_parent_folder_called_once_per_multi_episode_torrent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _cfg(tmp_path)
    show = cfg.torrents_tv_dir / "Show.2020.S01.1080p"
    for e in range(1, 7):
        _video(show / f"Show.2020.S01E{e:02d}.mkv")

    calls: list[str] = []
    real_resolve = hm_parser.resolve_parent_folder

    def counting_resolve(*a: object, **k: object) -> hm_parser.ParentResolution:
        calls.append(str(a[1]))
        return real_resolve(*a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr("homelab_media.scanner.resolve_parent_folder", counting_resolve)
    monkeypatch.setattr("homelab_media.parser.resolve_parent_folder", counting_resolve)
    report = scan_media_gaps(cfg, use_qbittorrent=False)

    assert len(report.ready_to_sync) == 6
    assert len(calls) == 1


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


def test_non_video_and_keyword_extras_never_call_stat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _cfg(tmp_path)
    show = cfg.torrents_tv_dir / "Show.2020.S01.1080p"
    show.mkdir(parents=True)
    (show / "readme.nfo").write_text("info", encoding="utf-8")
    (show / "subs.srt").write_text("1", encoding="utf-8")
    _video(show / "Show.2020.S01E01.Sample.mkv", size=5 * 1024 * 1024)

    stat_calls: list[str] = []
    real_scandir = os.scandir

    class _ProxyEntry:
        def __init__(self, inner: os.DirEntry[str]) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

        def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
            stat_calls.append(self._inner.name)
            return self._inner.stat(follow_symlinks=follow_symlinks)

    class _ProxyScandir:
        def __init__(self, path: str | os.PathLike[str]) -> None:
            self._cm = real_scandir(path)

        def __enter__(self) -> list[_ProxyEntry]:
            return [_ProxyEntry(e) for e in self._cm.__enter__()]

        def __exit__(self, *args: object) -> None:
            self._cm.__exit__(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "scandir", _ProxyScandir)
    report = scan_media_gaps(cfg, use_qbittorrent=False)

    assert len(report.skipped_extras) == 3
    assert stat_calls == []


def test_conflict_detection_uses_in_memory_library_index_without_stat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _cfg(tmp_path)
    _video(cfg.torrents_movies_dir / "Dune.2021.1080p.mkv")
    existing_target = cfg.media_movies_dir / "Dune (2021)" / "Dune (2021).mkv"
    _video(existing_target)  # different inode -> conflict

    target_stats: list[str] = []
    real_stat = Path.stat

    def counting_stat(self: Path, *a: object, **k: object) -> os.stat_result:
        if self == existing_target:
            target_stats.append(str(self))
        return real_stat(self, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "stat", counting_stat)
    report = scan_media_gaps(cfg, use_qbittorrent=False)

    assert len(report.conflicts) == 1
    assert target_stats == []


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
