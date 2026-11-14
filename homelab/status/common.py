"""Common CLI rendering and connection formatting utilities for homelab inspectors."""

from __future__ import annotations

import datetime
import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from models import TargetConnection

console = Console()


class Env(dict[str, str]):
    """Environment dictionary with strict key requirement helper."""

    def require(self, key: str) -> str:
        """Return non-empty setting or print formatted error and exit."""
        if val := self.get(key):
            return val
        console.print(f"[bold red]Error:[/bold red] {key} not found in .env or environment")
        sys.exit(1)


def require(env: dict[str, str], key: str) -> str:
    """Retrieve key from env dict or print error and exit in 1 line."""
    if isinstance(env, Env):
        return env.require(key)
    if val := env.get(key):
        return val
    console.print(f"[bold red]Error:[/bold red] {key} not found in .env or environment")
    sys.exit(1)


# Backwards compatibility alias
require_env = require


def format_bytes(bytes_val: int) -> str:
    """Format bytes into human-friendly string (KB, MB, GB)."""
    if bytes_val < 1024:
        return f"{bytes_val} B"
    if bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} KB"
    if bytes_val < 1024 * 1024 * 1024:
        return f"{bytes_val / (1024 * 1024):.1f} MB"
    return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"


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
    console: Console,
    border_style: str = "magenta",
) -> None:
    """Render the standardized header panel showing target host, IP, route badge, and execution mode."""
    if not conn:
        return

    badge, _, full = format_connection_badge(conn)
    ip_info = f" ({conn.ip})" if conn.ip and conn.ip != "unknown" else ""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    header_text = Text()
    header_text.append(f"{title}\n", style=f"bold {border_style}")
    header_text.append(f"Target: {conn.host}{ip_info}  •  Route: ", style="dim")
    header_text.append_text(Text.from_markup(badge))
    header_text.append(f"\nExecution Mode: {full}  •  Time: {now_str}", style="dim")

    console.print()
    console.print(Panel(header_text, border_style=border_style, expand=False))


def format_route_line(conn: TargetConnection | None) -> str:
    """Format a bullet line detailing the inspection route for verdict panels."""
    if not conn:
        return ""
    badge, endpoint, _ = format_connection_badge(conn)
    return f"• [bold]Inspection Route:[/bold] {badge} [dim]({endpoint})[/dim]\n"
