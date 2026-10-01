"""Explicit cross-target reconciliation must preserve surplus occurrences."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from soju_extras.importer.cli import SojuLogImporter
from soju_extras.importer.overlap import deduplicate_overlap


def test_overlap_preserves_multiplicity_order_and_originals(tmp_path: Path) -> None:
    preferred, secondary, output = (tmp_path / name for name in ("preferred", "secondary", "out"))
    shared = b"2026-09-30 10:00:00\talice\thello"
    unique = b"2026-09-30 10:00:01\tbob\told only\n"
    different_time = b"2026-09-30 10:00:02\talice\thello\n"
    first = shared + b"\r\n" + b"new only\n"
    second = shared + b"\n" + unique + shared + b"\n" + different_time
    preferred.write_bytes(first)
    secondary.write_bytes(second)
    report = deduplicate_overlap(preferred, secondary, output)
    assert (report.preferred_records, report.secondary_records) == (2, 4)
    assert (report.removed_records, report.retained_records) == (1, 3)
    assert output.read_bytes() == unique + shared + b"\n" + different_time
    assert preferred.read_bytes() == first
    assert secondary.read_bytes() == second
    with pytest.raises(FileExistsError):
        deduplicate_overlap(preferred, secondary, output)
    assert output.read_bytes() == unique + shared + b"\n" + different_time


@pytest.mark.parametrize("broken", ["preferred", "secondary"])
def test_partial_input_does_not_publish_output(tmp_path: Path, broken: str) -> None:
    preferred, secondary, output = (tmp_path / name for name in ("preferred", "secondary", "out"))
    preferred.write_bytes(b"shared\n")
    secondary.write_bytes(b"shared\nunique\n")
    (tmp_path / broken).write_bytes(b"shared\npartial")
    with pytest.raises(ValueError, match="incomplete final line"):
        deduplicate_overlap(preferred, secondary, output)
    assert not output.exists()
    assert not list(tmp_path.glob(".overlap-*"))
    (tmp_path / broken).write_bytes(b"shared\nrecovered\n")
    deduplicate_overlap(preferred, secondary, output)
    assert output.exists()


def test_identical_histories_and_same_input_guard(tmp_path: Path) -> None:
    preferred, secondary, output = (tmp_path / name for name in ("preferred", "secondary", "out"))
    preferred.write_bytes(b"repeat\nrepeat\n")
    secondary.write_bytes(preferred.read_bytes())
    with pytest.raises(ValueError, match="different files"):
        deduplicate_overlap(preferred, preferred, output)
    report = deduplicate_overlap(preferred, secondary, output)
    assert report.removed_records == 2
    assert report.retained_records == 0
    assert output.read_bytes() == b""


def test_reconciled_channels_import_and_retry(soju_db: Path, tmp_path: Path) -> None:
    preferred = tmp_path / "old"
    secondary = tmp_path / "new"
    logs = tmp_path / "prepared"
    logs.mkdir()
    shared = b"2026-09-01 10:00:00\talice\trepeated\n"
    old_only = b"2026-09-20 10:00:00\tbob\told only\n"
    new_only = b"2026-09-07 10:00:00\tcarol\tnew only\n"
    preferred.write_bytes(shared * 2 + old_only)
    secondary.write_bytes(shared * 3 + new_only)
    output = logs / "irc.libera.##c++.weechatlog"
    report = deduplicate_overlap(preferred, secondary, output)
    assert report.retained_records == 2
    assert output.read_bytes() == shared + new_only
    (logs / "irc.libera.#c++.weechatlog").write_bytes(preferred.read_bytes())
    importer = SojuLogImporter(logs, db_path=soju_db)
    assert importer.run() == 5
    assert importer.run() == 0
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute(
            "SELECT t.target, count(*) FROM Message m JOIN MessageTarget t ON t.id=m.target GROUP BY t.target ORDER BY t.target"
        ).fetchall() == [("##c++", 2), ("#c++", 3)]
