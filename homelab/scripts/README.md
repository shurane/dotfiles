# Homelab Scripts

Automated media downloaders, metadata indexers, and Jellyfin library helpers.

## Setup

Sync dependencies into the local virtual environment:

```bash
uv sync
```

---

## Commands

### `download-numberblocks`
Downloads and organizes Numberblocks from YouTube directly into 1080p AV1+Opus `.mkv` files with Jellyfin-compliant naming.

```bash
# Dry run simulation (first item of Season 1)
uv run download-numberblocks --dry-run -s 1 --limit 1

# Download a single season
uv run download-numberblocks -s 5

# Download multiple seasons and trigger Jellyfin scan on completion
uv run download-numberblocks -s 1-4 --scan

# Download all 8 seasons
uv run download-numberblocks -s all --scan
```

---

### `download-anpanman`
Downloads Soreike! Anpanman episodes from Internet Archive, matches Romanized titles from metadata, and hardlinks into the Jellyfin library.

```bash
# Quick test (download single file)
uv run download-anpanman --limit 1

# Download Season 1 and trigger Jellyfin library refresh
uv run download-anpanman --season 1 --scan

# Download episode range with 4 concurrent streams
uv run download-anpanman --season 1 --episodes 1-50 --concurrency 4

# Perform deep MD5 checksum verification on existing files
uv run download-anpanman --verify-checksum
```

---

### `build-anpanman-metadata`
Scrapes Japanese Wikipedia (`それいけ!アンパンマンのエピソード一覧`), Romanizes titles with `pykakasi`, and updates `anpanman_metadata.json`.

```bash
# Dry run inspection (first archive section only)
uv run build-anpanman-metadata --dry-run --end-sec 2

# Scrape and regenerate full anpanman_metadata.json
uv run build-anpanman-metadata
```

---

### `jellyfin-scan`
Triggers an immediate Jellyfin library refresh via the REST API (`POST /Library/Refresh`) using credentials from `~/dotfiles/homelab/.env`.

```bash
# Trigger Jellyfin library refresh
uv run jellyfin-scan
```
