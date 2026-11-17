"""Common CLI rendering and connection formatting utilities for homelab inspectors."""

from __future__ import annotations

from homelab_core.formatting import (
    format_bytes,
    format_connection_badge,
    format_route_line,
    render_command_header,
)
from rich.console import Console

__all__ = [
    "format_bytes",
    "format_connection_badge",
    "format_route_line",
    "render_command_header",
]

console = Console()
