"""Tests for sojugrep CLI and search execution."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from sojugrep.cli import execute_search, print_result
from sojugrep.models import SearchQuery, SearchResult


def test_search_query_validation() -> None:
    q = SearchQuery(pattern="hello", limit=50)
    assert q.pattern == "hello"
    assert q.limit == 50
    assert q.target is None

    with pytest.raises(ValidationError):
        SearchQuery(pattern="")


def test_execute_search_mock_db(tmp_path: Path) -> None:
    db_file = tmp_path / "soju.db"
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    cursor.execute("CREATE TABLE networks (id INTEGER PRIMARY KEY, name TEXT);")
    cursor.execute("CREATE TABLE channels (id INTEGER PRIMARY KEY, name TEXT);")
    cursor.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, nick TEXT);")
    cursor.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            time TEXT,
            network_id INTEGER,
            target_id INTEGER,
            sender TEXT,
            text TEXT
        );
    """)
    cursor.execute("""
        CREATE VIRTUAL TABLE MessageFTS USING fts5(
            sender,
            target,
            body,
            tokenize='porter unicode61'
        );
    """)

    cursor.execute("INSERT INTO networks VALUES (1, 'libera');")
    cursor.execute("INSERT INTO channels VALUES (10, '#test');")
    cursor.execute(
        "INSERT INTO messages VALUES (1, '2026-09-30T12:00:00Z', 1, 10, 'alice', 'hello world');"
    )
    cursor.execute(
        "INSERT INTO MessageFTS (rowid, sender, target, body) "
        "VALUES (1, 'alice', '#test', 'hello world');"
    )
    conn.commit()
    conn.close()

    query = SearchQuery(pattern="world", db_path=db_file)
    results = execute_search(query)
    assert len(results) == 1
    assert results[0].sender_nick == "alice"
    assert results[0].network == "libera"
    assert results[0].target == "#test"


def test_print_result(capsys: pytest.CaptureFixture[str]) -> None:
    res = SearchResult(
        message_id=1,
        timestamp_str="2026-09-30T12:00:00Z",
        network="libera",
        target="#test",
        sender_nick="alice",
        text="hello \x01world\x02 test",
    )
    print_result(res)
    captured = capsys.readouterr().out
    assert "alice" in captured
    assert "libera" in captured
    assert "#test" in captured
