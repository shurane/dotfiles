# Homelab Scripts

```bash
# Numberblocks
uv run download-numberblocks --season 5
uv run download-numberblocks --season 1-4 --scan     # download & trigger jellyfin scan
uv run download-numberblocks --season all
uv run download-numberblocks --dry-run --season 1 --limit 1

# Anpanman
uv run download-anpanman --season 1 --scan           # download & trigger jellyfin scan
uv run download-anpanman --season 1 --episodes 1-50 --concurrency 4
uv run download-anpanman --verify-checksum           # verify local files against MD5
uv run download-anpanman --dry-run --season 1 --limit 1

# Anpanman metadata
uv run build-anpanman-metadata
uv run build-anpanman-metadata --dry-run --end-sec 2 # test scraper on first 2 sections

# Jellyfin
uv run jellyfin-scan                                 # trigger library refresh
uv run jellyfin-scan --dry-run
```
