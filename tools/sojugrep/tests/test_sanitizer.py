"""Unit tests for FTS5 query sanitizer."""

from __future__ import annotations

import sqlite3

from sojugrep.sanitizer import sanitize_fts5_query


def test_sanitize_basic_words() -> None:
    assert sanitize_fts5_query("hello world") == "hello world"
    assert sanitize_fts5_query("python") == "python"


def test_sanitize_quotes() -> None:
    assert sanitize_fts5_query('"exact phrase"') == '"exact phrase"'
    # Unclosed quotes
    assert sanitize_fts5_query('"unclosed phrase') == '"unclosed phrase"'


def test_sanitize_special_punctuation() -> None:
    assert sanitize_fts5_query("c++") == '"c++"'
    assert sanitize_fts5_query("https://example.com/test") == '"https://example.com/test"'
    assert sanitize_fts5_query("user:admin") == '"user:admin"'


def test_sanitize_wildcards() -> None:
    assert sanitize_fts5_query("python*") == "python*"
    # Leading wildcard stripped
    assert sanitize_fts5_query("*python") == "python"


def test_sanitize_boolean_operators() -> None:
    assert sanitize_fts5_query("foo AND bar") == "foo AND bar"
    assert sanitize_fts5_query("foo OR bar") == "foo OR bar"
    assert sanitize_fts5_query("foo AND NOT bar") == "foo NOT bar"
    # Dangling operators pruned
    assert sanitize_fts5_query("foo AND") == "foo"
    assert sanitize_fts5_query("AND foo") == "foo"
    assert sanitize_fts5_query("OR") == ""


def test_sanitize_parentheses() -> None:
    assert sanitize_fts5_query("(foo OR bar)") == "( foo OR bar )"
    assert sanitize_fts5_query("(foo OR bar") == "( foo OR bar )"


def test_fts5_parser_validity_on_edge_cases() -> None:
    """Verify that sanitized queries never crash SQLite's FTS5 MATCH parser."""
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
