#!/usr/bin/env sh
exec uv run --project "$(dirname "$0")" status "$@"
