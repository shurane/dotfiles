"""Command line interface and search execution for sojugrep."""

from __future__ import annotations

import argparse
import sqlite3
import sys

from soju.db import open_soju_db
from soju.grep.sanitizer import sanitize_fts5_query
from soju.models import SearchQuery, SearchResult

# ANSI terminal formatting
RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
MAGENTA = "\x1b[35m"
CYAN = "\x1b[36m"
GREEN = "\x1b[32m"
HIGHLIGHT = "\x1b[1;31m"  # Bold red for matched terms


def execute_search(query: SearchQuery) -> list[SearchResult]:
    """Execute FTS5 search query against Soju SQLite database using sqlite-utils."""
    sanitized = sanitize_fts5_query(query.pattern)
    if not sanitized:
        print(f"Error: Invalid or empty search pattern: {query.pattern!r}", file=sys.stderr)
        return []

    if not query.db_path.exists():
        print(f"Error: Soju database not found at {query.db_path}", file=sys.stderr)
        return []

    sql = """
        SELECT
            m.id,
            m.time,
            n.name AS network,
            t.target AS target,
            COALESCE(m.sender, '') AS sender,
            highlight(MessageFTS, 2, '\x01', '\x02') AS highlighted_text
        FROM MessageFTS fts
        JOIN Message m ON fts.rowid = m.id
        JOIN MessageTarget t ON m.target = t.id
        JOIN Network n ON t.network = n.id
        WHERE MessageFTS MATCH ?
    """
    params: list[str | int] = [sanitized]

    if query.target:
        sql += " AND LOWER(t.target) = LOWER(?)"
        params.append(query.target)

    if query.network:
        sql += " AND LOWER(n.name) = LOWER(?)"
        params.append(query.network)

    sql += " ORDER BY m.time DESC LIMIT ?"
    params.append(query.limit)

    results: list[SearchResult] = []
    try:
        with open_soju_db(query.db_path, readonly=True) as db:
            for row in db.query(sql, params):
                results.append(
                    SearchResult(
                        message_id=row["id"],
                        timestamp_str=str(row["time"]),
                        network=row["network"] or "",
                        target=row["target"] or "",
                        sender_nick=row["sender"] or "",
                        text=row["highlighted_text"] or "",
                    )
                )
    except sqlite3.OperationalError as e:
        print(f"FTS5 Query Error ({e}) for query: {sanitized}", file=sys.stderr)
        return []

    return results


def print_result(res: SearchResult) -> None:
    """Format and print a single search result with ANSI color highlighting."""
    formatted_text = res.text.replace("\x01", HIGHLIGHT).replace("\x02", RESET)
    time_display = f"{DIM}{res.timestamp_str[:19]}{RESET}"
    net_display = f"{MAGENTA}{res.network}{RESET}"
    target_display = f"{CYAN}{res.target}{RESET}"
    sender_display = f"{GREEN}<{res.sender_nick}>{RESET}" if res.sender_nick else ""

    print(f"{time_display} [{net_display}/{target_display}] {sender_display} {formatted_text}")


def main() -> int:
    """CLI entrypoint for sojugrep."""
    parser = argparse.ArgumentParser(
        prog="sojugrep",
        description="Instant FTS5 search across Soju SQLite IRC backlog.",
    )
    parser.add_argument(
        "pattern",
        help="Search query or FTS5 phrase (e.g. 'error', 'systemd AND timer', 'c++')",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Optional channel or nick (e.g. #selfhosted)",
    )
    parser.add_argument(
        "-n",
        "--network",
        default=None,
        help="Limit search to specific IRC network (e.g. libera, oftc)",
    )
    parser.add_argument(
        "-d",
        "--db-path",
        default="/var/lib/soju/main.db",
        help="Path to Soju SQLite DB (default: /var/lib/soju/main.db)",
    )
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=100,
        help="Max results to display (default: 100)",
    )

    args = parser.parse_args()

    query = SearchQuery(
        pattern=args.pattern,
        target=args.target,
        network=args.network,
        db_path=args.db_path,
        limit=args.limit,
    )

    results = execute_search(query)
    for res in reversed(results):
        print_result(res)

    return 0


if __name__ == "__main__":
    sys.exit(main())
