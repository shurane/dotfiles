"""Database context manager and connection utilities using sqlite-utils."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlite_utils


@contextmanager
def open_soju_db(
    path: Path | str,
    *,
    readonly: bool = False,
) -> Iterator[sqlite_utils.Database]:
    """Open a Soju SQLite database wrapped in sqlite_utils.Database.

    Provides a clean context manager that automatically closes connections.
    In read-only mode, uses SQLite URI `mode=ro` and enforces `PRAGMA query_only = ON`
    so queries run safely against a live bouncer database without locks or accidental writes.
    """
    resolved_path = Path(path).resolve()
    if readonly:
        uri = f"file:{resolved_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.execute("PRAGMA query_only = ON")
        db = sqlite_utils.Database(conn)
    else:
        db = sqlite_utils.Database(resolved_path)

    try:
        yield db
    finally:
        db.conn.close()
