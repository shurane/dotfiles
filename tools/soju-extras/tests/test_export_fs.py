"""Export retry/recovery, bounded batches, paths and CLI failures."""

import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from soju_extras.export_fs.cli import SojuFSExporter, main
from soju_extras.export_fs.storage import export_lock
from tests.conftest import add_message
from tests.test_regressions import exported_text


def test_incremental_and_bounded(soju_db: Path, tmp_path: Path) -> None:
    for i in range(7):
        add_message(soju_db, f"message {i}")
    out = tmp_path / "out"
    exporter = SojuFSExporter(soju_db, out, batch_size=2)
    assert len(exporter.fetch_new_records(0)) == 2
    assert exporter.run() == 0
    assert exporter.get_last_synced_id() == 7
    assert len(exported_text(out).splitlines()) == 7
    add_message(soju_db, "new")
    assert exporter.run() == 0
    assert exporter.run() == 0
    assert len(exported_text(out).splitlines()) == 8
    with pytest.raises(ValueError, match="fresh"):
        exporter.run(force_all=True)


@pytest.mark.parametrize("committed", [False, True])
def test_process_death_before_or_after_checkpoint(
    soju_db: Path, tmp_path: Path, committed: bool
) -> None:
    out = tmp_path / "out"
    add_message(soju_db, "original")
    SojuFSExporter(soju_db, out).run()
    add_message(soju_db, "appended")
    add_message(soju_db, "new day", time="2026-10-01T00:00:00.000Z")
    script = """
import os, sys
from pathlib import Path
from soju_extras.export_fs.cli import SojuFSExporter
exporter = SojuFSExporter(Path(sys.argv[1]), Path(sys.argv[2]))
original = exporter.set_last_synced_id
def terminate(value):
    if sys.argv[3] == 'True':
        original(value)
    os._exit(99)
exporter.set_last_synced_id = terminate
exporter.run()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(soju_db), str(out), str(committed)], check=False
    )
    assert result.returncode == 99
    assert (out / ".append-journal.json").exists()
    if not committed:
        # Simulate a torn compressed append; recovery must remove those bytes too.
        with next(out.rglob("*.gz")).open("ab") as stream:
            stream.write(b"partial gzip member")
    SojuFSExporter(soju_db, out).run()
    content = exported_text(out)
    assert len(content.splitlines()) == 3
    assert content.count("original") == content.count("appended") == content.count("new day") == 1
    assert not (out / ".append-journal.json").exists()


def test_corrupt_checkpoint_and_bad_timestamp_fail(soju_db: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / ".last_synced_id").write_text("broken")
    add_message(soju_db)
    assert main(["--db-path", str(soju_db), "--output-dir", str(out)]) == 2
    assert not list(out.rglob("*.gz"))
    (out / ".last_synced_id").unlink()
    with closing(sqlite3.connect(soju_db)) as db, db:
        db.execute("UPDATE Message SET time = 'invalid'")
    assert main(["--db-path", str(soju_db), "--output-dir", str(out)]) == 2
    assert not (out / ".last_synced_id").exists()


def test_path_encoding_and_symlink_escape(soju_db: Path, tmp_path: Path) -> None:
    add_message(soju_db)
    exporter = SojuFSExporter(soju_db, tmp_path / "out")
    record = exporter.fetch_new_records(0)[0]
    paths = [
        exporter.get_target_log_path(
            record.model_copy(update={"network": "/tmp/../outside", "target": value})
        )
        for value in ["#a/b", "#a_b", "..", "%2E%2E"]
    ]
    assert len(set(paths)) == 4
    assert all(path.is_relative_to(exporter.output_dir) for path in paths)
    exporter.output_dir.mkdir()
    (exporter.output_dir / "users").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        exporter.run()


def test_export_lock_and_dry_run(soju_db: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    add_message(soju_db)
    assert SojuFSExporter(soju_db, out, dry_run=True).run() == 0
    assert not out.exists()
    with export_lock(out / ".export.lock"), pytest.raises(ValueError, match="Another exporter"):
        SojuFSExporter(soju_db, out).run()


def test_uncompressed_export(soju_db: Path, tmp_path: Path) -> None:
    add_message(soju_db)
    out = tmp_path / "out"
    assert main(["--db-path", str(soju_db), "--output-dir", str(out), "--uncompressed"]) == 0
    assert "hello world" in next(out.rglob("*.log")).read_text()


def test_changed_compression_or_missing_checkpoint_rejected(soju_db: Path, tmp_path: Path) -> None:
    add_message(soju_db)
    out = tmp_path / "out"
    exporter = SojuFSExporter(soju_db, out)
    exporter.run()
    with pytest.raises(ValueError, match="compression changed"):
        SojuFSExporter(soju_db, out, compress=False).run()
    exporter.state_file.unlink()
    with pytest.raises(ValueError, match="no usable checkpoint"):
        exporter.run()
    assert exported_text(out).count("hello world") == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (":alice!u@h QUIT :connection lost", "Quits: alice (alice!u@h) (connection lost)"),
        (":alice!u@h PART #python :bye", "Parts: alice (alice!u@h) (bye)"),
        (":alice!u@h JOIN #python", "Joins: alice (alice!u@h)"),
        (":alice!u@h PRIVMSG #python :\x01ACTION waves\x01", "* alice waves"),
    ],
)
def test_real_event_rows_with_null_text(
    soju_db: Path, tmp_path: Path, raw: str, expected: str
) -> None:
    with closing(sqlite3.connect(soju_db)) as db, db:
        db.execute(
            "INSERT INTO Message(target,raw,time,sender,text) VALUES(1,?,'2026-09-30T10:00:00.000Z','alice',NULL)",
            (raw,),
        )
    out = tmp_path / "out"
    SojuFSExporter(soju_db, out).run()
    assert expected in exported_text(out)


@pytest.mark.parametrize("dry_run", [False, True])
def test_live_writes_do_not_extend_run(
    soju_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dry_run: bool
) -> None:
    from soju_extras.models import ExportedLogRecord

    add_message(soju_db, "initial")
    out = tmp_path / "out"
    exporter = SojuFSExporter(soju_db, out, batch_size=1, dry_run=dry_run)
    fetch = exporter.fetch_new_records
    calls = 0

    def fetch_while_writing(start_id: int, end_id: int | None = None) -> list[ExportedLogRecord]:
        nonlocal calls
        calls += 1
        assert calls <= 2, "Export continued following live writes"
        records = fetch(start_id, end_id)
        add_message(soju_db, "arrived during export")
        return records

    monkeypatch.setattr(exporter, "fetch_new_records", fetch_while_writing)
    assert exporter.run() == 0
    if dry_run:
        assert not out.exists()
    else:
        assert len(exported_text(out).splitlines()) == 1


@pytest.mark.parametrize("compress", [False, True])
def test_backfill_is_inserted_chronologically_without_losing_archived_history(
    soju_db: Path, tmp_path: Path, compress: bool
) -> None:
    import gzip

    out = tmp_path / "out"
    add_message(soju_db, "archived", time="2026-09-30T10:00:00.000Z")
    exporter = SojuFSExporter(soju_db, out, compress=compress, batch_size=1)
    exporter.run()
    # Retention has removed the archived message from SQLite. It must survive a rewrite.
    with closing(sqlite3.connect(soju_db)) as db, db:
        db.execute(
            "INSERT INTO Message(id,target,raw,time,sender,text) VALUES(2,1,':alice!u@h PRIVMSG #python :later','2026-09-30T11:00:00.000Z','alice','later')"
        )
        db.execute("DELETE FROM Message WHERE id = 1")
    exporter.run()
    add_message(soju_db, "backfill", time="2026-09-30T09:00:00.000Z")
    add_message(soju_db, "middle", time="2026-09-30T10:30:00.000Z")
    exporter.run()
    exporter.run()
    path = next(out.rglob("*.log.gz" if compress else "*.log"))
    text = gzip.decompress(path.read_bytes()).decode() if compress else path.read_text()
    assert [line.split("> ")[1] for line in text.splitlines()] == [
        "backfill",
        "archived",
        "middle",
        "later",
    ]


@pytest.mark.parametrize("batch_size", [1, 10])
def test_initial_export_sorts_out_of_order_ids(
    soju_db: Path, tmp_path: Path, batch_size: int
) -> None:
    add_message(soju_db, "later", time="2026-09-30T11:00:00.000Z")
    add_message(soju_db, "earlier", time="2026-09-30T09:00:00.000Z")
    add_message(soju_db, "same time", time="2026-09-30T09:00:00.000Z")
    out = tmp_path / "out"
    SojuFSExporter(soju_db, out, batch_size=batch_size).run()
    assert [line.split("> ")[1] for line in exported_text(out).splitlines()] == [
        "earlier",
        "same time",
        "later",
    ]


@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("stage", ["before_replace", "before_checkpoint", "after_checkpoint"])
def test_backfill_process_death_and_retry(
    soju_db: Path, tmp_path: Path, compress: bool, stage: str
) -> None:
    import gzip

    out = tmp_path / "out"
    add_message(soju_db, "original", time="2026-09-30T10:00:00.000Z")
    SojuFSExporter(soju_db, out, compress=compress).run()
    add_message(soju_db, "backfill", time="2026-09-30T09:00:00.000Z")
    # A batch with both a replacement and a new file must recover consistently.
    add_message(soju_db, "other day", time="2026-10-01T00:00:00.000Z")
    script = """
