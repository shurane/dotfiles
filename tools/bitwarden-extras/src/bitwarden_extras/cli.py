"""Command line interface for Bitwarden Extras."""

import json
import sqlite3
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from bitwarden_extras.client import (
    BitwardenClient,
    BitwardenError,
    CliNotFoundError,
    ServeConnectionError,
    VaultLockedError,
    VaultUnauthenticatedError,
)
from bitwarden_extras.db import build_sqlite_db, execute_sql, run_repl
from bitwarden_extras.models import OutputFormat, clean_str, process_vault

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    name="bw-vault",
    help="Extract safe metadata and query your Bitwarden vault with In-Memory SQLite.",
    add_completion=False,
    no_args_is_help=False,
)

client = BitwardenClient()


@contextmanager
def handle_client_errors() -> Generator[None]:
    """Catch Bitwarden client errors and render friendly UI messages."""
    try:
        yield
    except (
        VaultLockedError,
        VaultUnauthenticatedError,
        ServeConnectionError,
        CliNotFoundError,
    ) as e:
        err_console.print(f"\n[bold red]Error:[/bold red] {e}\n")
        sys.exit(1)
    except BitwardenError as e:
        err_console.print(f"[bold red]Bitwarden Error:[/bold red] {e}")
        sys.exit(1)


@app.command(
    name="export", help="Extract sanitized metadata to YAML or JSON (passwords strictly omitted)."
)
def export_cmd(
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Output format: yaml or json."),
    ] = OutputFormat.YAML,
    output_path: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Custom output file path. Defaults to bitwarden_metadata.<format>",
        ),
    ] = None,
    include_notes: Annotated[
        bool,
        typer.Option(
            "--include-notes",
            help="Include freeform notes (disabled by default for secret safety).",
        ),
    ] = False,
    server: Annotated[
        str | None,
        typer.Option(
            "--server",
            "-s",
            help="Custom bw serve URL (e.g. http://localhost:8087 or http://[::1]:8087).",
        ),
    ] = None,
    sync: Annotated[
        bool,
        typer.Option("--sync", help="Force sync with Bitwarden cloud before exporting."),
    ] = False,
    no_sync: Annotated[
        bool,
        typer.Option(
            "--no-sync", help="Skip automatic cloud sync and export from local cache immediately."
        ),
    ] = False,
) -> None:
    with handle_client_errors():
        folders_data, items_data, info = client.fetch_live_data(
            server_url=server, sync=sync, no_sync=no_sync
        )
    console.print(f"[dim]{info}...[/dim]")

    metadata = process_vault(folders_data, items_data, include_notes=include_notes)

    if output_path is None:
        ext = "yaml" if output_format == OutputFormat.YAML else "json"
        output_path = Path.cwd() / f"bitwarden_metadata.{ext}"

    # Serialize items cleanly using Pydantic model_dump
    items_dump = [
        it.model_dump(
            exclude_none=True,
            exclude={"notes"} if not include_notes else None,
        )
        for it in metadata.items
    ]

    output_dict = {
        "folders": metadata.folders,
        "total_items": metadata.total_items,
        "items": items_dump,
    }

    with (
        console.status(f"[bold cyan]Writing {output_path.name}...[/bold cyan]", spinner="dots"),
        output_path.open("w", encoding="utf-8") as f,
    ):
        if output_format == OutputFormat.YAML:
            yaml.safe_dump(
                output_dict, f, sort_keys=False, default_flow_style=False, allow_unicode=True
            )
        else:
            json.dump(output_dict, f, indent=2)

    console.print(
        f"\n[bold green]✓ Success![/bold green] Extracted metadata for [bold]{metadata.total_items}[/bold] items across [bold]{len(metadata.folders)}[/bold] folders."
    )
    console.print(f"[dim]Saved to: {output_path}[/dim]")
    if include_notes:
        console.print("[yellow]Notice: Notes are included in this export.[/yellow]")
    else:
        console.print(
            "[dim green]Verification: NO passwords, TOTP keys, notes, or custom fields are present in this file.[/dim green]"
        )


@app.command(name="sync", help="Sync local Bitwarden cache with Bitwarden cloud servers.")
def sync_cmd(
    server: Annotated[
        str | None,
        typer.Option("--server", "-s", help="Custom bw serve URL (e.g. http://localhost:8087)."),
    ] = None,
) -> None:
    with handle_client_errors():
        with console.status("[cyan]Syncing vault with Bitwarden cloud...[/cyan]", spinner="dots"):
            ok = client.sync(server_url=server)
        if ok:
            console.print(
                "[bold green]✓ Vault synced successfully with Bitwarden cloud![/bold green]"
            )
        else:
            err_console.print("[bold red]Error:[/bold red] Vault sync failed.")
            sys.exit(1)


