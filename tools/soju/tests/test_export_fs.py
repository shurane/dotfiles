"""Unit tests for SojuFSExporter."""

from __future__ import annotations

import gzip
from pathlib import Path

import sqlite_utils

from soju.export_fs.cli import SojuFSExporter


def setup_mock_soju_db(db_path: Path) -> None:
    db = sqlite_utils.Database(db_path)
    db.table("User").insert({"id": 1, "username": "shurane", "admin": 1})
    db.table("Network").insert(
        {
            "id": 1,
            "user": 1,
            "name": "libera",
            "addr": "irc.libera.chat:6697",
            "nick": "shurane",
            "enabled": 1,
        }
    )
    db.table("MessageTarget").insert({"id": 1, "network": 1, "target": "#python"})
    db.table("Message").insert_all(
        [
            {
                "id": 1,
                "target": 1,
                "time": "2026-09-30T10:00:00.000Z",
                "sender": "alice",
                "text": "Hello world",
                "raw": "@time=... :alice!user@host PRIVMSG #python :Hello world",
            },
            {
                "id": 2,
                "target": 1,
                "time": "2026-09-30T10:01:00.000Z",
                "sender": "bob",
                "text": "Hey alice",
                "raw": "@time=... :bob!user@host PRIVMSG #python :Hey alice",
            },
        ]
    )


def test_soju_fs_exporter_incremental(tmp_path: Path) -> None:
    db_path = tmp_path / "soju.db"
    out_dir = tmp_path / "logs"
    setup_mock_soju_db(db_path)

    exporter = SojuFSExporter(db_path=db_path, output_dir=out_dir, compress=True)
    res = exporter.run()
    assert res == 0
    assert exporter.get_last_synced_id() == 2

    # Check generated log file
    log_file = (
        out_dir
        / "users"
        / "shurane"
        / "networks"
        / "libera"
        / "channels"
        / "#python"
        / "2026-09-30.log.gz"
    )
    assert log_file.exists()

    with gzip.open(log_file, "rt", encoding="utf-8") as f:
        content = f.read()
    assert "<alice> Hello world" in content
    assert "<bob> Hey alice" in content

    # Second run with no new messages should be a no-op
    res2 = exporter.run()
    assert res2 == 0
    assert exporter.get_last_synced_id() == 2
