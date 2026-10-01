"""Tests for weechat-to-soju importer."""

from __future__ import annotations

from pathlib import Path

import sqlite_utils

from soju.importer.cli import SojuLogImporter


def test_weechat_importer_db(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    sample_log = logs_dir / "irc.libera.#channel.weechatlog"
    sample_log.write_text(
        "2026-09-30 10:00:00\tshurane\tHello world\n"
        "2026-09-30 10:01:00\t-->\talice (alice@host) has joined #channel\n"
        "2026-09-30 10:02:00\t<--\tbob (bob@host) has left #channel\n",
        encoding="utf-8",
    )

    db_path = tmp_path / "soju.db"
    db = sqlite_utils.Database(db_path)
    db.table("User").create({"id": int, "username": str, "admin": int}, pk="id")
    db.table("Network").create(
        {"id": int, "user": int, "name": str, "addr": str, "nick": str, "enabled": int},
        pk="id",
    )
    db.table("MessageTarget").create({"id": int, "network": int, "target": str}, pk="id")
    db.table("Message").create(
        {"id": int, "target": int, "raw": str, "time": str, "sender": str, "text": str},
        pk="id",
    )

    importer = SojuLogImporter(
        logs_dir=logs_dir,
        db_path=db_path,
        mode="db",
        username="shurane",
    )
    targets = importer.discover_targets()
    assert len(targets) == 1

    importer.import_to_db(targets)

    rows = list(db.table("Message").rows)
    assert len(rows) == 3
    assert rows[0]["sender"] == "shurane"
    assert rows[0]["text"] == "Hello world"
