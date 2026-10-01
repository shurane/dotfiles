"""Search Soju messages with validated rows and optional raw FTS5 syntax."""

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

from rich.console import Console
from rich.text import Text

from soju_extras.db import SQLValue, open_soju_db, query_rows
from soju_extras.grep.sanitizer import sanitize_fts5_query
from soju_extras.models import SearchQuery, SearchResult


def execute_search(query: SearchQuery) -> list[SearchResult]:
    sql = """
        SELECT m.id AS message_id, m.time AS timestamp_str,
               coalesce(nullif(n.name, ''), n.addr) AS network,
               t.target, m.sender AS sender_nick,
               highlight(MessageFTS, 0, '\x01', '\x02') AS text
        FROM MessageFTS fts
        JOIN Message m ON fts.rowid = m.id
        JOIN MessageTarget t ON m.target = t.id
        JOIN Network n ON t.network = n.id
        WHERE MessageFTS MATCH ?
    """
    params: list[SQLValue] = [
        query.pattern if query.raw_fts else sanitize_fts5_query(query.pattern)
    ]
    if query.target:
        sql += " AND t.target = ? COLLATE NOCASE"
        params.append(query.target)
    if query.network:
        sql += " AND (n.name = ? COLLATE NOCASE OR n.addr = ?)"
        params.extend((query.network, query.network))
    sql += " ORDER BY m.time DESC, m.id DESC LIMIT ?"
    params.append(query.limit)
    with open_soju_db(query.db_path, readonly=True) as db:
        return query_rows(db, SearchResult, sql, params)


def print_result(res: SearchResult) -> None:
    output = Text(f"{res.timestamp_str[:23]} ", style="dim")
    output.append(f"[{res.network}/{res.target}] ", style="cyan")
    output.append(f"<{res.sender_nick}> ", style="green")
    # Rich controls terminal escapes and disables color when stdout is redirected.
    for index, part in enumerate(res.text.split("\x01")):
        if index and "\x02" in part:
            match, rest = part.split("\x02", 1)
            output.append(match, style="bold red")
            output.append(rest)
        else:
            output.append(part)
    Console().print(output, soft_wrap=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pattern", help="Literal search terms (use --raw-fts for operators)")
    parser.add_argument("target", nargs="?")
    parser.add_argument("-n", "--network")
    parser.add_argument("-d", "--db-path", type=Path, default=Path("/var/lib/soju/main.db"))
    parser.add_argument("-l", "--limit", type=int, default=100)
    parser.add_argument(
        "--raw-fts", action="store_true", help="Pass FTS5 syntax to SQLite unchanged"
    )
    try:
        query = SearchQuery.model_validate(vars(parser.parse_args(argv)))
        results = execute_search(query)
        for result in reversed(results):
            print_result(result)
        return 0 if results else 1
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