import os, sys
from pathlib import Path
from soju_extras.export_fs.cli import SojuFSExporter
exporter = SojuFSExporter(Path(sys.argv[1]), Path(sys.argv[2]), compress=sys.argv[3] == 'True')
original_checkpoint = exporter.set_last_synced_id
original_replace = os.replace
stage = sys.argv[4]
def replace(source, destination):
    if stage == 'before_replace' and str(source).endswith('.after'):
        os._exit(99)
    original_replace(source, destination)
def checkpoint(value):
    if stage == 'after_checkpoint':
        original_checkpoint(value)
    os._exit(99)
os.replace = replace
exporter.set_last_synced_id = checkpoint
exporter.run()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(soju_db), str(out), str(compress), stage], check=False
    )
    assert result.returncode == 99
    assert (out / ".append-journal.json").exists()
    exporter = SojuFSExporter(soju_db, out, compress=compress)
    exporter.run()
    exporter.run()
    paths = sorted(out.rglob("*.log.gz" if compress else "*.log"))
    contents = [
        gzip.decompress(path.read_bytes()).decode() if compress else path.read_text()
        for path in paths
    ]
    assert [line.split("> ")[1] for line in contents[0].splitlines()] == ["backfill", "original"]
    assert [line.split("> ")[1] for line in contents[1].splitlines()] == ["other day"]
    assert exporter.get_last_synced_id() == 3
    assert not list(out.rglob(".soju-reorder-*"))
    assert not (out / ".append-journal.json").exists()


@pytest.mark.parametrize("compress", [False, True])
def test_legacy_unsorted_archive_is_repaired_without_dropping_duplicates(
    soju_db: Path, tmp_path: Path, compress: bool
) -> None:
    import gzip

    out = tmp_path / "out"
    add_message(soju_db, "original", time="2026-09-30T10:00:00.000Z")
    SojuFSExporter(soju_db, out, compress=compress).run()
    path = next(out.rglob("*.log.gz" if compress else "*.log"))
    # Simulate an older exporter, including its second-resolution timestamps.
    legacy = "[08:00:00] <alice> legacy\n" * 2
    with path.open("ab") as stream:
        stream.write(gzip.compress(legacy.encode()) if compress else legacy.encode())
    add_message(soju_db, "new", time="2026-09-30T12:00:00.000Z")
    SojuFSExporter(soju_db, out, compress=compress).run()
    text = gzip.decompress(path.read_bytes()).decode() if compress else path.read_text()
    assert [line.split("> ")[1] for line in text.splitlines()] == [
        "legacy",
        "legacy",
        "original",
        "new",
    ]
    assert not list(out.rglob(".soju-reorder-*"))
