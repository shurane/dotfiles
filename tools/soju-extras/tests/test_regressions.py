"""Behavioral regressions against the real schema, including interrupted writes."""

import gzip
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from soju_extras.export_fs.cli import SojuFSExporter
from soju_extras.grep.cli import execute_search
from soju_extras.importer.cli import SojuLogImporter
from soju_extras.models import SearchQuery
from tests.conftest import add_message


def exported_text(root: Path) -> str:
    return "".join(gzip.decompress(p.read_bytes()).decode() for p in sorted(root.rglob("*.log.gz")))


def test_search_real_fts_schema(soju_db: Path) -> None:
    add_message(soju_db)
    results = execute_search(SearchQuery(pattern="world", db_path=soju_db))
    assert len(results) == 1
    assert results[0].text == "hello \x01world\x02"


def test_export_retry_after_output_before_checkpoint(
    soju_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_message(soju_db)
    exporter = SojuFSExporter(soju_db, tmp_path / "out")

    def interrupt(last_id: int) -> None:
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(exporter, "set_last_synced_id", interrupt)
        with pytest.raises(KeyboardInterrupt):
            exporter.run()
    assert exporter.run() == 0
    assert exported_text(tmp_path / "out").count("hello world") == 1


def test_unnamed_network(soju_db: Path, tmp_path: Path) -> None:
    add_message(soju_db)
    with closing(sqlite3.connect(soju_db)) as db, db:
        db.execute("UPDATE Network SET name = NULL")
    assert SojuFSExporter(soju_db, tmp_path / "out").run() == 0
    assert "hello world" in exported_text(tmp_path / "out")


def test_import_repeat_preserves_real_repetitions(soju_db: Path, tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    line = "2026-09-30 10:00:00\talice\thello\n"
    source = logs / "irc.libera.#python.weechatlog"
    source.write_text(line * 2)
    importer = SojuLogImporter(logs_dir=logs, db_path=soju_db, batch_size=1)
    importer.run()
    importer.run()
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT count(*) FROM Message").fetchone()[0] == 2
    source.write_text(line * 2 + "2026-09-30 10:01:00\tbob\tnew\n")
    importer.run()
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT count(*) FROM Message").fetchone()[0] == 3


def test_import_offset_and_fraction(soju_db: Path, tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "irc.libera.#python.weechatlog").write_text(
        "2026-09-30 10:00:00.123-05:00\talice\thello\n"
    )
    SojuLogImporter(logs_dir=logs, db_path=soju_db).run()
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT time FROM Message").fetchone()[0] == "2026-09-30T15:00:00.123Z"
