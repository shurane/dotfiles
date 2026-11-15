# Research: Unifying Python Projects into a `uv` Workspace

**Date:** 2026-11-15  
**Status:** Complete  
**Scope:** Repository-wide (`homelab/status`, `homelab/auth`, `homelab/scripts`, `tools/bitwarden-extras`, `tools/soju-extras`)

---

## 1. Executive Summary

The repository currently maintains 5 isolated Python packages, each with its own `pyproject.toml`, `uv.lock`, and `.venv/` folder. This results in:
- **341 MB of duplicate virtual environment storage** (`auth`: 102M, `scripts`: 110M, `status`: 57M, `bitwarden`: 42M, `soju`: 30M).
- **Repetitive maintenance overhead**: Every time Ruff rules or Ty type-checking configurations are updated, ~80 lines of identical configuration must be manually synchronized across all 5 `pyproject.toml` files.
- **Fragmented developer experience**: Running tests or lint checks requires navigating into 5 directories or chaining 5 separate commands.

By restructuring the repository into a single unified **`uv` Workspace** rooted at `/home/ehtesh/dotfiles/`, we achieve:
1. A single shared `.venv/` (~120 MB total) containing all packages and CLI entry points.
2. A single `uv.lock` resolving all dependencies with zero version conflicts.
3. Centralized linting and type-checking rules defined once in `dotfiles/pyproject.toml` and automatically inherited by all members.
4. One-shot verification: `uv run pytest`, `uv run ruff check .`, and `uv run ty check .` executed from the repository root.

---

## 2. Key Technical Findings & Architectural Requirements

### A. Module Collision in Shared Virtual Environments (Crucial Finding)
In a `uv` workspace, all workspace members are installed into the shared root `.venv/` as editable packages.
- `tools/bitwarden-extras` and `tools/soju-extras` already use the standard `src/` layout (`src/bitwarden_extras` and `src/soju_extras`). They are safely namespaced.
- However, `homelab/status` and `homelab/auth` currently use flat root directories containing identically named top-level modules:
  - `status`: `common.py`, `config.py`, `models.py`, `main.py`, `services/`, `commands/`
  - `auth`: `common.py`, `config.py`, `models.py`, `main.py`, `services/`, `compose.py`, `cli.py`
- If installed as editable packages into the same `.venv` without namespacing, their top-level modules collide and overwrite each other in `site-packages`.
- **Architectural Solution**: Migrate `homelab/status`, `homelab/auth`, and `homelab/scripts` to standard `src/` layouts:
  - `homelab/status/src/homelab_status/`
  - `homelab/auth/src/homelab_auth/`
  - `homelab/scripts/src/homelab_scripts/`
  This eliminates collision risk and aligns the entire repository with standard modern packaging practices.

### B. Dependency Version Compatibility
Inspection and temporary workspace simulation confirmed **zero dependency conflicts**:
- **Python Version**: All projects are compatible with Python 3.14 (`requires-python = "==3.14.*"`).
- **Shared Libraries**: `whenever>=0.11.0`, `rich>=13.0.0`, `httpx>=0.28.1`, `anyio>=4.8.0`, `pydantic>=2.10.0`, `typer>=0.12.5` have compatible `>=` bounds.
- **Dev Tooling**: `pytest>=8.0.0`, `ruff>=0.16.1`, and `ty>=0.0.95` are 100% unified.

### C. Configuration Inheritance
We empirically validated with Ruff and Ty:
- Both tools walk up parent directories to discover configuration.
- By placing `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.ruff.format]`, and `[tool.ty.rules]` in root `dotfiles/pyproject.toml`, member `pyproject.toml` files shrink from ~140 lines down to ~25–35 lines.
- All 33 strict Ruff rules, formatting rules, `TID251` (banned stdlib datetime), and 20 elevated Ty error rules are enforced uniformly across every package.

### D. Deployment Context (`m70q.lan` & `raspy.lan`)
- IRC services (Soju and WeeChat) have been fully migrated to `m70q.lan`. `raspy.lan` is no longer running IRC services.
- `m70q.lan` hosts both homelab services (`status`, `auth`) and `soju-extras`.
- Consequently, a root `uv sync` on `m70q.lan` cleanly deploys all tools into `/home/ehtesh/dotfiles/.venv/bin/` with zero special casing.
