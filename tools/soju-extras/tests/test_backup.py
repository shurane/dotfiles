"""Exercise real SQLite/rsync/compression and destructive retention boundaries."""

import gzip
import json
import sqlite3
import subprocess
from compression import zstd
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import pytest
from pydantic import ValidationError
from whenever import Instant

from soju_extras.backup.models import (
    BackupConfig,
    CopySource,
    DirectoryEntry,
    Manifest,
    Receipt,
    Remote,
    Retention,
    SymlinkEntry,
    snapshot_name,
)
from soju_extras.backup.retention import completed, prune, retained
from soju_extras.backup.runner import complete, create_backup
from soju_extras.backup.snapshot import (
    MANIFEST,
    RECEIPT,
    backup_database,
    check_database,
    pack_tree,
    restore_snapshot,
    sha256,
    verify_snapshot,
)
from soju_extras.export_fs.storage import export_lock


def stamp(day: str, hour: str = "120000") -> str:
    return day + "T" + hour + "Z"


def mark(root: Path, name: str) -> Path:
    snapshot = root / name
    snapshot.mkdir(parents=True)
    (snapshot / MANIFEST).write_text(Manifest(snapshot=name, entries=[]).model_dump_json())
    receipt = Receipt(snapshot=name, manifest_sha256=sha256(snapshot / MANIFEST))
    (snapshot / RECEIPT).write_text(receipt.model_dump_json())
    return snapshot


@pytest.fixture
def config(tmp_path: Path, soju_db: Path) -> BackupConfig:
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "channel").mkdir()
    with gzip.open(exports / "channel/2026-10-01.log.gz", "wb") as writer:
        writer.write(b"2026-10-01 hello\n" * 100)
    return BackupConfig(
        database=soju_db,
        export_directory=exports,
        root=tmp_path / "backups",
        sources=[CopySource(source=exports, destination="soju/logs", excludes=[".export.lock"])],
        last_file=tmp_path / "last",
        success_file=tmp_path / "success",
    )


def fake_clock(monkeypatch: pytest.MonkeyPatch, *times: str) -> None:
    values = iter(times)
    monkeypatch.setattr(
        "soju_extras.backup.runner.Instant",
        SimpleNamespace(now=lambda: Instant.parse_iso(next(values))),
    )


