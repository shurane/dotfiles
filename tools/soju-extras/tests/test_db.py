"""Connection/cursor lifetime and transaction behavior against SQLite."""

import sqlite3
from pathlib import Path

import pytest

from soju_extras.db import execute, open_soju_db, query_rows, transaction
from soju_extras.resolver import IDRow


def test_connection_closed_on_exception(soju_db: Path) -> None:
    with pytest.raises(RuntimeError), open_soju_db(soju_db) as db:
        raise RuntimeError("stop")
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute("SELECT 1")


def test_readonly_and_missing_db(soju_db: Path, tmp_path: Path) -> None:
    with open_soju_db(soju_db, readonly=True) as db, pytest.raises(sqlite3.OperationalError):
        execute(db, "DELETE FROM User")
    with pytest.raises(sqlite3.OperationalError), open_soju_db(tmp_path / "missing.db"):
        pass
    assert not (tmp_path / "missing.db").exists()


def test_transaction_commits_and_rolls_back(soju_db: Path) -> None:
    with open_soju_db(soju_db) as db:
        with transaction(db):
            execute(db, "INSERT INTO MessageTarget(network, target) VALUES (1, '#committed')")
        with pytest.raises(KeyboardInterrupt), transaction(db):
            execute(db, "INSERT INTO MessageTarget(network, target) VALUES (1, '#rolled-back')")
            raise KeyboardInterrupt
    with open_soju_db(soju_db) as db:
        assert query_rows(db, IDRow, "SELECT id FROM MessageTarget WHERE target = '#committed'")
        assert not query_rows(
            db, IDRow, "SELECT id FROM MessageTarget WHERE target = '#rolled-back'"
        )


def test_uri_filename(soju_db: Path) -> None:
    renamed = soju_db.with_name("soju?#%.db")
    soju_db.rename(renamed)
    with open_soju_db(renamed, readonly=True) as db:
        assert query_rows(db, IDRow, "SELECT id FROM User")[0].id == 1


def test_query_streams_and_releases_lock_on_early_exit(soju_db: Path) -> None:
    from soju_extras.db import query

    with open_soju_db(soju_db) as db:
        execute(db, "CREATE TEMP TABLE stream_test(id)")
        execute(db, "INSERT INTO stream_test VALUES (1), (2), ('invalid')")
        with query(db, IDRow, "SELECT id FROM stream_test") as rows:
            assert next(rows).id == 1
            # An unfinished query holds its cursor until the context exits.
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                execute(db, "DROP TABLE stream_test")
        # The unconsumed invalid row was never validated, and the iterator is closed.
        with pytest.raises(StopIteration):
            next(rows)
        execute(db, "DROP TABLE stream_test")


def test_query_validation_failure_releases_lock(soju_db: Path) -> None:
    from pydantic import ValidationError

    from soju_extras.db import query

    with open_soju_db(soju_db) as db:
        execute(db, "CREATE TEMP TABLE stream_test(id)")
        execute(db, "INSERT INTO stream_test VALUES ('invalid'), (2)")
        with pytest.raises(ValidationError), query(db, IDRow, "SELECT id FROM stream_test") as rows:
            next(rows)
        execute(db, "DROP TABLE stream_test")


def test_query_consumer_exception_releases_lock(soju_db: Path) -> None:
    from soju_extras.db import query

    with open_soju_db(soju_db) as db:
        execute(db, "CREATE TEMP TABLE stream_test(id)")
        execute(db, "INSERT INTO stream_test VALUES (1), (2), (3)")
        with (
            pytest.raises(KeyboardInterrupt),
            query(db, IDRow, "SELECT id FROM stream_test") as rows,
        ):
            next(rows)
            raise KeyboardInterrupt
        execute(db, "DROP TABLE stream_test")


def test_failed_bulk_input_rolls_back(soju_db: Path) -> None:
    from collections.abc import Iterator

    from soju_extras.db import execute_many

    def broken_input() -> Iterator[tuple[int]]:
        yield (1,)
        raise ValueError("failed to parse next row")

    with open_soju_db(soju_db) as db:
        execute(db, "CREATE TEMP TABLE bulk_test(id)")
        with pytest.raises(ValueError, match="parse next row"), transaction(db):
            execute_many(db, "INSERT INTO bulk_test VALUES (?)", broken_input())
        assert query_rows(db, IDRow, "SELECT id FROM bulk_test") == []
        with transaction(db):
            execute_many(db, "INSERT INTO bulk_test VALUES (?)", ((2,), (3,)))
        assert [row.id for row in query_rows(db, IDRow, "SELECT id FROM bulk_test")] == [2, 3]


def test_failed_commit_rolls_back_and_connection_remains_usable(soju_db: Path) -> None:
    with open_soju_db(soju_db) as db:
        execute(db, "CREATE TEMP TABLE parent(id INTEGER PRIMARY KEY)")
        execute(
            db,
            "CREATE TEMP TABLE child(id INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)",
        )
        with pytest.raises(sqlite3.IntegrityError), transaction(db):
            execute(db, "INSERT INTO child VALUES (42)")
        assert not db.in_transaction
        assert query_rows(db, IDRow, "SELECT id FROM child") == []
        with transaction(db):
            execute(db, "INSERT INTO parent VALUES (42)")
            execute(db, "INSERT INTO child VALUES (42)")
        assert query_rows(db, IDRow, "SELECT id FROM child")[0].id == 42


def test_connection_setup_failure_closes_connection(
    soju_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Sequence

    import soju_extras.db as database
    from soju_extras.db import SQLValue

    connections: list[sqlite3.Connection] = []

    def fail_setup(conn: sqlite3.Connection, sql: str, params: Sequence[SQLValue] = ()) -> None:
        connections.append(conn)
        raise sqlite3.OperationalError("setup failed")

    monkeypatch.setattr(database, "execute", fail_setup)
    with pytest.raises(sqlite3.OperationalError, match="setup failed"), open_soju_db(soju_db):
        pass
    with pytest.raises(sqlite3.ProgrammingError):
        connections[0].execute("SELECT 1")


def test_returning_query_does_not_commit_enclosing_transaction(soju_db: Path) -> None:
    from soju_extras.db import query

    with open_soju_db(soju_db) as db:
        with pytest.raises(RuntimeError), transaction(db):
            with query(
                db,
                IDRow,
                "INSERT INTO MessageTarget(network, target) VALUES(1, '#returning') RETURNING id",
            ) as rows:
                assert next(rows).id > 0
            assert db.in_transaction
            raise RuntimeError("consumer failed after query closed")
        assert (
            query_rows(db, IDRow, "SELECT id FROM MessageTarget WHERE target = '#returning'") == []
        )
