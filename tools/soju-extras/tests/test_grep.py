"""Search semantics and CLI errors with the real FTS table and triggers."""

from pathlib import Path

import pytest

from soju_extras.grep.cli import execute_search, main
from soju_extras.models import SearchQuery
from tests.conftest import add_message


@pytest.mark.parametrize(
    "pattern",
    [
        "foo;bar",
        "foo[bar]",
        "(NOT foo)",
        "foo AND (bar OR)",
        "https://example.com",
        '"hello"',
        "c++",
    ],
)
def test_literal_search_accepts_punctuation(soju_db: Path, pattern: str) -> None:
    add_message(soju_db, pattern)
    assert len(execute_search(SearchQuery(pattern=pattern, db_path=soju_db))) == 1


def test_search_filters_order_and_limit(soju_db: Path) -> None:
    add_message(soju_db, "hello first")
    add_message(soju_db, "hello second")
    query = SearchQuery(
        pattern="hello", target="#python", network="libera", limit=1, db_path=soju_db
    )
    assert "second" in execute_search(query)[0].text
    assert execute_search(query.model_copy(update={"target": "#other"})) == []


def test_cli_exit_codes_and_redirected_output(
    soju_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_message(soju_db)
    assert main(["world", "-d", str(soju_db)]) == 0
    output = capsys.readouterr().out
    assert "hello world" in output
    assert "\x1b" not in output
    assert main(["absent", "-d", str(soju_db)]) == 1
    assert main(["world", "-d", str(tmp_path / "missing")]) == 2
    assert main(["world", "--limit", "0", "-d", str(soju_db)]) == 2
    assert main(["foo AND (", "--raw-fts", "-d", str(soju_db)]) == 2


def test_raw_boolean_search(soju_db: Path) -> None:
    add_message(soju_db, "hello world")
    add_message(soju_db, "hello again")
    results = execute_search(SearchQuery(pattern="hello NOT world", raw_fts=True, db_path=soju_db))
    assert len(results) == 1
    assert "again" in results[0].text
