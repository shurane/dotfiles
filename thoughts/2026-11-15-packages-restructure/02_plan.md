# Implementation Plan: Encapsulated `packages/` Workspace Restructuring (Choice 1)

**Date:** 2026-11-15  
**Status:** Ready for Execution  
**Reference Research:** [01_research.md](file:///home/ehtesh/dotfiles/thoughts/2026-11-15-packages-restructure/01_research.md)

---

## 1. Objectives

1. Restructure `/home/ehtesh/dotfiles` into a pure dotfiles repository where all Python packages and their workspace infrastructure are fully encapsulated inside `packages/`.
2. Move `homelab/status`, `homelab/auth`, and `homelab/scripts` out of `homelab/` into `packages/homelab-status`, `packages/homelab-auth`, and `packages/homelab-scripts`.
3. Move `tools/bitwarden-extras` and `tools/soju-extras` out of `tools/` into `packages/bitwarden-extras` and `packages/soju-extras`.
4. Relocate `pyproject.toml` and `uv.lock` from the repository root to `packages/pyproject.toml` and `packages/uv.lock`.
5. Remove the root `.venv/` and regenerate a unified `.venv/` inside `packages/.venv/`.
6. Update relative path references in `homelab_status` and `homelab_auth` to point across to `dotfiles/homelab/`.
7. Guarantee 100% test pass rate (338/338 tests), 0 Ruff diagnostics, and 0 Ty errors from within the new `packages/` workspace root.

---

## 2. Implementation Checklist

### Phase 1: Directory Preparation and Package Migration
- [x] **1.1. Create `packages/` directory**
  - Run `mkdir -p /home/ehtesh/dotfiles/packages`.
- [x] **1.2. Move packages via `git mv`**
  - `git mv homelab/status packages/homelab-status`
  - `git mv homelab/auth packages/homelab-auth`
  - `git mv homelab/scripts packages/homelab-scripts`
  - `git mv tools/bitwarden-extras packages/bitwarden-extras`
  - `git mv tools/soju-extras packages/soju-extras`
- [x] **1.3. Clean up obsolete parent directories**
  - Remove empty `tools/` directory if git left empty directory behind.
  - Verify `homelab/` now only contains Docker Compose infrastructure and service directories.

---

### Phase 2: Relocate and Update Workspace Configuration
- [x] **2.1. Relocate root workspace configuration to `packages/`**
  - `git mv pyproject.toml packages/pyproject.toml`
  - `git mv uv.lock packages/uv.lock`
- [x] **2.2. Update `packages/pyproject.toml`**
  - Update `[tool.uv.workspace]` members:
    ```toml
    [tool.uv.workspace]
    members = [
      "homelab-status",
      "homelab-auth",
      "homelab-scripts",
      "bitwarden-extras",
      "soju-extras",
    ]
    ```
  - Update `[tool.pytest.ini_options]`:
    - `pythonpath = ["soju-extras"]`
    - `testpaths = ["homelab-status/tests", "homelab-auth/tests", "homelab-scripts/tests", "bitwarden-extras/tests", "soju-extras/tests"]`
  - Update `[tool.ruff]`:
    - `extend-exclude = ["soju-extras/benchmarks", "soju-extras/tmp"]`
  - Clean up `[tool.ty.src]`:
    - Remove obsolete exclusions for `homelab/jellyfin/**` and `homelab/withings-sync/**` (they are not in `packages/`).

---

### Phase 3: Update Path Discovery in Homelab Packages
- [x] **3.1. Update `packages/homelab-status/src/homelab_status/config.py`**
  - Added dynamic upward discovery `find_homelab_env()` terminating at `.git` or filesystem root.
- [x] **3.2. Update `packages/homelab-auth/src/homelab_auth/config.py`**
  - Added dynamic upward discovery `find_homelab_root()` terminating at `.git` or filesystem root.
- [x] **3.3. Update `packages/homelab-scripts/src/homelab_scripts/download_anpanman.py`**
  - Update fallback path in `load_anpanman_metadata()` to check `packages/homelab-scripts/src/homelab_scripts/anpanman_metadata.json`.

---

### Phase 4: Virtual Environment & Lockfile Synchronization
- [x] **4.1. Remove legacy root `.venv`**
  - `rm -rf /home/ehtesh/dotfiles/.venv`
- [x] **4.2. Lock and sync in `packages/`**
  - Run `cd /home/ehtesh/dotfiles/packages && uv lock`
  - Run `cd /home/ehtesh/dotfiles/packages && uv sync`
  - Verify `packages/.venv/bin/` contains all CLI binaries: `status`, `auth`, `download-anpanman`, `bw-vault`, `soju-backup`.

---

### Phase 5: Verification & Acceptance Testing
- [x] **5.1. Run unified test suite**
  - Run `uv run pytest` from `/home/ehtesh/dotfiles/packages`.
  - Verify all 338 tests pass.
- [x] **5.2. Run unified linting and formatting**
  - Run `uv run ruff check .` and `uv run ruff format --check .` from `/home/ehtesh/dotfiles/packages`.
  - Verify 0 errors / 0 formatting diffs.
- [x] **5.3. Run unified type checker**
  - Run `uv run ty check .` from `/home/ehtesh/dotfiles/packages`.
  - Verify 0 errors.
- [x] **5.4. Verify root execution via `--project packages`**
  - Run `uv run --project packages pytest` from `/home/ehtesh/dotfiles`.
  - Run `uv run --project packages ruff check packages`.
  - Run `uv run --project packages ty check packages`.
- [x] **5.5. Verify CLI entry points**
  - Test `uv run --project packages status --help`
  - Test `uv run --project packages auth --help`
  - Test `uv run --project packages download-anpanman --help`
  - Test `uv run --project packages bw-vault --help`
  - Test `uv run --project packages soju-backup --help`

---

## 3. Success Criteria
1. `/home/ehtesh/dotfiles` root contains no `pyproject.toml`, `uv.lock`, or `.venv/`.
2. `/home/ehtesh/dotfiles/homelab/` contains only Docker Compose infrastructure and service configs.
3. All 5 Python packages cleanly live in `packages/` with 1:1 directory-to-package names.
4. All 338 tests pass, Ruff reports 0 issues, and Ty reports 0 type errors.
5. All CLI entry points operate properly with zero configuration overhead.
