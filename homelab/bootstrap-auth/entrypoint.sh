#!/bin/sh
set -eu

export PATH="/root/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  wget -qO- https://astral.sh/uv/install.sh | sh
fi

exec uv run ./scripts/bootstrap_auth.py "$@"
