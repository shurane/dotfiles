"""SQLite lifetimes, transactions, and validated rows."""

import sqlite3
from collections.abc import Generator, Iterable, Iterator, Sequence
from contextlib import closing, contextmanager
from pathlib import Path

from pydantic import BaseModel

type SQLValue = str | int | float | bytes | None


@contextmanager
def open_soju_db(path: Path | str, *, readonly: bool = False) -> Generator[sqlite3.Connection]:
    """Close every connection, including when setup fails. Never create a Soju database."""
    uri = Path(path).resolve().as_uri() + ("?mode=ro" if readonly else "?mode=rw")
    # Transaction scopes below issue explicit BEGIN/COMMIT/ROLLBACK statements.
    with closing(
        sqlite3.connect(
            uri,
            uri=True,
            timeout=30,
            autocommit=True,
        )
    ) as conn:
        conn.row_factory = sqlite3.Row
        execute(conn, "PRAGMA foreign_keys = ON")
        execute(conn, "PRAGMA temp_store = FILE")
        if readonly:
            execute(conn, "PRAGMA query_only = ON")
        yield conn


@contextmanager
def transaction(conn: sqlite3.Connection, *, immediate: bool = True) -> Generator[None]:
    """Acquire the writer lock before checking/inserting, then commit or roll back."""
    if conn.in_transaction:
        raise ValueError("Nested transactions are not supported")
    execute(conn, "BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield
        execute(conn, "COMMIT")
    except BaseException:
        if conn.in_transaction:
            execute(conn, "ROLLBACK")
        raise


def execute(conn: sqlite3.Connection, sql: str, params: Sequence[SQLValue] = ()) -> None:
    """Execute a statement without results. Transaction ownership stays with the caller."""
    with closing(conn.cursor()) as cursor:
        cursor.execute(sql, params)


def execute_many(conn: sqlite3.Connection, sql: str, rows: Iterable[Sequence[SQLValue]]) -> None:
    """Consume bulk input lazily; use inside transaction() for atomic writes."""
    with closing(conn.cursor()) as cursor:
        cursor.executemany(sql, rows)


@contextmanager
def query[T: BaseModel](
    conn: sqlite3.Connection, model: type[T], sql: str, params: Sequence[SQLValue] = ()
) -> Generator[Iterator[T]]:
    """Stream validated rows within an explicit cursor lifetime.

    The iterator and cursor close on context exit, including early breaks,
    validation failures, and consumer exceptions. This scope does not commit
    writes; enclose statements such as INSERT RETURNING in transaction().
    """
    with closing(conn.cursor()) as cursor:
        cursor.execute(sql, params)
        with closing(model.model_validate(dict(row)) for row in cursor) as rows:
            yield rows


def query_rows[T: BaseModel](
    conn: sqlite3.Connection, model: type[T], sql: str, params: Sequence[SQLValue] = ()
) -> list[T]:
    """Validate SQLite's dynamically typed rows exactly once at the boundary.

    Callers must bound large queries with LIMIT; cursors close before returning.
    """
    with query(conn, model, sql, params) as rows:
        return list(rows)
