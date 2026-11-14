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

Manages and bootstraps authenticated credentials across services (qBittorrent, Qui, Arcane, Jellyfin, BookOrbit).
Defaults to dry-run verification; pass `--apply` to commit credentials:

```bash
# Run from homelab/
uv run --project auth auth                         # Dry-run verification across all services
uv run --project auth auth --apply                 # Commit credentials
uv run --project auth auth --apply --services jellyfin

# Or run from auth/
cd auth
uv run auth                                        # Dry-run verification
uv run auth --apply
```

`HOSTNAME_BASE` is the canonical local domain (e.g. `example.com`).

### 4. Health & Status Checks

Deep health & content inspector that authenticates and queries service state, libraries, torrents, shares, and routes:

```bash
# Run full status tree from homelab/
uv run --project status status

# Deep service inspectors
uv run --project status status jellyfin      # Intel QuickSync (QSV) transcode benchmark, 512MB cgroup, active streams, media library
uv run --project status status qbittorrent   # VPN tun0 binding, port alignment, /mnt/mango/torrents rw, swarm speeds, errors
uv run --project status status samba         # Port 445, SMB auth & empty pw rejection, drive mounts (/dev/sda1 rw), active clients, locks
uv run --project status status vpn           # ProtonVPN tun0 tunnel, Gluetun kill switch, port forwarding, qBittorrent integration

# Filter services, inspect remote hosts, or export JSON
uv run --project status status -s jellyfin -s qbittorrent
uv run --project status status -H m70q.lan         # Inspect remote host (auto-resolves LAN / Tailscale)
uv run --project status status --json

# Or run from status/
cd status
uv run status
uv run status jellyfin

# Run unit test suites from homelab/
uv --directory status run pytest            # 54 status & failure mode tests
uv --directory auth run pytest              # 29 credential bootstrap tests
```
