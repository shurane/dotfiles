"""Tests for in-memory SQLite database, views, and custom functions."""

from bitwarden_extras.db import build_sqlite_db, execute_sql
from bitwarden_extras.models import SanitizedItem


def test_sqlite_in_memory_db_and_vault_view():
    items = [
        SanitizedItem(
            name="Work Account",
            folder="Work",
            type="Login",
            username="alice",
            domains=["work.com"],
            notes="some notes",
            favorite=True,
            id="id-1",
            revision_date="2026-10-05T22:00:00Z",
            creation_date="2026-01-01T00:00:00Z",
        ),
        SanitizedItem(
            name=None,
            folder=None,
            type="Login",
            username="bob",
            domains=[],
            notes=None,
            favorite=False,
            id="id-2",
        ),
    ]

    conn = build_sqlite_db(items)
    cur = conn.cursor()

    # Check total items and column population
    cur.execute("SELECT count(*), count(revision_date) FROM items")
    assert cur.fetchone() == (2, 1)

    # Check helper flags in 'vault' view
    cur.execute("SELECT is_unfiled, is_unnamed FROM vault WHERE id = 'id-1'")
    assert cur.fetchone() == (0, 0)

    cur.execute("SELECT is_unfiled, is_unnamed FROM vault WHERE id = 'id-2'")
    assert cur.fetchone() == (1, 1)

    # Check custom SQLite functions
    cur.execute("SELECT is_blank(''), is_blank('\x10'), is_blank('hello')")
    assert cur.fetchone() == (1, 1, 0)

    cur.execute("SELECT strip(' \x10 test \x10 ')")
    assert cur.fetchone() == ("test",)


def test_execute_sql():
    items = [
        SanitizedItem(name="Test 1", folder="Personal", type="Login"),
        SanitizedItem(name="Test 2", folder="Personal", type="Login"),
    ]
    conn = build_sqlite_db(items)
    col_names, rows = execute_sql(conn, "SELECT name, folder FROM items WHERE folder = 'Personal'")
    assert col_names == ["name", "folder"]
    assert len(rows) == 2
