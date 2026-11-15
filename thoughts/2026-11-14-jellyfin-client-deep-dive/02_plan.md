# Implementation Plan: Jellyfin Client Deep-Dive & Route Classification

## Overview
Enhance Jellyfin client tracking in `homelab/status` by resolving client hostnames, distinguishing local vs Tailscale access routes, decoding browser User-Agents from `DeviceId`, and displaying a dedicated **Connected Clients (Last 24h)** table in `status jellyfin`.

---

## Proposed Changes

### 1. `homelab/status/services/jellyfin.py`
- [x] **Extend `ConnectedClientInfo` dataclass**:
  - Add fields: `platform: str = ""`, `route: str = ""`, `endpoint: str = ""`, `route_badge: str = ""`
- [x] **Implement Route & User-Agent Decoding Helpers**:
  - `classify_client_route(ip: str | None) -> tuple[str, str]`: Uses `ipaddress` to identify `Tailscale` (`100.64.0.0/10`), `LAN` (RFC1918), `Local` (loopback), or `WAN`.
  - `decode_browser_user_agent(device_id: str) -> str | None`: Decodes Base64 Jellyfin Web device IDs into human-readable OS and browser (e.g., `Firefox on Windows 11`, `Chrome on Linux`).
  - `normalize_hostname(host: str | None) -> str | None`: Strips domain suffixes (`.lan`, `.local`, `.ts.net`, `.localdomain`) so `sp11.lan` and `sp11.tail4f594f.ts.net` both map to `sp11`.
  - `load_device_cache()` and `save_device_cache()`: Reads/writes `~/.cache/homelab/jellyfin_device_routes.json` so disconnected 24h devices maintain their rich route and hostname context.
- [x] **Enhance `evaluate_jellyfin_report()`**:
  - Correlate active `/Sessions` endpoints (`RemoteEndPoint`) with `/Devices` records.
  - Populate hostname, decoded platform, route name, and route badge for each client.
  - Update cached entries for future runs.
- [x] **Update Presentation**:
  - `check_jellyfin()`: Update `Active Clients (24h)` tree line with route tags, e.g., `Infuse-Direct (Keifukus-iPad-Pro-11 • LAN)`, `Jellyfin Web (Firefox on sp11 • Tailscale)`.
  - `render_jellyfin_deep_report()`: Add dedicated Rich table `👥 Connected Clients (Last 24h)` with columns:
    `Client App` | `Device Name` | `Platform / OS` | `Route & Endpoint` | `Last Active` | `User`

### 2. `homelab/status/commands/jellyfin.py`
- [x] **Add `--limit` / `-n` Flag for Recent Playback History**:
  - Add `limit: int = typer.Option(10, "--limit", "-n", help="Number of recent playback items to display [default: 10]")`.
  - Pass `limit` to `run_jellyfin_deep_check(ctx, history_limit=limit)`.
- [x] **Update JSON Serialization**:
  - Ensure new fields (`platform`, `route`, `endpoint`, `route_badge`) in `ConnectedClientInfo` are included when `--json` is specified.

### 3. `homelab/status/tests/test_jellyfin_failure_modes.py`
- [x] **Add Unit Tests**:
  - `test_classify_client_route()`: Test Tailscale IP (`100.123.98.28`), LAN IP (`192.168.8.144`, `192.168.8.135`), Loopback (`127.0.0.1`), WAN (`8.8.8.8`), and invalid IPs.
  - `test_decode_browser_user_agent()`: Test Windows 10/11 Firefox, macOS Safari, Linux Chrome, and graceful fallback on UUIDs (VidHub/Infuse).
  - `test_normalize_hostname()`: Test `.lan`, `.local`, `.tail4f594f.ts.net` stripping.
  - `test_device_route_cache_io()`: Verify reading and writing to cache file handles missing dirs and invalid JSON safely.
  - `test_connected_clients_enrichment()`: Verify `evaluate_jellyfin_report` attaches route badges, hostnames, and decoded platforms correctly.

---

## Verification Plan

### Automated Tests
1. Run pytest suite:
   ```bash
   uv run --project homelab/status pytest homelab/status/tests
   ```
2. Run Ruff linter:
   ```bash
   uv run --project homelab/status ruff check homelab/status/services/jellyfin.py homelab/status/commands/jellyfin.py homelab/status/tests/test_jellyfin_failure_modes.py
   ```

### Manual Verification
1. **Summary Tree**:
   ```bash
   uv run --project homelab/status status --service jellyfin
   ```
   Verify active clients display route tags: `Infuse-Direct (Keifukus-iPad-Pro-11 • LAN)`, `Jellyfin Web (Firefox on sp11 • Tailscale)` or `(Firefox on sp11 • LAN)`.
2. **Deep Inspector Subcommand**:
   ```bash
   uv run --project homelab/status status jellyfin
   ```
   Verify the new `👥 Connected Clients (Last 24h)` table renders cleanly alongside the existing `Recent Playback History` table.
3. **JSON Export**:
   ```bash
   uv run --project homelab/status status jellyfin --json
   ```
   Verify `platform`, `route`, and `endpoint` fields appear in `connected_clients_24h` JSON array.
