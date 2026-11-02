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
    DOMAIN=$(grep -E "^HOSTNAME_BASE=" "$ENV_FILE" | cut -d= -f2- || true)
    if [ -n "$DOMAIN" ]; then
        HOSTNAME_BASE="$DOMAIN"
    fi
fi

if [ -z "${JELLYFIN_API_KEY:-}" ]; then
    echo "Error: JELLYFIN_API_KEY not found in environment or ${ENV_FILE}" >&2
    exit 1
fi

API_KEY="${JELLYFIN_API_KEY}"
BASE_URL="https://jellyfin.${HOSTNAME_BASE:-009973.xyz}"
HOST="${1:-${JELLYFIN_HOST:-$BASE_URL}}"

echo "Triggering Jellyfin library scan at ${HOST}..."
STATUS=$(curl -fs -o /dev/null -w "%{http_code}" -X POST "${HOST}/Library/Refresh" \
    -H "Authorization: MediaBrowser Token=\"${API_KEY}\"" || echo "failed")

if [ "$STATUS" = "204" ]; then
    echo "Library scan triggered successfully (HTTP 204)."
else
    echo "Failed to trigger scan. Response: $STATUS" >&2
    exit 1
fi
