# Homelab

### 1. Hardware & GPU Bootstrap (First run or hardware changes)

Auto-detects host GPU, sets `VIDEO_GID` / `RENDER_GID` in `.env`, and configures Jellyfin hardware transcoding.
Defaults to dry-run preview; pass `--apply` to write changes:

```bash
./jellyfin/bootstrap.py --apply
```

Optional flags: `--info` (GPU diagnostics), `--test` (run test suite).

### 2. Start Services

Compose is run from this directory:

```bash
docker compose pull
docker compose up -d --remove-orphans
```

### 3. Auth Bootstrap

Defaults to dry-run verification; pass `--apply` to commit credentials:

```bash
./auth/main.py --apply
./auth/main.py --apply --services jellyfin
```

Run without `--apply` to verify credentials in dry-run mode.

`HOSTNAME_BASE` is the canonical local domain (e.g. `009973.xyz`).

### 4. Health & Status Checks

Deep health & content inspector that authenticates and queries service state, libraries, torrents, shares, and routes:

```bash
# Run via uv project script
uv run --project status status

# Or execute main.py directly
./status/main.py
./status/main.py --service jellyfin --service qbittorrent
./status/main.py --json

# Run unit tests
cd status && uv run pytest
```
