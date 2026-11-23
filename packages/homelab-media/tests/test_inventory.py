"""Unit tests for in-memory SQLite media inventory."""

from __future__ import annotations

from io import StringIO

from homelab_media.inventory import build_inventory_db, render_inventory_summary, run_sql_query
from rich.console import Console


def test_inventory_db_and_sql_queries() -> None:
    items = [
        {
            "Type": "Movie",
            "Name": "Big Movie",
            "Path": "/mnt/mango/media/movies/Big Movie (2020)/Big Movie (2020).mkv",
            "MediaSources": [
                {
                    "Size": 10 * 1024**3,
                    "MediaStreams": [{"Type": "Video", "Width": 3840, "Height": 2160, "Codec": "hevc"}],
                }
            ],
        },
        {
            "Type": "Episode",
            "SeriesName": "Some Show",
            "ParentIndexNumber": 1,
            "IndexNumber": 1,
            "Path": "/mnt/mango/media/tv/Some Show (2020)/Season 01/S01E01.mkv",
            "MediaSources": [
                {
                    "Size": 2 * 1024**3,
                    "MediaStreams": [{"Type": "Video", "Width": 1920, "Height": 1080, "Codec": "h264"}],
                }
            ],
        },
    ]
    conn = build_inventory_db(items)
    try:
        cols, rows = run_sql_query(
            conn,
            "SELECT kind, title, resolution FROM items ORDER BY size_bytes DESC",
        )
        assert cols == ["kind", "title", "resolution"]
        assert rows == [("movie", "Big Movie", "2160p"), ("tv", "Some Show", "1080p")]

        buf = StringIO()
        render_inventory_summary(conn, Console(file=buf, force_terminal=False, width=120), limit=5)
        out = buf.getvalue()
        assert "Big Movie" in out
        assert "Some Show" in out
        assert "12.0 GiB" in out
    finally:
        conn.close()
