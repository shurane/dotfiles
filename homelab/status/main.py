#!/usr/bin/env -S uv run
"""Homelab status inspector entrypoint script."""

from __future__ import annotations

from homelab_status.main import app

if __name__ == "__main__":
    app()
