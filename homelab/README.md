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
# Direct CLI (installed via uv tool) or via packages/ workspace:
auth                                          # Dry-run verification across all services
auth --apply                                  # Commit credentials
auth --apply --services jellyfin

# Or run via packages/ workspace:
uv run --project ../packages auth             # From homelab/
```

`HOSTNAME_BASE` is the canonical local domain (e.g. `example.com`).

### 4. Health & Status Checks

Deep health & content inspector that authenticates and queries service state, libraries, torrents, shares, and routes:

```bash
# Run full status tree (direct CLI or via packages/)
status
# or: uv run --project ../packages status

# Deep service inspectors
status jellyfin      # Intel QuickSync (QSV) transcode benchmark, 512MB cgroup, active streams, media library
status qbittorrent   # VPN tun0 binding, port alignment, /mnt/mango/torrents rw, swarm speeds, errors
status samba         # Port 445, SMB auth & empty pw rejection, drive mounts (/dev/sda1 rw), active clients, locks
status vpn           # ProtonVPN tun0 tunnel, Gluetun kill switch, port forwarding, qBittorrent integration

# Filter services, inspect remote hosts, or export JSON
status --service jellyfin --service qbittorrent
status -H server.lan       # Inspect remote host (auto-resolves LAN / Tailscale)
status --json

# Run unit test suites from packages/
cd ../packages && uv run pytest homelab-status/tests
uv --directory auth run pytest              # 29 credential bootstrap tests
```
