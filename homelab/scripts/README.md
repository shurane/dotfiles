# Homelab Scripts

```bash
# Numberblocks (YouTube -> 1080p MKV)
uv run download-numberblocks -s 5
uv run download-numberblocks -s 1-4 --scan
uv run download-numberblocks -s all --scan
uv run download-numberblocks --dry-run -s 1 --limit 1

# Anpanman (Archive.org -> Jellyfin hardlinks)
uv run download-anpanman --season 1 --scan
uv run download-anpanman --season 1 --episodes 1-50 --concurrency 4
uv run download-anpanman --verify-checksum
uv run download-anpanman --limit 1

# Anpanman Metadata (Scrape Wikipedia -> anpanman_metadata.json)
uv run build-anpanman-metadata
uv run build-anpanman-metadata --dry-run --end-sec 2

# Jellyfin (Trigger REST API /Library/Refresh)
uv run jellyfin-scan
```
