# Research: Homelab Adversarial Performance Optimization & Systemic Profiling

## 1. Overview & Goals
Following comprehensive VizTracer profiling of `homelab/status`, `homelab/auth`, and `homelab/scripts`, an adversarial audit identified latency bottlenecks, process spawn overhead, unresolvable bare hostnames, obsolete container references, and disk footprint inflation.

### Primary Objectives
1. **Trace Persistence & Compression**: Compress large VizTracer `.json` traces (>550MB raw) into `.json.zst` using Zstandard level 9 without modifying originals.
2. **`homelab/auth` Concurrency & Endpoint Fallback**:
   - Parallelize dry-run credential checks across all selected services.
   - Resolve bare service hostnames (`http://qbittorrent:8080`) when executed outside Docker network to live endpoints (`https://qbittorrent.009973.xyz`) via `AUTH_ENV` (`HOSTNAME_BASE` / `HOMELAB_HOSTNAME`).
   - Add fast connection failover (`connect=0.5s`) to prevent blocking on dead endpoints.
   - Add `if __name__ == "__main__": typer_main()` entry point to `cli.py`.
3. **`homelab/status` Central Container Typing & Dead Reference Removal**:
   - Audit all container name strings (~35 occurrences) across `models.py` and all 12 service inspectors.
   - Implement a statically-typed `ContainerName(StrEnum)` in `models.py` for type safety, autocomplete, and rename resilience.
   - Remove obsolete `homelab-homepage-1` (replaced by Glance) and `homelab-jellyfin-1` (lacks `wget`) from host public IP probe lists, replacing them with `(ContainerName.CADDY, ContainerName.GLANCE)`.
   - Update `Recent Plays (24h)` in the Jellyfin status tree to list up to the last 10 streamed items with yellow titles and device/client details.
4. **`homelab/scripts` Performance**:
   - `sync_maruko.py`: Prevent spawning synchronous `ffmpeg` processes for all 142 episodes on repeat runs by checking if the `.nfo` already exists; add `--repair` flag to force re-extraction.
   - `download_numberblocks.py`: Pass `--flat-playlist` during `--dry-run` to eliminate full webpage downloads and Deno JS challenge solving.

---

## 2. VizTracer Profiling Baselines & Findings

### A. `homelab/auth` (Baseline: 16.11s $\rightarrow$ Optimized: 0.82s — 19.5x Speedup)
* **Raw Trace**: `trace_auth.json` (67.7 MB, 391,756 events).
* **Root Cause 1 — Serial Execution**:
  [cli.py](file:///home/ehtesh/dotfiles/homelab/auth/cli.py) looped synchronously through each check (`check_qbittorrent`, `check_qui`, `check_arcane`, `check_jellyfin`, `check_bookorbit`), forcing serial execution regardless of `--parallel`.
* **Root Cause 2 — Synchronous glibc `getaddrinfo` DNS Hang**:
  When run from a client machine (`sp11`), `get_container_ip()` returns `None`. `config.py` fell back to `http://{service_name}:{port}` (e.g. `http://qbittorrent:8080`).
  In Linux glibc, `socket.getaddrinfo` is a synchronous C call that ignores socket timeouts and queries `/etc/resolv.conf` nameservers for bare hostnames, waiting ~3.75s before returning `[Errno -2] Name or service not known`.
  4 services $\times$ ~3.75s = ~15.0s spent blocked in libc!
* **Solution**:
  - Dynamically resolve via `HOSTNAME_BASE` (`https://{service}.009973.xyz`) or `HOMELAB_HOSTNAME` in `config.py` when `get_container_ip()` is `None`. Resolves in ~23ms.
  - Set `timeout=httpx.Timeout(5.0, connect=0.5)` on check clients for fast 500ms failover.
  - Concurrently execute dry-run checks via `anyio.create_task_group()` and `to_thread.run_sync()`, sorting results to ensure clean, non-interleaved output.

### B. `homelab/status` (Baseline: 1.44s – 5.47s)
* **Raw Traces**: `trace_status.json` (147 MB, 895,777 events), `trace_status_jellyfin.json` (112 MB, 674,434 events).
* **Container Inventory & Typing**:
  Exactly 12 Compose containers run on the homelab host:
  `caddy`, `glance`, `arcane`, `bookorbit`, `bookorbit-postgres`, `jellyfin`, `gluetun`, `qbittorrent`, `qui`, `rclone-retroarch`, `samba`, `withings-sync`.
* **Dead Container Lookups in `_fetch_host_ip`**:
  `gluetun.py` and `qbittorrent.py` queried `homelab-homepage-1` (does not exist) and `homelab-jellyfin-1` (has no `wget`, returning OCI exit code 127).
  Replacing both with `(ContainerName.CADDY, ContainerName.GLANCE)` ensures both fallback containers exist and bundle `wget`.
* **Jellyfin Recent Plays Tree**:
  `check_jellyfin()` previously displayed only `report.recent_playback[0]` (`Last: ...`). Expanding this to iterate over `report.recent_playback[:10]` surfaces the full history of active episodes while preserving the 24h count summary.

### C. `homelab/scripts`
* **`sync_maruko.py` (Subprocess Bomb)**:
  `extract_english_title_from_mkv` ran `ffmpeg` for every file in the source directory. Across 142 episodes, this incurred 142 synchronous process forks (~25-30s).
  By guarding subtitle extraction with `needs_nfo_check = args.repair or not dest_nfo.exists() or dest_nfo.stat().st_size == 0`, repeat syncs execute in **<0.15s**.
* **`download_numberblocks.py` (yt-dlp Extraction Buffer Overflow)**:
  Simulating playlist downloads previously downloaded all 30+ video web pages and solved JS challenges via Deno (4.58s, overflowing VizTracer's 1,000,000 circular buffer).
  Adding `--flat-playlist` to `--simulate` dropped runtime to **0.69s** (6.6x speedup).

---

## 3. Compression Benchmarks (zstd -9)
| Trace File | Raw Size | Compressed (`.zst`) | Compression Ratio | Space Saved |
| :--- | :--- | :--- | :--- | :--- |
| `trace_numberblocks.json` | 151.7 MB | 7.0 MB | 21.7 : 1 | 95.4% |
| `trace_status.json` | 147.2 MB | 7.6 MB | 19.4 : 1 | 94.8% |
| `trace_status_jellyfin.json` | 112.3 MB | 5.9 MB | 19.0 : 1 | 94.7% |
| `trace_auth.json` | 67.7 MB | 4.4 MB | 15.4 : 1 | 93.5% |
| `trace_anpanman.json` | 35.5 MB | 2.1 MB | 16.9 : 1 | 94.1% |
| `trace_maruko.json` | 19.7 MB | 1.1 MB | 17.9 : 1 | 94.4% |
| `trace_jellyfin_scan.json` | 16.5 MB | 0.9 MB | 18.3 : 1 | 94.5% |
| **Total** | **550.6 MB** | **34.8 MB** | **15.8 : 1** | **93.7%** |
