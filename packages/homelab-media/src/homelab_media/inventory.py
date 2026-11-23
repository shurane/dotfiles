"""In-memory SQLite inventory and size/resolution querying for Jellyfin media."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from rich.markup import escape

from homelab_media.renderer import format_bytes, print_section_header

if TYPE_CHECKING:
    from rich.console import Console


def _resolution_label(height: int) -> str:
    if height >= 2160:
        return "2160p"
    if height >= 1080:
        return "1080p"
    if height >= 720:
        return "720p"
    return "SD" if height > 0 else "unknown"


def _extract_row(item: dict[str, Any]) -> tuple[str, str, int | None, int | None, int, int, int, str, str, str]:
    item_type = item.get("Type")
    kind = "tv" if item_type == "Episode" else "movie"
    title = str(item.get("SeriesName") or item.get("Name") or "Unknown")
    season = item.get("ParentIndexNumber") if kind == "tv" else None
    episode = item.get("IndexNumber") if kind == "tv" else None

    sources = item.get("MediaSources") or []
    src = sources[0] if sources else {}
    size_bytes = int(src.get("Size") or 0)

    video_stream = next(
        (s for s in (src.get("MediaStreams") or []) if s.get("Type") == "Video"),
        {},
    )
    width = int(video_stream.get("Width") or 0)
    height = int(video_stream.get("Height") or 0)
    codec = str(video_stream.get("Codec") or "")
    path = str(item.get("Path") or src.get("Path") or "")
    return (kind, title, season, episode, size_bytes, width, height, _resolution_label(height), codec, path)


def build_inventory_db(items: list[dict[str, Any]]) -> sqlite3.Connection:
    """Load Jellyfin Movie/Episode items into an in-memory SQLite `items` table."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE items (
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            season INTEGER,
            episode INTEGER,
            size_bytes INTEGER NOT NULL,
            width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            resolution TEXT NOT NULL,
            codec TEXT NOT NULL,
            path TEXT NOT NULL
        )
        """
    )
    conn.executemany(
        "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [_extract_row(it) for it in items],
    )
    return conn


def run_sql_query(conn: sqlite3.Connection, sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Execute a read-only SQL query against the in-memory inventory DB."""
    cur = conn.execute(sql)
    cols = [d[0] for d in (cur.description or [])]
    return cols, [tuple(row) for row in cur.fetchall()]


def render_inventory_summary(conn: sqlite3.Connection, console: Console, *, limit: int = 10) -> None:
    """Print largest overall, largest shows, largest movies, and resolution breakdown."""
    total_bytes, total_count = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0), COUNT(*) FROM items"
    ).fetchone()
    console.print(
        f"[bold blue]homelab-media inventory[/bold blue] · "
        f"Files: [cyan]{total_count}[/cyan] | Total: [bold green]{format_bytes(total_bytes)}[/bold green]"
    )

    queries = [
        (
            f"Top {limit} Largest Overall",
            "bold cyan",
            ("SELECT kind, title, COUNT(*) AS files, SUM(size_bytes) AS bytes, "
            "MAX(resolution) AS res FROM items GROUP BY kind, title ORDER BY bytes DESC LIMIT ?"),
            (limit,),
        ),
        (
            f"Top {limit} Largest Shows",
            "bold yellow",
            ("SELECT title, COUNT(*) AS eps, SUM(size_bytes) AS bytes, "
            "MAX(resolution) AS res FROM items WHERE kind = 'tv' GROUP BY title ORDER BY bytes DESC LIMIT ?"),
            (limit,),
        ),
        (
            f"Top {limit} Largest Movies",
            "bold magenta",
            ("SELECT title, size_bytes AS bytes, resolution AS res, codec "
            "FROM items WHERE kind = 'movie' ORDER BY bytes DESC LIMIT ?"),
            (limit,),
        ),
        (
            "By Resolution",
            "bold green",
            ("SELECT resolution, COUNT(*) AS files, SUM(size_bytes) AS bytes "
            "FROM items GROUP BY resolution ORDER BY bytes DESC"),
            (),
        ),
    ]

    for heading, style, sql, params in queries:
        print_section_header(console, heading, style=style)
        cur = conn.execute(sql, params)
        cols = [d[0] for d in (cur.description or [])]
        for row in cur.fetchall():
            parts = [
                f"[white]{format_bytes(val)}[/white]" if col == "bytes" else escape(str(val))
                for col, val in zip(cols, row, strict=True)
            ]
            console.print(" / ".join(parts), soft_wrap=True, highlight=False)
