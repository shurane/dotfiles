#!/usr/bin/env python3
"""Homelab Centralized Authentication Bootstrap Manager."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# If executed directly with system Python outside uv, re-exec via uv run --project
if "VIRTUAL_ENV" not in os.environ:
    project_dir = Path(__file__).resolve().parent
    uv_path = shutil.which("uv")
    if not uv_path:
        local_uv = Path.home() / ".local" / "bin" / "uv"
        if local_uv.is_file():
            uv_path = str(local_uv)
    if uv_path and os.path.isfile(uv_path):
        os.execv(uv_path, [uv_path, "run", "--project", str(project_dir), str(__file__), *sys.argv[1:]])

from cli import typer_main

if __name__ == "__main__":
    typer_main()
