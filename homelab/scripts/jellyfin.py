"""Jellyfin REST API client helper for library refresh and automation."""

import os
import sys
from pathlib import Path

import httpx
from rich.console import Console


def get_jellyfin_config(env_file: Path | None = None) -> tuple[str, str] | None:
    """Resolve (base_url, api_key) from environment or .env file."""
    api_key = os.environ.get("JELLYFIN_API_KEY")
    hostname_base = os.environ.get("HOSTNAME_BASE")

    target_env = env_file if env_file is not None else Path.home() / "dotfiles/homelab/.env"
    if target_env.exists():
        for raw_line in target_env.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if not api_key and line.startswith("JELLYFIN_API_KEY="):
                api_key = line.split("=", 1)[1].strip().strip("\"'")
            elif not hostname_base and line.startswith("HOSTNAME_BASE="):
                hostname_base = line.split("=", 1)[1].strip().strip("\"'")

    if api_key and hostname_base:
        return f"https://jellyfin.{hostname_base}", api_key
    return None


def refresh(console: Console | None = None) -> bool:
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
    headers = {"Authorization": f'MediaBrowser Token="{api_key}"'}
    out.print(f"[bold cyan]Triggering Jellyfin library refresh at [white]{url}[/white]...[/bold cyan]")

    try:
        resp = httpx.post(url, headers=headers, timeout=10.0)
        if resp.status_code == 204:
            out.print("[bold green]✔ Jellyfin library refresh triggered successfully (HTTP 204).[/bold green]")
            return True
        out.print(f"[bold red]✖ Jellyfin refresh failed with status {resp.status_code}[/bold red]")
    except httpx.HTTPError as exc:
        out.print(f"[bold red]✖ Jellyfin refresh request failed: {exc}[/bold red]")

    return False


def main() -> None:
    """CLI entry point to trigger a Jellyfin library refresh."""
    success = refresh()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
