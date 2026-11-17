"""Display, terminal UI, and unit formatting helpers for homelab tools."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from whenever import SYSTEM_TZ, ZonedDateTime

if TYPE_CHECKING:
    from homelab_core.network import TargetConnection

__all__ = [
    "format_bytes",
    "format_connection_badge",
    "format_path",
    "format_route_line",
    "format_size",
    "format_speed",
    "render_command_header",
    "render_sparkbar",
]


def format_path(path: Path | None) -> str:
    """Format path relative to user's home directory (e.g. ~/dotfiles/...) if applicable."""
    if path is None:
        return "<none>"
    with contextlib.suppress(ValueError, RuntimeError):
        resolved = path.resolve()
        home = Path.home().resolve()
        if resolved == home:
            return "~"
        if resolved.is_relative_to(home):
            return f"~/{resolved.relative_to(home)}"
    return str(path)


def format_bytes(bytes_val: int) -> str:
    """Format bytes into a human-friendly string (KB, MB, GB)."""
    if bytes_val < 1024:
        return f"{bytes_val} B"
    if bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} KB"
    if bytes_val < 1024 * 1024 * 1024:
        return f"{bytes_val / (1024 * 1024):.1f} MB"
    return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"


def format_speed(bytes_per_sec: float) -> str:
    """Format transfer speed in bytes per second into B/s, KB/s, MB/s."""
    bps = float(bytes_per_sec)
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / (1024 * 1024):.2f} MB/s"


def format_size(bytes_val: float) -> str:
    """Format storage capacity into KB, MB, GB, or TB."""
    n = float(bytes_val)
    if n >= 1024**4:
        return f"{n / (1024**4):.1f} TB"
    if n >= 1024**3:
        gb = n / (1024**3)
        return f"{gb:.0f} GB" if gb >= 10 else f"{gb:.1f} GB"
    if n >= 1024**2:
        return f"{n / (1024**2):.0f} MB"
    return f"{n / 1024:.0f} KB"


def render_sparkbar(pct: float, width: int = 10, bg: str = "grey27") -> str:
    """Render a fractional block sparkline gauge with seamless background color alignment."""
    blocks = ("", "▏", "▎", "▍", "▌", "▋", "▊", "▉")
    val = max(0.0, min(1.0, pct)) * width
    full = int(val)
    rem = val - full
    char_idx = round(rem * 8)
    if char_idx == 8:
        full += 1
        part = ""
    else:
        part = blocks[char_idx]

    full = min(full, width)
    if full == width:
        part = ""
    empty = max(0, width - full - (1 if part else 0))
    fg = "bold red" if pct >= 0.9 else ("bold yellow" if pct >= 0.7 else "bold cyan")

    filled = f"[{fg}]" + ("█" * full) + f"[/{fg}]" if full else ""
    partial = f"[{fg} on {bg}]{part}[/]" if part else ""
    unfilled = f"[{bg}]" + ("█" * empty) + f"[/{bg}]" if empty else ""
    return f"[{filled}{partial}{unfilled}]"


def format_connection_badge(conn: TargetConnection | None) -> tuple[str, str, str]:
    """Format connection route into a Rich badge, endpoint description, and full summary.

    Returns:
        tuple[badge_markup, endpoint_str, full_summary_str]
    """
    if not conn:
        return "[dim]Unknown[/dim]", "unknown", "Unknown execution context"

    ip_str = f" • {conn.ip}" if conn.ip and conn.ip != "unknown" else ""

    if conn.is_local or conn.route == "local":
        badge = "[bold magenta]🏠 On-Device[/bold magenta]"
        endpoint = f"{conn.host} • Local UNIX socket"
        full = f"On-Device ({endpoint})"
    elif conn.route == "tailscale":
        badge = "[bold cyan]🔒 Remote (Tailscale)[/bold cyan]"
        endpoint = f"{conn.host}{ip_str}"
        full = f"Remote via Tailscale ({endpoint})"
    elif conn.route == "lan":
        badge = "[bold green]🟢 Remote (Direct LAN)[/bold green]"
        endpoint = f"{conn.host}{ip_str}"
        full = f"Remote via Direct LAN ({endpoint})"
    else:
        badge = f"[bold yellow]🌐 Remote ({conn.description})[/bold yellow]"
        endpoint = f"{conn.host}{ip_str}"
        full = f"Remote via {conn.description} ({endpoint})"

    return badge, endpoint, full


def render_command_header(
    title: str,
    conn: TargetConnection | None,
    console: Console | None = None,
    border_style: str = "magenta",
) -> None:
    """Render the standardized header panel showing target host, IP, route badge, and execution mode."""
    if not conn:
        return

    out = console or Console()
    badge, _, full = format_connection_badge(conn)
    ip_info = f" ({conn.ip})" if conn.ip and conn.ip != "unknown" else ""
    now_str = ZonedDateTime.now(SYSTEM_TZ).format("YYYY-MM-DD HH:mm:ss")

    header_text = Text()
    header_text.append(f"{title}\n", style=f"bold {border_style}")
    header_text.append(f"Target: {conn.host}{ip_info}  •  Route: ", style="dim")
    header_text.append_text(Text.from_markup(badge))
    header_text.append(f"\nExecution Mode: {full}  •  Time: {now_str}", style="dim")

    out.print()
    out.print(Panel(header_text, border_style=border_style, expand=False))


def format_route_line(conn: TargetConnection | None) -> str:
    """Format a bullet line detailing the inspection route for verdict panels."""
    if not conn:
        return ""
    badge, endpoint, _ = format_connection_badge(conn)
    return f"• [bold]Inspection Route:[/bold] {badge} [dim]({endpoint})[/dim]\n"
