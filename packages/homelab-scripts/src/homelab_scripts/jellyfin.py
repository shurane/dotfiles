"""Jellyfin REST API client helper for library refresh and automation."""

from __future__ import annotations

import argparse
import os
import sys
from typing import TYPE_CHECKING

import httpx
from homelab_core.env import load_homelab_env
from homelab_core.services import Service, make_jellyfin_auth_headers, resolve_service_url
from rich.console import Console

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "get_jellyfin_config",
    "main",
    "refresh",
]


def get_jellyfin_config(env_file: Path | None = None) -> tuple[str, str] | None:
    """Resolve (base_url, api_key) from environment or .env file."""
    api_key = os.environ.get("JELLYFIN_API_KEY")
    hostname_base = os.environ.get("HOSTNAME_BASE")

    if not api_key or not hostname_base:
        env = load_homelab_env(env_file)
        api_key = api_key or env.get("JELLYFIN_API_KEY")
        hostname_base = hostname_base or env.get("HOSTNAME_BASE")

    if api_key and hostname_base:
        base_url = resolve_service_url(Service.JELLYFIN, base_domain=hostname_base)
        return base_url, api_key
    return None


def refresh(console: Console | None = None, *, dry_run: bool = False) -> bool:
    """Trigger a Jellyfin library refresh directly via REST API."""
    out = console or Console()
    config = get_jellyfin_config()
    if not config:
        out.print(
            "[bold yellow]⚠ Could not find JELLYFIN_API_KEY or HOSTNAME_BASE in environment "
            "or ~/dotfiles/homelab/.env[/bold yellow]"
        )
        return False

    base_url, api_key = config
    url = f"{base_url}/Library/Refresh"
    if dry_run:
        out.print(
            f"[dim][dry-run][/dim] Would trigger Jellyfin library refresh at [white]{url}[/white]"
        )
        return True

    headers = make_jellyfin_auth_headers(token=api_key, client="homelab-scripts")
    out.print(
        f"[bold cyan]Triggering Jellyfin library refresh at [white]{url}[/white]...[/bold cyan]"
    )

    try:
        resp = httpx.post(url, headers=headers, timeout=10.0)
        if resp.status_code == 204:
            out.print(
                "[bold green]✔ Jellyfin library refresh triggered successfully (HTTP 204).[/bold green]"
            )
            return True
        out.print(f"[bold red]✖ Jellyfin refresh failed with status {resp.status_code}[/bold red]")
    except httpx.HTTPError as exc:
        out.print(f"[bold red]✖ Jellyfin refresh request failed: {exc}[/bold red]")

    return False


def main() -> None:
    """CLI entry point to trigger a Jellyfin library refresh."""
    parser = argparse.ArgumentParser(description="Trigger Jellyfin library scan via REST API.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate library refresh without making API requests",
    )
    args = parser.parse_args()

    success = refresh(dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
