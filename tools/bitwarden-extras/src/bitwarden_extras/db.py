"""In-memory SQLite database engine and interactive REPL."""

import json
import sqlite3
from collections.abc import Callable, Sequence
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from bitwarden_extras.models import SanitizedItem, clean_str


def build_sqlite_db(items: Sequence[SanitizedItem | dict[str, Any]]) -> sqlite3.Connection:
    """Construct an in-memory SQLite database populated with sanitized vault items."""
    conn = sqlite3.connect(":memory:")
    conn.create_function("strip", 1, lambda s: clean_str(s) if s is not None else None)
    conn.create_function("is_blank", 1, lambda s: 1 if not clean_str(s) else 0)

    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE items (
            name TEXT,
            folder TEXT,
            type TEXT,
            username TEXT,
            domains TEXT,
            notes TEXT,
            favorite INTEGER,
            id TEXT,
            revision_date TEXT,
            creation_date TEXT,
            raw_json TEXT
        )
    """)

    for it in items:
        if isinstance(it, SanitizedItem):
            name = it.name
            folder = it.folder
            itype = it.type
            username = it.username
            domains = it.domains
            notes = it.notes
            fav = 1 if it.favorite else 0
            iid = it.id
            rev = it.revision_date
            created = it.creation_date
            raw_json_str = it.model_dump_json()
        else:
            name = it.get("name")
            folder = it.get("folder")
            itype = it.get("type", "")
            username = it.get("username")
            domains = it.get("domains", [])
            notes = it.get("notes")
            fav = 1 if it.get("favorite") else 0
            iid = it.get("id")
            rev = it.get("revision_date")
            created = it.get("creation_date")
            raw_json_str = json.dumps(it)

        dom_str = ", ".join(domains) if isinstance(domains, list) else str(domains or "")

        cur.execute(
            "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                folder,
                itype,
                username,
                dom_str,
                notes,
                fav,
                iid,
                rev,
                created,
                raw_json_str,
            ),
        )

    cur.execute("""
        CREATE VIEW vault AS
        SELECT
            *,
            (folder IS NULL) AS is_unfiled,
            (name IS NULL OR is_blank(name)) AS is_unnamed
        FROM items
    """)
    conn.commit()
    return conn


def execute_sql(
    conn: sqlite3.Connection,
    sql: str,
    console: Console | None = None,
) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Execute SQL against the connection and optionally print a formatted Rich table."""
    cur = conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    col_names = [d[0] for d in cur.description] if cur.description else []

    if console is not None:
        if not col_names:
            console.print("[dim]Query executed successfully (no rows returned).[/dim]\n")
            return col_names, rows

        table = Table(show_header=True, header_style="bold cyan", show_lines=True)
        for col in col_names:
            if col.lower() in ("notes", "raw_json"):
                table.add_column(col, overflow="fold", max_width=60)
            else:
                table.add_column(col, style="bold" if col.lower() in ("name", "folder") else None)

        for row in rows:
            table.add_row(*(str(val) if val is not None else "[dim]NULL[/dim]" for val in row))

        console.print(table)
        console.print(f"[dim]{len(rows)} row(s) returned.[/dim]\n")

    return col_names, rows


def run_repl(
    conn: sqlite3.Connection,
    console: Console,
    refresh_callback: Callable[[], sqlite3.Connection | None] | None = None,
) -> None:
    """Run an interactive SQLite REPL session."""
    console.print(
        Panel(
            "[bold green]Bitwarden In-Memory SQLite REPL[/bold green]\n"
            "Tables/Views: [cyan]vault[/cyan], [cyan]items[/cyan]\n"
            "Columns: [dim]name, folder, type, username, domains, notes, favorite, id, revision_date, creation_date, raw_json[/dim]\n"
            "Helper Flags in 'vault': [dim]is_unfiled (1/0), is_unnamed (1/0)[/dim]\n"
            "Commands: [bold cyan].sync[/bold cyan] (refresh from cloud), [bold cyan].schema[/bold cyan], [bold cyan]exit[/bold cyan], [bold cyan]quit[/bold cyan]",
            border_style="cyan",
        )
    )

    current_conn = conn
    while True:
        try:
            query_str = console.input("[bold cyan]vault>[/bold cyan] ").strip()
            if not query_str:
                continue
            if query_str.lower() in ("exit", "quit", "q", ".exit", ".quit"):
                break
            if query_str.lower() in (".sync", "sync"):
                if refresh_callback is None:
                    console.print("[yellow]Cannot sync when querying a local file.[/yellow]\n")
                    continue
                new_conn = refresh_callback()
                if new_conn:
                    current_conn = new_conn
                continue
            if query_str.lower() in (".schema", "schema"):
                console.print(
                    "[dim]CREATE TABLE items (name, folder, type, username, domains, notes, favorite, id, revision_date, creation_date, raw_json);\n"
                    "CREATE VIEW vault AS SELECT *, (folder IS NULL) AS is_unfiled, (name IS NULL OR is_blank(name)) AS is_unnamed FROM items;[/dim]\n"
                )
                continue
            execute_sql(current_conn, query_str, console=console)
        except KeyboardInterrupt, EOFError:
            console.print("\n[dim]Exiting...[/dim]")
            break
        except sqlite3.Error as e:
            console.print(f"[bold red]SQL Error:[/bold red] {e}\n")
