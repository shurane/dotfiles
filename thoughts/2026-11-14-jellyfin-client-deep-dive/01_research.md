# Research: Jellyfin Client Enrichment & Route Classification

## 1. Overview & User Goals
The goal is to enrich connected client tracking in `homelab/status` (both the `--service jellyfin` overview tree and the dedicated `status jellyfin` deep inspector):
1. **Device Identification**: Map Jellyfin device endpoints and client records to human-friendly device hostnames (e.g., `sp11`, `Keifukus-iPad-Pro-11`).
2. **Access Route Distinction**: Explicitly identify and display whether a client accessed Jellyfin locally over LAN (`192.168.8.x`) or remotely over Tailscale (`100.x.y.z`), or local loopback.
3. **Platform / User-Agent Decoding**: Automatically parse browser and operating system information from Jellyfin Web's base64-encoded `DeviceId` (e.g., `Firefox on Windows 11`, `Safari on macOS`).
4. **Rich Table in Deep Inspection**: Add a dedicated "Connected Clients (Last 24h)" table in `status jellyfin` showing Client App, Device Name, Platform / OS, Route & Endpoint, and Last Active time.
5. **Session & Device Persistence**: Persist known client routes so devices that were active within the last 24h retain their rich device identity even after disconnecting from the transient `/Sessions` endpoint.

---

## 2. Codebase Architecture & Key Files

### Existing Files
1. **`homelab/status/services/jellyfin.py`**:
   - Manages Jellyfin API authentication (`/Users/AuthenticateByName`), device inspection (`/Devices`), session queries (`/Sessions`), and activity logs (`/System/ActivityLog/Entries`).
   - Defines `ConnectedClientInfo`, `PlaybackHistoryItem`, and `JellyfinDeepReport`.
   - Evaluates diagnostic data via `evaluate_jellyfin_report()`.
   - Renders deep inspection panels and tables via `render_jellyfin_deep_report()`.
   - Emits tree summary branches via `check_jellyfin()`.
2. **`homelab/status/commands/jellyfin.py`**:
   - CLI command handler for `status jellyfin`.
   - Handles `--json` export of `connected_clients_24h` and `recent_playback`.
3. **`homelab/status/common.py`**:
   - Provides connection route formatting: `format_connection_badge()`, `format_route_line()`.
4. **`homelab/status/tests/test_jellyfin_failure_modes.py`**:
   - Test suite with 16 failure mode and diagnostic tests for Jellyfin.

---

## 3. Technical Discoveries & Implementation Patterns

### A. Route Classification via Standard Library `ipaddress`
- **Tailscale**: Tailscale utilizes the CGNAT RFC6598 block `100.64.0.0/10` (`100.64.0.0` - `100.127.255.255`).
- **Direct LAN**: Private subnets defined by RFC1918 (`192.168.0.0/16`, `10.0.0.0/8`, `172.16.0.0/12`).
- **Local**: `127.0.0.1` or `::1`.
- **Public / WAN**: Any routable global unicast address.
```python
import ipaddress


def classify_client_route(ip_str: str | None) -> tuple[str, str]:
    if not ip_str:
        return ("Unknown", "")
    try:
        ip = ipaddress.ip_address(ip_str.strip())
        if ip.is_loopback:
            return ("Local", "🏠 Local")
        if ip in ipaddress.ip_network("100.64.0.0/10"):
            return ("Tailscale", "🔒 Tailscale")
        if ip.is_private:
            return ("LAN", "🟢 LAN")
        return ("WAN", "🌐 WAN")
    except ValueError:
        return ("Unknown", "")
```

### B. Hostname Stem Normalization
Reverse DNS for both LAN and Tailscale resolves to the same base machine stem:
- `192.168.8.144` ➔ `sp11.lan` ➔ `sp11`
- `100.123.98.28` ➔ `sp11.tail4f594f.ts.net` ➔ `sp11`
- `192.168.8.135` ➔ `Keifukus-iPad-Pro-11.local` / `KeifukuPadPro11.lan` ➔ `Keifukus-iPad-Pro-11`

Stripping trailing domain components (`hostname.split(".")[0]`) unifies the hardware identity across networks.

### C. Browser Platform Decoding from `DeviceId`
Jellyfin Web builds client `DeviceId` values by Base64-encoding `navigator.userAgent + "|" + timestamp`:
- Raw ID: `TW96aWxsYS81LjAgKFdpbmRvd3MgTlQgMTAuMDsgV2luNjQ7IHg2NDsgcnY6MTU3LjApIEdlY2tvLzIwMTAwMTAxIEZpcmVmb3gvMTU3LjB8MTc5MTIxOTI2NzkxNg11`
- Decoded: `Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:157.0) Gecko/20100101 Firefox/157.0`
- Extracted OS: Windows 10/11, macOS, Linux, Android, iOS.
- Extracted Browser: Firefox, Chrome, Edge, Safari.

### D. Session & Device Persistence
While `/Sessions` contains live `RemoteEndPoint` IPs, devices that disconnected or closed tabs in the past 24h remain in `/Devices` without an active session object.
By maintaining a lightweight JSON cache file (`~/.cache/homelab/jellyfin_device_routes.json`), any device resolved while active will preserve its hostname, platform, and last-seen route for offline reporting.

---

## 4. Risks & Mitigations

1. **DNS Lookup Latency**: Reverse DNS queries on unreachable IPs could block or slow down `status`.
   - *Mitigation*: Run reverse DNS queries through `anyio.to_thread.run_sync` with a strict per-query timeout (e.g. 150ms) or use local cache lookup first.
2. **Mangled Base64 in `DeviceId`**: Some third-party clients might send UUIDs or non-base64 strings.
   - *Mitigation*: Graceful exception handling; if base64 decoding fails or doesn't look like a User-Agent, fall back to the raw device name.
3. **No Network Changes When Offline**: Cache read/write must be atomic and handle missing directories safely.

---

## 5. Success Criteria
- [x] Client endpoints accurately classified as `LAN`, `Tailscale`, `Local`, or `WAN`.
- [x] Hostnames normalized consistently (`sp11` regardless of LAN vs Tailscale).
- [x] Browser user-agents decoded to human-readable OS + Browser.
- [x] Dedicated "Connected Clients (Last 24h)" Rich table in `status jellyfin`.
- [x] Enriched branch strings in `status --service jellyfin`.
- [x] All existing 73 tests continue to pass, with new comprehensive tests for route classification, base64 decoding, and cache persistence.
