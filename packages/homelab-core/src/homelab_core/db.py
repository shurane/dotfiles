"""Database utility functions for homelab services."""

from __future__ import annotations

import contextlib
import sqlite3
import time
from typing import TYPE_CHECKING

from homelab_core.errors import HomelabError

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["wait_for_sqlite_table"]


def wait_for_sqlite_table(
    db_path: Path,
    table_name: str,
    timeout_seconds: float = 60.0,
    poll_interval: float = 1.0,
) -> None:
    """Wait until a specific SQLite table exists in the target database file.

    Raises:
        HomelabError: If the table does not appear before timeout_seconds expires.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if db_path.exists():
            with contextlib.suppress(sqlite3.Error):
                with sqlite3.connect(db_path) as db:
                    row = db.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                        (table_name,),
                    ).fetchone()
                if row is not None:
                    return
        time.sleep(poll_interval)
    raise HomelabError(f"timed out waiting for table {table_name!r} in {db_path}")
