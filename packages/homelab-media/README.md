# homelab-media

Fast, typed Python 3.14 CLI tool for auditing media library gaps between `/mnt/mango/torrents` and `/mnt/mango/media`, filtering extras/featurettes, and safely creating zero-copy hardlinks for Jellyfin.

## Usage

```bash
# Overview of in-progress torrents, sync gaps, flagged reviews, and skipped extras
media status

# Preview exact planned hardlink operations (or machine-readable JSON)
media plan
media plan --json

# Execute hardlinks and trigger Jellyfin library refresh
media sync --apply

# Trigger a Jellyfin library scan
media refresh
```
