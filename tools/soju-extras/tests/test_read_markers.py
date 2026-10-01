"""Read markers are explicit input; logs never imply a read position."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from pydantic import ValidationError

from soju_extras.importer.cli import main
from soju_extras.importer.read_markers import ReadMarkers, import_read_markers


def document(*markers: tuple[str, str, str]) -> str:
    return json.dumps(
        {
            "version": 1,
            "markers": [
                {"network": network, "target": target, "timestamp": timestamp}
                for network, target, timestamp in markers
            ],
        }
    )


def test_explicit_markers_preserve_later_reads_and_map_networks(soju_db: Path) -> None:
    with closing(sqlite3.connect(soju_db)) as db, db:
        db.execute(
            "INSERT INTO ReadReceipt(network,target,timestamp) VALUES(1,'#python','2026-09-30T12:00:00.000Z')"
        )
    markers = ReadMarkers.model_validate_json(
        document(
            ("old-name", "#python", "2026-09-30T06:00:00-05:00"),
            ("old-name", "#new", "2026-09-30T06:00:00.123456-05:00"),
        )
    )
    for _ in range(2):
        import_read_markers(markers, soju_db, "shurane", {"old-name": "libera"})
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute(
            "SELECT target,timestamp FROM ReadReceipt ORDER BY target"
        ).fetchall() == [
            ("#new", "2026-09-30T11:00:00.123Z"),
            ("#python", "2026-09-30T12:00:00.000Z"),
        ]
        assert db.execute("SELECT count(*) FROM Message").fetchone()[0] == 0


def test_marker_import_is_atomic(soju_db: Path) -> None:
    markers = ReadMarkers.model_validate_json(
        document(
            ("libera", "#python", "2026-09-30T10:00:00Z"), ("missing", "#x", "2026-09-30T10:00:00Z")
        )
    )
    with pytest.raises(ValueError, match="missing"):
        import_read_markers(markers, soju_db, "shurane", {})
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT count(*) FROM ReadReceipt").fetchone()[0] == 0


@pytest.mark.parametrize("timestamp", ["2026-09-30T10:00:00", "nonsense"])
def test_markers_require_valid_explicit_offset(timestamp: str) -> None:
    with pytest.raises(ValidationError):
        ReadMarkers.model_validate_json(document(("libera", "#python", timestamp)))


def test_cli_validates_markers_before_messages_and_dry_run_does_not_write(
    soju_db: Path, tmp_path: Path
) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "irc.libera.#python.weechatlog").write_text("2026-09-30 10:00:00\talice\thello\n")
    source = tmp_path / "markers.json"
    args = ["--logs-dir", str(logs), "--db-path", str(soju_db), "--read-markers", str(source)]
    source.write_text("{}")
    assert main(args) == 2
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT count(*) FROM Message").fetchone()[0] == 0
    source.write_text(document(("libera", "#python", "2026-09-29T00:00:00Z")))
    assert main(args + ["--dry-run"]) == 0
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT count(*) FROM ReadReceipt").fetchone()[0] == 0
    assert main(args) == 0
    with closing(sqlite3.connect(soju_db)) as db:
        assert (
            db.execute("SELECT timestamp FROM ReadReceipt").fetchone()[0]
            == "2026-09-29T00:00:00.000Z"
        )


def test_markers_use_existing_ascii_target_casing(soju_db: Path) -> None:
    markers = ReadMarkers.model_validate_json(
        document(("libera", "#Python", "2026-09-20T10:00:00Z"))
    )
    import_read_markers(markers, soju_db, "shurane", {})
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT target FROM ReadReceipt").fetchall() == [("#python",)]


def test_ambiguous_target_casing_aborts_markers(soju_db: Path) -> None:
    with closing(sqlite3.connect(soju_db)) as db, db:
        db.execute("INSERT INTO MessageTarget(network,target) VALUES(1,'#Python')")
    markers = ReadMarkers.model_validate_json(
        document(("libera", "#python", "2026-09-20T10:00:00Z"))
    )
    with pytest.raises(ValueError, match="Ambiguous target casing"):
        import_read_markers(markers, soju_db, "shurane", {})
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT count(*) FROM ReadReceipt").fetchone()[0] == 0


def unread_document() -> ReadMarkers:
    return ReadMarkers.model_validate_json(
        json.dumps(
            {
                "version": 1,
                "markers": [
                    {"network": "libera", "target": "#other", "timestamp": "2026-09-20T00:00:00Z"}
                ],
                "unread": [{"network": "libera", "target": "#Python", "scope": "retained_lines"}],
            }
        )
    )


def test_known_unread_does_not_invent_receipt(soju_db: Path) -> None:
    import_read_markers(unread_document(), soju_db, "shurane", {})
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT target FROM ReadReceipt").fetchall() == [("#other",)]


def test_known_unread_conflict_preserves_database(soju_db: Path) -> None:
    with closing(sqlite3.connect(soju_db)) as db, db:
        db.execute(
            "INSERT INTO ReadReceipt(network,target,timestamp) VALUES(1,'#python','2026-09-30T00:00:00.000Z')"
        )
    with pytest.raises(ValueError, match="snapshot records unread history"):
        import_read_markers(unread_document(), soju_db, "shurane", {})
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT target,timestamp FROM ReadReceipt").fetchall() == [
            ("#python", "2026-09-30T00:00:00.000Z")
        ]


def test_read_and_unread_aliases_conflict_atomically(soju_db: Path) -> None:
    doc = json.loads(unread_document().model_dump_json())
    doc["markers"].append(
        {"network": "libera", "target": "#python", "timestamp": "2026-09-20T00:00:00Z"}
    )
    with pytest.raises(ValueError, match="Conflicting read and unread"):
        import_read_markers(
            ReadMarkers.model_validate_json(json.dumps(doc)), soju_db, "shurane", {}
        )
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT count(*) FROM ReadReceipt").fetchone()[0] == 0
