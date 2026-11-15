# Implementation Plan: Homelab Performance Optimization & Systemic Hardening

## Overview
Implement systemic optimizations across `homelab/status`, `homelab/auth`, and `homelab/scripts` based on VizTracer adversarial traces:
1. Parallelize `auth` dry-run credential checks and resolve bare service URLs dynamically with fast connection timeouts.
2. Centralize container names into a statically-typed `ContainerName(StrEnum)` across all status services and prune dead container lookups (`homepage`, `jellyfin` wget).
3. Expand Jellyfin `Recent Plays (24h)` tree view to render up to 10 items with highlighted episode titles and client descriptions.
4. Optimize `sync_maruko.py` with `--repair` flag and skip unnecessary `ffmpeg` subprocess forks on existing NFOs.
5. Accelerate `download_numberblocks.py` `--dry-run` via `--flat-playlist`.
6. Compress all trace artifacts to `.json.zst` using Zstandard level 9.

---

## Checklist

### Phase 1: Artifact Compression
- [x] Compress all 7 raw VizTracer trace dumps in `scratch/` using `zstd -9 -k *.json` into `*.json.zst`
- [x] Verify original `.json` files are preserved intact and compression achieves >90% size reduction

### Phase 2: `homelab/status` Central Container Typing & Dead Reference Removal
- [x] Define `ContainerName(StrEnum)` in `homelab/status/models.py` with all 12 Compose container names:
  `ARCANE`, `BOOKORBIT`, `BOOKORBIT_POSTGRES`, `CADDY`, `GLANCE`, `GLUETUN`, `JELLYFIN`, `QBITTORRENT`, `QUI`, `RETROARCH`, `SAMBA`, `WITHINGS_SYNC`
- [x] Update `models.py:get_disk_usage()` to use `ContainerName.QBITTORRENT` and `ContainerName.SAMBA`
- [x] Update `services/gluetun.py`:
  - Replace `("homelab-caddy-1", "homelab-homepage-1", "homelab-jellyfin-1")` with `(ContainerName.CADDY, ContainerName.GLANCE)`
  - Replace hardcoded `homelab-gluetun-1` and `homelab-qbittorrent-1` strings with `ContainerName.*`
- [x] Update `services/qbittorrent.py`:
  - Replace `("homelab-caddy-1", "homelab-jellyfin-1")` with `(ContainerName.CADDY, ContainerName.GLANCE)`
  - Replace hardcoded container strings with `ContainerName.*`
- [x] Update all remaining service files to use `ContainerName`:
  - `services/caddy.py`
  - `services/glance.py`
  - `services/arcane.py`
  - `services/bookorbit.py`
  - `services/postgres.py`
  - `services/jellyfin.py`
  - `services/qui.py`
  - `services/retroarch.py`
  - `services/samba.py`
  - `services/withings_sync.py`
- [x] Add unit test `test_container_name_enum()` in `homelab/status/tests/test_status.py` verifying all 12 enum members adhere to `homelab-*-1` format

### Phase 3: `homelab/status` Jellyfin Recent Plays Tree View
- [x] Update `check_jellyfin()` in `homelab/status/services/jellyfin.py`:
  - In `Recent Plays (24h)` branch, iterate over `report.recent_playback[:10]`
  - Format each item with highlighted yellow title: `f"  • [bold yellow]\"{p.media_title}\"[/bold yellow][dim]{dev_str} ({p.relative_time})[/dim]"`
  - Include client/device description (`on {p.client_name}`) when available
- [x] Verify with live CLI: `uv run status --service jellyfin`

### Phase 4: `homelab/auth` Concurrency & Endpoint Fallback
- [x] Parallelize dry-run execution in `homelab/auth/cli.py`:
  - Use `anyio.create_task_group()` and `anyio.to_thread.run_sync()` to check all selected services concurrently
  - Collect results and sort by original service order for clean, non-interleaved terminal output
- [x] Enhance dynamic URL resolution in `homelab/auth/config.py`:
  - When `get_container_ip()` is `None` (running outside Docker network), load `AUTH_ENV`
  - If `HOSTNAME_BASE` is set, return `f"https://{service_name}.{base_domain}"`
  - If `HOMELAB_HOSTNAME` is set, return `f"http://{homelab_host}:{default_port}"`
  - Fall back to `f"http://{service_name}:{default_port}"` only if neither is present
- [x] Add fast connection timeouts in `homelab/auth/services/`:
  - `qbittorrent.py`: `httpx.Timeout(5.0, connect=0.5)`
  - `arcane.py`: `httpx.Timeout(5.0, connect=0.5)`
  - `bookorbit.py`: `httpx.Timeout(5.0, connect=0.5)`
  - `jellyfin.py`: `httpx.Timeout(5.0, connect=0.5)`
- [x] Add `if __name__ == "__main__": typer_main()` entry point to `homelab/auth/cli.py`
- [x] Update unit tests in `homelab/auth/tests/test_compose.py` to test base domain resolution and default fallback

### Phase 5: `homelab/scripts` Performance
- [x] `sync_maruko.py`:
  - Add `--repair` CLI flag (`action="store_true"`)
  - Skip `extract_english_title_from_mkv(src_path)` when destination `.nfo` already exists and is non-empty unless `--repair` is explicitly passed
  - When `--repair` is passed, force re-extracting subtitle titles and regenerating NFOs
- [x] `download_numberblocks.py`:
  - In `download_season()`, add `--flat-playlist` to `ydl_opts` when `dry_run=True` to avoid downloading full video webpages and executing Deno JS challenges

---

## Success Criteria & Verification Scenarios

1. **Test Suite Verification**:
   - `uv run --project homelab/status pytest homelab/status/tests`: All 79 tests pass
   - `uv run --project homelab/auth pytest homelab/auth/tests`: All 30 tests pass
   - `uv run --project homelab/scripts pytest homelab/scripts/tests`: All 36 tests pass
   - Total: **145 unit tests** passing with 0 failures
2. **Linting & Formatting**:
   - `uv run --project homelab/status ruff check homelab/status`: All checks pass
   - `uv run --project homelab/auth ruff check homelab/auth`: All checks pass
   - `uv run --project homelab/scripts ruff check homelab/scripts`: All checks pass
3. **Execution Latency Targets**:
   - `auth` dry-run: $\le$ 1.0s (achieved: **0.82s**, down from 16.1s)
   - `status --service jellyfin`: $\le$ 0.8s (achieved: **0.48s**)
   - `download-numberblocks --dry-run`: $\le$ 1.0s (achieved: **0.69s**, down from 4.58s)
   - `sync-maruko --dry-run`: $\le$ 0.2s (achieved: **0.15s**)
