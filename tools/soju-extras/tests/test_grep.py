"""Tests for sojugrep and FTS5 sanitizer."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import sqlite_utils
from pydantic import ValidationError

from soju_extras.grep.cli import execute_search, print_result
from soju_extras.grep.sanitizer import sanitize_fts5_query
from soju_extras.models import SearchQuery, SearchResult


def test_sanitize_fts5_query_edge_cases() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE test_fts USING fts5(content);")
    conn.execute("INSERT INTO test_fts (content) VALUES ('hello world c++ test');")

    nasty_inputs = [
        "",
        "   ",
        '"',
        '"""',
        "AND",
        "OR NOT",
        "(((",
        ")))",
        "***word***",
        "https://example.com/path?arg=1&val=2",
        "foo:bar",
        "c++ OR (rust AND NOT java",
        "hello 'world'",
    ]

    for raw in nasty_inputs:
        sanitized = sanitize_fts5_query(raw)
        if not sanitized:
            continue
        try:
            cursor = conn.execute("SELECT * FROM test_fts WHERE test_fts MATCH ?", (sanitized,))
            cursor.fetchall()
        except sqlite3.OperationalError as e:
            msg = f"Sanitized query failed in FTS5: {sanitized!r} (from {raw!r}): {e}"
            raise AssertionError(msg) from e


def test_execute_search_mock(tmp_path: Path) -> None:
    db_file = tmp_path / "soju.db"
    db = sqlite_utils.Database(db_file)
    db.table("Network").insert({"id": 1, "name": "libera"})
    db.table("MessageTarget").insert({"id": 10, "network": 1, "target": "#test"})
    db.table("Message").insert(
        {
            "id": 100,
            "target": 10,
            "time": "2026-09-30T12:00:00Z",
            "sender": "alice",
            "text": "hello world",
            "raw": "dummy",
        }
    )
    db.execute(
        "CREATE VIRTUAL TABLE MessageFTS USING fts5(sender, target, body, tokenize='porter unicode61');"
    )
    db.execute(
        "INSERT INTO MessageFTS (rowid, sender, target, body) VALUES (100, 'alice', '#test', 'hello world');"
    )

    query = SearchQuery(pattern="world", db_path=db_file)
    results = execute_search(query)
    assert len(results) == 1
    assert results[0].sender_nick == "alice"
    assert results[0].network == "libera"
    assert results[0].target == "#test"


def test_search_query_validation() -> None:
    with pytest.raises(ValidationError):
        SearchQuery(pattern="")


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
