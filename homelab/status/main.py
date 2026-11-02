#!/usr/bin/env sh
[ -d "$HOME/.local/bin" ] && case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH" ;; esac
exec uv run --project "$(dirname "$0")" status "$@"
