#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Jellyfin Library Scan CLI Helper
# Triggers a full library refresh on Jellyfin via the REST API.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"

if [ -f "$ENV_FILE" ]; then
    VAL=$(grep -E "^JELLYFIN_API_KEY=" "$ENV_FILE" | cut -d= -f2- || true)
    if [ -n "$VAL" ]; then
        JELLYFIN_API_KEY="$VAL"
    fi
fi

if [ -z "${JELLYFIN_API_KEY:-}" ]; then
    echo "Error: JELLYFIN_API_KEY not found in environment or ${ENV_FILE}" >&2
    exit 1
fi

API_KEY="${JELLYFIN_API_KEY}"
HOST="${JELLYFIN_HOST:-http://127.0.0.1:8096}"

echo "Triggering Jellyfin library scan..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${HOST}/Library/Refresh" \
    -H "Authorization: MediaBrowser Token=\"${API_KEY}\"")

if [ "$STATUS" = "204" ]; then
    echo "Library scan triggered successfully (HTTP 204)."
else
    echo "Failed to trigger scan. HTTP Status: $STATUS" >&2
    exit 1
fi
