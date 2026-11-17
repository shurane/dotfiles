"""Unit tests for homelab_core.db."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from homelab_core.db import wait_for_sqlite_table
from homelab_core.errors import HomelabError

if TYPE_CHECKING:
    from pathlib import Path


def test_wait_for_sqlite_table_returns_when_table_exists(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
    wait_for_sqlite_table(db_path, "users", timeout_seconds=1.0, poll_interval=0.01)


def test_wait_for_sqlite_table_times_out_for_missing_table(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE other_table (id INTEGER PRIMARY KEY);")
    with pytest.raises(HomelabError, match="timed out waiting for table 'users'"):
        wait_for_sqlite_table(db_path, "users", timeout_seconds=0.05, poll_interval=0.01)
