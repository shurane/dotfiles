#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "anyio>=4.7.0",
#   "docker>=7.1.0",
#   "httpx>=0.27.0",
#   "paramiko>=3.5.0",
#   "python-dotenv>=1.0.0",
#   "rich>=13.0.0",
#   "typer>=0.16.0",
# ]
# ///
# ruff: noqa: E402
"""Homelab Deep Health & Content Inspector.

Entrypoint wrapper delegating to status.main.app.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HOMELAB_DIR = Path(__file__).resolve().parent
if str(_HOMELAB_DIR) not in sys.path:
    sys.path.insert(0, str(_HOMELAB_DIR))

from status.main import app

if __name__ == "__main__":
    app()
