#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "anyio>=4.7.0",
#   "docker>=7.1.0",
#   "httpx>=0.27.0",
#   "pydantic>=2.7.0",
#   "rich>=13.0.0",
#   "trio>=0.27.0",
#   "typer>=0.16.0",
#   "werkzeug>=3.0.0",
# ]
# ///
"""Homelab Centralized Authentication Bootstrap Manager.

Safely checks and synchronizes shared credentials across:
1. qBittorrent (Web UI preferences)
2. Qui (User credentials & password)
3. Arcane (Docker management login)
4. Jellyfin (Admin user, password hash, and API token)
"""

from bootstrap_auth.cli import typer_main

if __name__ == "__main__":
    typer_main()