@app.command(
    name="query",
    help="Execute in-memory SQL queries against your vault (table: 'items' or 'vault').",
)
def query_cmd(
    sql: Annotated[
        str | None,
        typer.Argument(help="SQL query string to run. If omitted, launches an interactive REPL."),
    ] = None,
    file_path: Annotated[
        Path | None,
        typer.Option(
            "--file",
            "-f",
            help="Query a specific metadata file (YAML or JSON) instead of live Bitwarden.",
        ),
    ] = None,
    server: Annotated[
        str | None,
        typer.Option(
            "--server",
            "-s",
            help="Custom bw serve URL (e.g. http://localhost:8087 or http://[::1]:8087).",
        ),
    ] = None,
    sync: Annotated[
        bool,
        typer.Option("--sync", help="Force sync with Bitwarden cloud before querying."),
    ] = False,
    no_sync: Annotated[
        bool,
        typer.Option(
            "--no-sync", help="Skip automatic cloud sync and query local cache immediately."
        ),
    ] = False,
) -> None:
    items_to_load: list[Any] = []

    if file_path is not None:
        if not file_path.exists():
            err_console.print(f"[bold red]Error:[/bold red] File not found: {file_path}")
            sys.exit(1)
        console.print(f"[dim]Querying {file_path.name}...[/dim]")
        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) if file_path.suffix in (".yaml", ".yml") else json.load(f)
            items_to_load = data.get("items", [])
    else:
        with handle_client_errors():
            folders_data, items_data, info = client.fetch_live_data(
                server_url=server, sync=sync, no_sync=no_sync
            )
        console.print(f"[dim]{info}...[/dim]")
        meta = process_vault(folders_data, items_data, include_notes=True)
        items_to_load = meta.items

    conn = build_sqlite_db(items_to_load)

    if sql:
        try:
            execute_sql(conn, sql, console=console)
        except Exception as e:
            err_console.print(f"[bold red]SQL Error:[/bold red] {e}")
    else:

        def refresh_db() -> sqlite3.Connection | None:
            try:
                client.sync(server_url=server)
                f_data, i_data, _ = client.fetch_live_data(server_url=server, no_sync=True)
                new_meta = process_vault(f_data, i_data, include_notes=True)
                new_conn = build_sqlite_db(new_meta.items)
                console.print(
                    f"[bold green]✓ REPL database refreshed with latest cloud data ({new_meta.total_items} items).[/bold green]\n"
                )
                return new_conn
            except Exception as ex:
                err_console.print(f"[bold red]Refresh Error:[/bold red] {ex}\n")
                return None

        run_repl(conn, console=console, refresh_callback=refresh_db if file_path is None else None)


@app.command(
    name="clean-blank-notes", help="Wipe phantom/whitespace notes across vault items via bw serve."
)
def clean_blank_notes_cmd(
    server: Annotated[
        str | None,
        typer.Option(
            "--server",
            "-s",
            help="Custom bw serve URL (e.g. http://localhost:8087 or http://[::1]:8087).",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="List items that would be modified without making any changes."
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt and proceed with cleanup."),
    ] = False,
) -> None:
    with handle_client_errors():
        active_url = client.get_active_serve_url(server)

    if not active_url:
        err_console.print(
            "\n[bold red]Error:[/bold red] 'clean-blank-notes' requires 'bw serve' to be running."
        )
        sys.exit(1)

    with console.status("[cyan]Syncing vault before cleanup...[/cyan]", spinner="dots"):
        client.sync(server_url=active_url)

    items_res = client.http_request(f"{active_url}/list/object/items", timeout=10.0)
    items_data: list[dict[str, Any]] = (items_res or {}).get("data", {}).get("data", [])

    blank_items = client.find_blank_note_items(items_data)

    if not blank_items:
        console.print("[bold green]✓ No blank or phantom notes found in vault![/bold green]")
        return

    table = Table(
        title=f"Items with Blank/Phantom Notes ({len(blank_items)})",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Item Name", style="bold")
    table.add_column("Current Note Repr", style="dim")
    table.add_column("Length", justify="right")
    for it in blank_items:
        table.add_row(
            it.get("name") or "[dim]Unnamed[/dim]",
            repr(it.get("notes")),
            str(len(it.get("notes", ""))),
        )
    console.print(table)

    if dry_run:
        console.print(
            f"\n[yellow]Dry-run mode: {len(blank_items)} items would have their notes set to NULL.[/yellow]"
        )
        return

    if not yes:
        confirm = typer.confirm(
            f"Are you sure you want to set notes to NULL for these {len(blank_items)} items?"
        )
        if not confirm:
            console.print("[dim]Operation cancelled.[/dim]")
            return

    updated_count = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Clearing blank notes...", total=len(blank_items))
        for it in blank_items:
            item_id = it["id"]
            item_res = client.http_request(f"{active_url}/object/item/{item_id}", timeout=5.0)
            item_obj: dict[str, Any] = (item_res or {}).get("data", {})

            # Critical safety guard: abort if full item could not be retrieved
            if not item_obj or item_obj.get("id") != item_id:
                err_console.print(
                    f"\n[bold red]Warning:[/bold red] Failed to fetch full item object for {item_id}; skipping to prevent data loss."
                )
                progress.advance(task)
                continue

            if clean_str(item_obj.get("notes")):
                progress.advance(task)
                continue

            item_obj["notes"] = None
            put_res = client.http_request(
                f"{active_url}/object/item/{item_id}",
                method="PUT",
                payload=item_obj,
                timeout=5.0,
            )
            if put_res and put_res.get("success"):
                updated_count += 1
            else:
                err_console.print(
                    f"\n[bold red]Warning:[/bold red] Failed to update item {item_id}."
                )
            progress.advance(task)

    with console.status("[cyan]Syncing vault after cleanup...[/cyan]", spinner="dots"):
        client.sync(server_url=active_url)

    console.print(
        f"\n[bold green]✓ Successfully emptied notes for {updated_count} items![/bold green]"
    )


def main() -> None:
    """Entry point with backwards compatibility argument dispatch."""
    if len(sys.argv) > 1 and sys.argv[1] not in (
        "export",
        "query",
        "sync",
        "clean-blank-notes",
        "-h",
        "--help",
    ):
        sys.argv.insert(1, "export")
    app()


if __name__ == "__main__":
    main()
