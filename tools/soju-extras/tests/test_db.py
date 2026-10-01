"""Tests for open_soju_db context manager."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from soju_extras.db import open_soju_db


def test_open_soju_db_read_write(tmp_path: Path) -> None:
    db_file = tmp_path / "test.db"
    with open_soju_db(db_file, readonly=False) as db:
        db.table("test_table").insert({"name": "soju"})
        rows = list(db.query("SELECT * FROM test_table"))
        assert len(rows) == 1
        assert rows[0]["name"] == "soju"

    # Verify db connection was closed
    with pytest.raises(sqlite3.ProgrammingError):
        db.conn.execute("SELECT 1")


def test_open_soju_db_readonly(tmp_path: Path) -> None:
    db_file = tmp_path / "test_ro.db"
    with open_soju_db(db_file, readonly=False) as db:
        db.table("items").insert({"val": 42})

    with open_soju_db(db_file, readonly=True) as db:
        rows = list(db.query("SELECT * FROM items"))
        assert rows[0]["val"] == 42
        with pytest.raises(sqlite3.OperationalError):
            db.table("items").insert({"val": 99})
