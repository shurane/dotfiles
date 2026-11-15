# Research: Migrating to Encapsulated `packages/` Workspace (Choice 1)

**Date:** 2026-11-15  
**Target:** Restructure `/home/ehtesh/dotfiles` to encapsulate all Python packages and workspace files under `/home/ehtesh/dotfiles/packages/`.

---

## 1. Context & Motivation

In the current setup:
- Root `/home/ehtesh/dotfiles` hosts `pyproject.toml`, `uv.lock`, and `.venv/`.
- `homelab/` contains Docker Compose infrastructure (`docker-compose.yml`, `.env`, service directories) mixed with 3 Python packages (`homelab/status`, `homelab/auth`, `homelab/scripts`).
- `tools/` contains 2 Python packages (`tools/bitwarden-extras`, `tools/soju-extras`).

**User Decision**:
Adopt **Choice 1**:
- Encapsulate all Python packages in `/home/ehtesh/dotfiles/packages/`.
- Move the workspace root configuration (`pyproject.toml`, `uv.lock`, `.venv/`) entirely into `packages/`.
- Keep `/home/ehtesh/dotfiles/` root completely clean of Python project files (no `pyproject.toml`, `uv.lock`, or `.venv/` at dotfiles root).
- Keep `/home/ehtesh/dotfiles/homelab/` strictly for Docker Compose and infrastructure.
- Remove empty `tools/` directory.

---

## 2. Directory Layout Migration

### Current Layout
```
dotfiles/
├── pyproject.toml              # Root workspace
├── uv.lock                     # Root lockfile
├── .venv/                      # Root virtualenv
├── bin/
│   ├── extract.py
│   └── turn_off.py
├── homelab/
│   ├── docker-compose.yml
│   ├── .env
│   ├── caddy/
│   ├── ...
│   ├── status/                 # Package: homelab-status
│   ├── auth/                   # Package: homelab-auth
│   └── scripts/                # Package: homelab-scripts
└── tools/
    ├── bitwarden-extras/       # Package: bitwarden-extras
    └── soju-extras/            # Package: soju-extras
```

### Target Layout (Choice 1)
```
dotfiles/
├── homelab/                    # 100% Docker Compose & infra
│   ├── docker-compose.yml
│   ├── .env
│   ├── caddy/
│   ├── jellyfin/
│   ├── qbittorrent/
│   ├── samba/
│   └── ...
├── bin/                        # Standalone scripts (extract.py, turn_off.py)
└── packages/                   # 🐍 Fully encapsulated Python workspace
    ├── pyproject.toml          # Workspace root: members = ["*"]
    ├── uv.lock                 # Unified lockfile
    ├── .venv/                  # Unified virtual environment
    ├── homelab-status/         # (from homelab/status)
    ├── homelab-auth/           # (from homelab/auth)
    ├── homelab-scripts/        # (from homelab/scripts)
    ├── bitwarden-extras/       # (from tools/bitwarden-extras)
    └── soju-extras/            # (from tools/soju-extras)
```

---

## 3. Files to Move & Modify

### A. Move Operations (via `git mv`)
1. `homelab/status` -> `packages/homelab-status`
2. `homelab/auth` -> `packages/homelab-auth`
3. `homelab/scripts` -> `packages/homelab-scripts`
4. `tools/bitwarden-extras` -> `packages/bitwarden-extras`
5. `tools/soju-extras` -> `packages/soju-extras`
6. `pyproject.toml` -> `packages/pyproject.toml`
7. `uv.lock` -> `packages/uv.lock`

### B. Configuration Files to Modify
1. **`packages/pyproject.toml`**:
   - `[tool.uv.workspace]`: `members = ["*"]` or explicit list:
     ```toml
     members = [
       "homelab-status",
       "homelab-auth",
       "homelab-scripts",
       "bitwarden-extras",
       "soju-extras",
     ]
     ```
   - `[tool.pytest.ini_options]`:
     ```toml
     addopts = ["--import-mode=importlib"]
     pythonpath = ["soju-extras"]
     testpaths = [
       "homelab-status/tests",
       "homelab-auth/tests",
       "homelab-scripts/tests",
       "bitwarden-extras/tests",
       "soju-extras/tests",
     ]
     ```
   - `[tool.ruff]`:
     `extend-exclude = ["soju-extras/benchmarks", "soju-extras/tmp"]` (since `homelab/jellyfin` and `homelab/withings-sync` are outside `packages/`, they no longer need to be excluded here).
   - `[tool.ty.src]`:
     Remove `homelab/jellyfin/**` and `homelab/withings-sync/**` (they are no longer in scope).

2. **`packages/homelab-status/src/homelab_status/config.py`**:
   - Depth update for relative path search:
     `Path(__file__).resolve().parents[4] / "homelab" / ".env"`
     (parents[0]=homelab_status, parents[1]=src, parents[2]=homelab-status, parents[3]=packages, parents[4]=dotfiles).
   - Also retains fallback `Path.home() / "dotfiles" / "homelab" / ".env"`.

3. **`packages/homelab-auth/src/homelab_auth/config.py`**:
   - Update `ROOT`:
     `ROOT = Path(__file__).resolve().parents[4] / "homelab"`
     This correctly resolves `dotfiles/homelab` where `docker-compose.yml` and `.env` live.

4. **`packages/homelab-scripts/src/homelab_scripts/download_anpanman.py`**:
   - Update fallback cache path in `load_anpanman_metadata()` to check `packages/homelab-scripts/src/homelab_scripts/anpanman_metadata.json`.

5. **`homelab/README.md`**:
   - Update documentation references to reflect the clean separation of Docker Compose commands vs CLI tool invocation.

---

## 4. Potential Side-Effects & Mitigations

1. **Top-Level `uv` Execution**:
   - *Impact*: Running `uv run pytest` from `dotfiles/` root will no longer find a `pyproject.toml` in `dotfiles/`.
   - *Mitigation*: Run with `uv run --project packages pytest` from `dotfiles/` root, or `cd packages && uv run pytest`.
2. **Neovim / Editor LSP**:
   - *Impact*: Language servers (Pyright/Ty/Ruff) opening files in `packages/` will discover `packages/pyproject.toml` as root.
   - *Resolution*: This is the standard behavior in multi-project repositories; opening `packages/` or any file inside it attaches cleanly to `packages/.venv`.
3. **Binaries in `~/.local/bin/`**:
   - *Impact*: Existing symlinks in `~/.local/bin/` point to `~/.local/share/uv/tools/...` created by `uv tool install`.
   - *Resolution*: `uv tool install ./packages/homelab-status --force` etc. updates the tools cleanly.