def test_online_wal_backup_contains_committed_rows(tmp_path: Path, soju_db: Path) -> None:
    with closing(sqlite3.connect(soju_db)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE User SET username='committed'")
        writer.commit()
        destination = tmp_path / "snapshot/main.db"
        backup_database(soju_db, destination)
        with closing(sqlite3.connect(destination)) as copied:
            assert copied.execute("SELECT username FROM User").fetchone() == ("committed",)
        assert Path(str(soju_db) + "-wal").exists()
        assert not Path(str(destination) + "-wal").exists()
        assert not Path(str(destination) + "-shm").exists()
    check_database(destination)
    with pytest.raises(FileExistsError):
        backup_database(soju_db, destination)


def test_pack_restore_all_encodings_modes_links_and_empty_dirs(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "empty").mkdir(mode=0o750)
    (raw / "settings").write_bytes(b"secret value\n")
    (raw / "empty-file").touch()
    with gzip.open(raw / "empty.gz", "wb"):
        pass
    (raw / "settings").chmod(0o600)
    (raw / "helper").write_bytes(b"#!/bin/sh\nexit 0\n")
    (raw / "helper").chmod(0o755)
    (raw / "autoload").mkdir()
    (raw / "autoload/helper").symlink_to("../helper")
    with gzip.open(raw / "daily.log.gz", "wb") as writer:
        writer.write(b"daily lines\n" * 100)
    with zstd.open(raw / "monthly.log.zst", "wb") as writer:
        writer.write(b"older lines\n" * 100)
    snapshot = tmp_path / "snapshot"
    pack_tree(raw, snapshot, stamp("2026-10-01"))
    assert not list(snapshot.rglob("*.gz"))
    assert not list(snapshot.rglob("*.zst.zst"))
    assert (snapshot / "daily.log.zst").exists()
    assert (snapshot / "monthly.log.zst").read_bytes() == (raw / "monthly.log.zst").read_bytes()
    restored = tmp_path / "restored"
    restore_snapshot(snapshot, restored)
    assert (restored / "settings").read_bytes() == (raw / "settings").read_bytes()
    assert (restored / "empty-file").read_bytes() == b""
    with gzip.open(restored / "empty.gz", "rb") as reader:
        assert reader.read() == b""
    assert (restored / "helper").stat().st_mode & 0o777 == 0o755
    assert (restored / "empty").stat().st_mode & 0o777 == 0o750
    assert (restored / "autoload/helper").readlink() == Path("../helper")
    with gzip.open(restored / "daily.log.gz", "rb") as reader:
        assert reader.read() == b"daily lines\n" * 100
    with pytest.raises(FileExistsError):
        restore_snapshot(snapshot, restored)


def test_corruption_prevents_restore_publication(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "config").write_bytes(b"test")
    snapshot = tmp_path / "snapshot"
    pack_tree(raw, snapshot, stamp("2026-10-01"))
    (snapshot / "config.zst").write_bytes(b"bad")
    with pytest.raises(ValueError, match="checksum"):
        restore_snapshot(snapshot, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_compression_collision_fails_instead_of_overwriting(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "log").write_bytes(b"first")
    with zstd.open(raw / "log.zst", "wb") as writer:
        writer.write(b"second")
    with pytest.raises(ValueError, match="collision"):
        pack_tree(raw, tmp_path / "snapshot", stamp("2026-10-01"))


@pytest.mark.parametrize("value", ["../escape", "/absolute", "a/../b", "./x", "a//b", "."])
def test_manifest_rejects_unsafe_paths(value: str) -> None:
    with pytest.raises(ValidationError):
        DirectoryEntry(path=value, mode=0o700)


def test_manifest_rejects_symlink_parent() -> None:
    with pytest.raises(ValidationError, match="descends"):
        Manifest(
            snapshot=stamp("2026-10-01"),
            entries=[
                SymlinkEntry(path="parent", mode=0o777, target="/tmp"),
                SymlinkEntry(path="parent/escape", mode=0o777, target="/etc"),
            ],
        )


@pytest.mark.parametrize("value", ["../escape", "2026-99-01T120000Z", "2026-10-01T126000Z"])
def test_snapshot_name_validation(value: str) -> None:
    with pytest.raises(ValueError):
        snapshot_name(value)


def test_retention_calendar_buckets_timezone_and_sparse_schedule() -> None:
    names = [stamp(str(date(2026, 1, 1) + timedelta(days=i))) for i in range(274)]
    keep = retained(names, Retention())
    assert set(names[-7:]) <= keep
    assert len(keep) <= 17
    assert {name[:7] for name in keep} == {
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
        "2026-10",
    }
    assert retained([names[0]], Retention()) == {names[0]}
    # These UTC dates belong to the same Chicago calendar day.
    same_day = [stamp("2026-09-30", "230000"), stamp("2026-10-01", "010000")]
    assert retained(same_day, Retention(daily=7, weekly=0, monthly=0)) == {same_day[-1]}


def test_prune_ignores_legacy_incomplete_and_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "backups"
    first = mark(root, stamp("2026-09-30"))
    latest = mark(root, stamp("2026-10-01"))
    legacy = root / stamp("2020-01-01")
    legacy.mkdir()
    (root / ".pending-unfinished").mkdir()
    (root / stamp("2020-01-02")).symlink_to(first, target_is_directory=True)
    policy = Retention(daily=1, weekly=0, monthly=0)
    assert prune(root, policy) == [first.name]
    assert first.exists()
    assert prune(root, policy, apply=True) == [first.name]
    assert latest.exists() and legacy.exists()
    assert (root / stamp("2020-01-02")).is_symlink()


def test_invalid_receipt_aborts_pruning(tmp_path: Path) -> None:
    old = mark(tmp_path, stamp("2026-09-30"))
    new = mark(tmp_path, stamp("2026-10-01"))
    (new / MANIFEST).write_text("{}")
    with pytest.raises(ValueError, match="receipt"):
        prune(tmp_path, Retention(daily=1, weekly=0, monthly=0), apply=True)
    assert old.exists()


def test_full_backup_restore_and_hardlink_reuse(
    config: BackupConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_clock(monkeypatch, "2026-10-01T12:00:00Z", "2026-10-02T12:00:00Z")
    first = create_backup(config)
    verify_snapshot(first)
    second = create_backup(config)
    relative = "soju/logs/channel/2026-10-01.log.zst"
    assert (first / relative).stat().st_ino == (second / relative).stat().st_ino
    assert completed(config.root) == [first.name, second.name]
    restored = config.root.parent / "restored"
    restore_snapshot(second, restored)
    check_database(restored / "soju/main.db")
    assert config.last_file is not None and config.last_file.read_text().strip() == second.name


def test_failed_transfer_never_completes_or_prunes_then_retry_succeeds(
    config: BackupConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_clock(monkeypatch, "2026-09-01T12:00:00Z", "2026-10-01T12:00:00Z", "2026-10-01T12:00:01Z")
    first = create_backup(config)
    remote_config = config.model_copy(
        update={
            "remote": Remote(
                host="pi@raspy.lan", identity_file=Path("/key"), known_hosts=Path("/hosts")
            ),
            "retention": Retention(daily=1, weekly=0, monthly=0),
        }
    )

    def failed(*_args: object) -> None:
        raise subprocess.CalledProcessError(1, "rsync")

    monkeypatch.setattr("soju_extras.backup.runner.deliver", failed)
    with pytest.raises(subprocess.CalledProcessError):
        create_backup(remote_config)
    assert completed(config.root) == [first.name]
    assert (config.root / stamp("2026-10-01")).exists()
    assert not (config.root / stamp("2026-10-01") / RECEIPT).exists()
    monkeypatch.setattr("soju_extras.backup.runner.deliver", lambda *_args: None)
    monkeypatch.setattr(
        "soju_extras.backup.runner.complete", lambda path, _remote: complete(path, None)
    )
    last = create_backup(remote_config)
    assert completed(config.root) == [last.name]
    assert not first.exists()
    assert (config.root / stamp("2026-10-01")).exists()  # incomplete is never pruned


def test_export_lock_failure_leaves_no_snapshot(config: BackupConfig) -> None:
    with export_lock(config.export_directory / ".export.lock"), pytest.raises(ValueError):
        create_backup(config)
    assert completed(config.root) == []
    assert not list(config.root.glob(".pending-*"))


def test_cli_failure_exit_code(tmp_path: Path) -> None:
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "soju_extras.backup.cli", "verify", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_config_boundary_rejects_overlapping_paths(config: BackupConfig) -> None:
    data = json.loads(config.model_dump_json())
    data["sources"].append(dict(source="/outside", destination="soju/logs/nested"))
    with pytest.raises(ValidationError, match="overlap"):
        BackupConfig.model_validate_json(json.dumps(data))


def test_invalid_timezone_is_a_validation_error() -> None:
    with pytest.raises(ValidationError, match="Unknown timezone"):
        Retention(timezone="Not/A_Zone")


def test_truncated_stream_with_matching_stored_hash_is_rejected(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "file").write_bytes(b"content")
    snapshot = tmp_path / "snapshot"
    pack_tree(raw, snapshot, stamp("2026-10-01"))
    stored = snapshot / "file.zst"
    stored.write_bytes(b"")
    manifest = json.loads((snapshot / MANIFEST).read_text())
    manifest["entries"][0]["stored_sha256"] = sha256(stored)
    (snapshot / MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Invalid Zstandard payload: file"):
        verify_snapshot(snapshot)


def test_missing_prune_root_is_not_created(tmp_path: Path) -> None:
    root = tmp_path / "does-not-exist"
    with pytest.raises(FileNotFoundError):
        prune(root, Retention())
    assert not root.exists()


def test_database_backup_cannot_follow_staged_symlink(tmp_path: Path, soju_db: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        backup_database(soju_db, link / "main.db")
    assert not (outside / "main.db").exists()


@pytest.mark.parametrize("encoding", ["plain", "gzip", "zstd"])
@pytest.mark.parametrize("old_manifest", [False, True])
def test_unchanged_files_skip_compression_and_preserve_new_permissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    encoding: Literal["plain", "gzip", "zstd"],
    old_manifest: bool,
) -> None:
    from soju_extras.backup.snapshot import decoded

    raw = tmp_path / "raw"
    raw.mkdir()
    name = {"plain": "file", "gzip": "file.gz", "zstd": "file.zst"}[encoding]
    path = raw / name
    if encoding == "plain":
        path.write_bytes(b"unchanged content")
    elif encoding == "gzip":
        with gzip.open(path, "wb") as writer:
            writer.write(b"unchanged content")
    else:
        with zstd.open(path, "wb") as writer:
            writer.write(b"unchanged content")
    path.chmod(0o600)
    first = tmp_path / "first"
    pack_tree(raw, first, stamp("2026-10-01"))
    if old_manifest:
        data = json.loads((first / MANIFEST).read_text())
        data["version"] = 1
        for entry in data["entries"]:
            entry.pop("source_sha256", None)
        (first / MANIFEST).write_text(json.dumps(data))
    path.chmod(0o755)

    def unexpected(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Unchanged payload was recompressed")

    monkeypatch.setattr("soju_extras.backup.snapshot.pack_file", unexpected)
    second = tmp_path / "second"
    pack_tree(raw, second, stamp("2026-10-02"), previous=first)
    verify_snapshot(second)
    assert (first / "file.zst").stat().st_ino == (second / "file.zst").stat().st_ino
    assert (first / "file.zst").stat().st_mode & 0o777 == 0o600
    restored = tmp_path / "restored"
    restore_snapshot(second, restored)
    assert (restored / name).stat().st_mode & 0o777 == 0o755
    with decoded(restored / name, encoding) as reader:
        assert reader.read() == b"unchanged content"


def test_edited_file_with_unchanged_size_and_mtime_is_not_reused(tmp_path: Path) -> None:
    import os

    raw = tmp_path / "raw"
    raw.mkdir()
    source = raw / "file"
    source.write_bytes(b"one")
    before = source.stat()
    first, second = tmp_path / "first", tmp_path / "second"
    pack_tree(raw, first, stamp("2026-10-01"))
    source.write_bytes(b"two")
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    pack_tree(raw, second, stamp("2026-10-02"), previous=first)
    assert (first / "file.zst").stat().st_ino != (second / "file.zst").stat().st_ino
    restored = tmp_path / "restored"
    restore_snapshot(second, restored)
    assert (restored / "file").read_bytes() == b"two"


def test_corrupt_previous_payload_is_rebuilt(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "file").write_bytes(b"good source")
    first, second = tmp_path / "first", tmp_path / "second"
    pack_tree(raw, first, stamp("2026-10-01"))
    (first / "file.zst").write_bytes(b"bad backup")
    pack_tree(raw, second, stamp("2026-10-02"), previous=first)
    verify_snapshot(second)
    assert (first / "file.zst").read_bytes() == b"bad backup"
    assert (first / "file.zst").stat().st_ino != (second / "file.zst").stat().st_ino


def test_local_copy_exclusions_and_symlinks_without_rsync(
    config: BackupConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from soju_extras.backup.runner import copy_sources

    source = config.export_directory
    for name in (
        "main.db",
        "nested/main.db",
        "logs/.export.lock",
        "other/.export.lock",
        "nested/__pycache__/skip.pyc",
        "cache.txt",
        "nested/test.tmp",
        ".git/config",
    ):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"content")
    (source / "nested/link").symlink_to("../main.db")
    source_config = config.model_copy(
        update={
            "sources": [
                CopySource(
                    source=source,
                    destination="soju",
                    excludes=["/main.db", "/logs/.export.lock", "__pycache__/", ".git/", "*.tmp"],
                )
            ]
        }
    )

    def unexpected(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Local copy launched an external command")

    monkeypatch.setattr("soju_extras.backup.runner.run", unexpected)
    staged = tmp_path / "stage"
    copy_sources(source_config, staged)
    assert not (staged / "soju/main.db").exists()
    assert not (staged / "soju/logs/.export.lock").exists()
    assert not (staged / "soju/nested/__pycache__").exists()
    assert not (staged / "soju/.git").exists()
    assert not (staged / "soju/nested/test.tmp").exists()
    assert (staged / "soju/nested/main.db").read_bytes() == b"content"
    assert (staged / "soju/other/.export.lock").read_bytes() == b"content"
    assert (staged / "soju/nested/link").readlink() == Path("../main.db")
