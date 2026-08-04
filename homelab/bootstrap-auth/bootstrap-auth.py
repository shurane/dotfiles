#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "anyio>=4.7.0",
#   "docker>=7.1.0",
#   "httpx>=0.27.0",
#   "pydantic>=2.7.0",
#   "trio>=0.27.0",
#   "typer>=0.16.0",
#   "werkzeug>=3.0.0",
# ]
# ///
from bootstrap_auth.cli import typer_main

if __name__ == "__main__":
    typer_main()
