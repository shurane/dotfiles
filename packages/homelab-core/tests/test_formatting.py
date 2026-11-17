"""Unit tests for homelab_core.formatting."""

from __future__ import annotations

import io
from pathlib import Path

from homelab_core.formatting import (
    format_bytes,
    format_connection_badge,
    format_path,
    format_route_line,
    format_size,
    format_speed,
    render_command_header,
    render_sparkbar,
)
from homelab_core.network import TargetConnection
from rich.console import Console


def test_format_path() -> None:
    assert format_path(None) == "<none>"

    home = Path.home()
    sub_path = home / "dotfiles" / "homelab"
    assert format_path(sub_path) == "~/dotfiles/homelab"


def test_format_bytes() -> None:
    assert format_bytes(500) == "500 B"
    assert format_bytes(2048) == "2.0 KB"
    assert format_bytes(5 * 1024 * 1024) == "5.0 MB"
    assert format_bytes(10 * 1024 * 1024 * 1024) == "10.00 GB"


def test_format_speed() -> None:
    assert format_speed(500) == "500 B/s"
    assert format_speed(2048) == "2.0 KB/s"
    assert format_speed(5 * 1024 * 1024) == "5.00 MB/s"


def test_format_size() -> None:
    assert format_size(1024 * 1024) == "1 MB"
    assert format_size(2 * 1024 * 1024 * 1024) == "2.0 GB"
    assert format_size(15 * 1024 * 1024 * 1024) == "15 GB"
    assert format_size(2 * 1024 * 1024 * 1024 * 1024) == "2.0 TB"


def test_render_sparkbar() -> None:
    zero = render_sparkbar(0.0, width=10)
    assert "grey27" in zero
    half = render_sparkbar(0.5, width=10)
    assert "bold cyan" in half
    seventy = render_sparkbar(0.75, width=10)
    assert "bold yellow" in seventy
    ninety = render_sparkbar(0.95, width=10)
    assert "bold red" in ninety


def test_format_connection_badge_and_route() -> None:
    none_badge, _, _ = format_connection_badge(None)
    assert "Unknown" in none_badge
    assert format_route_line(None) == ""

    local_conn = TargetConnection(
        host="localhost",
        ip="127.0.0.1",
        is_local=True,
        route="local",
        description="Localhost / loopback",
    )
    badge, endpoint, full = format_connection_badge(local_conn)
    assert "On-Device" in badge
    assert "Local UNIX socket" in endpoint
    assert "On-Device (localhost • Local UNIX socket)" in full

    route_line = format_route_line(local_conn)
    assert "Inspection Route:" in route_line
    assert "On-Device" in route_line

    ts_conn = TargetConnection(
        host="m70q",
        ip="100.120.146.29",
        is_local=False,
        route="tailscale",
        description="Tailscale VPN",
    )
    ts_badge, ts_endpoint, _ = format_connection_badge(ts_conn)
    assert "Tailscale" in ts_badge
    assert "100.120.146.29" in ts_endpoint

    lan_conn = TargetConnection(
        host="m70q.lan",
        ip="192.168.8.10",
        is_local=False,
        route="lan",
        description="Direct Local Area Network",
    )
    lan_badge, lan_endpoint, _ = format_connection_badge(lan_conn)
    assert "Direct LAN" in lan_badge
    assert "192.168.8.10" in lan_endpoint


def test_render_command_header() -> None:
    f = io.StringIO()
    c = Console(file=f, force_terminal=True, width=100)
    conn = TargetConnection(
        host="m70q.lan",
        ip="192.168.8.10",
        is_local=False,
        route="lan",
        description="Direct Local Area Network",
    )
    render_command_header("Service Status", conn, c)
    output = f.getvalue()
    assert "Service Status" in output
    assert "m70q.lan" in output
    assert "Direct LAN" in output

    # When conn is None, does not write anything
    f_empty = io.StringIO()
    c_empty = Console(file=f_empty, force_terminal=True, width=100)
    render_command_header("Test", None, c_empty)
    assert f_empty.getvalue() == ""
