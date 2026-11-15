# Implementation Plan: Unified `uv` Workspace Restructuring

**Date:** 2026-11-15  
**Status:** Ready for Execution  
**Reference Research:** [01_research.md](file:///home/ehtesh/dotfiles/thoughts/2026-11-15-uv-workspace-restructure/01_research.md)

---

## 1. Objectives

1. Restructure the repository into a single unified **`uv` Workspace** rooted at `/home/ehtesh/dotfiles/`.
2. Move `homelab/status`, `homelab/auth`, and `homelab/scripts` to standard `src/` layout (`src/homelab_status`, `src/homelab_auth`, `src/homelab_scripts`) to eliminate top-level module collisions (`common.py`, `config.py`, `models.py`) in the shared virtual environment.
3. Centralize shared linting (`[tool.ruff]`), type checking (`[tool.ty.rules]`), and test tooling (`[dependency-groups] dev`) in root `dotfiles/pyproject.toml`, removing ~80 lines of duplicate boilerplate from each member project.
4. Modernize auxiliary scripts (`bin/extract.py`, `bin/turn_off.py`, and `tools/soju-extras/contrib/weechat_read_markers.py`) to conform to modern Python 3, `whenever>=0.11.0`, strict Ruff, and Ty standards.
5. Unify all dependencies into a single root `dotfiles/uv.lock` and shared `dotfiles/.venv/`, reducing virtual environment disk usage by ~220 MB.
6. Guarantee 100% test passing (312/312 tests) and zero Ruff or Ty diagnostics across the entire repository.

---

## 2. Implementation Checklist

### Phase 1: Modernize Auxiliary Scripts (`bin/` and `contrib/`)
- [x] **1.1. Modernize `bin/extract.py`**
  - Replace Python 2 `print >>sys.stderr` with `print(..., file=sys.stderr)`.
  - Use `Path(path).mkdir(parents=True, exist_ok=True)` and `shutil.which()`.
  - Add type annotations and clean imports to pass strict Ruff and Ty checks.
- [x] **1.2. Modernize `bin/turn_off.py`**
  - Add parentheses to `print(display.next_event())`.
  - Replace `str.split()` in subprocess calls with list literals.
- [x] **1.3. Modernize `tools/soju-extras/contrib/weechat_read_markers.py`**
  - Migrate `datetime` to `whenever.Instant`:
    `Instant.from_timestamp(seconds).add(nanoseconds=microseconds * 1000).format_iso(unit="millisecond")`.
  - Prefix unused callback arguments required by C API (`_data`, `_handle`, `_object_id`).
  - Rename shadowing arguments to descriptive names (`license_name` and `property_name`).
  - Add quotes to `cast("WeeChat", ...)`.
  - Verify against `tools/soju-extras/tests/test_weechat_marker_export.py`.

---

### Phase 2: Root Workspace Definition
- [x] **2.1. Create root `/home/ehtesh/dotfiles/pyproject.toml`**
  - Define `[tool.uv.workspace]` with members:
    - `"homelab/status"`
    - `"homelab/auth"`
    - `"homelab/scripts"`
    - `"tools/bitwarden-extras"`
    - `"tools/soju-extras"`
  - Define `[dependency-groups] dev = ["pytest>=8.0.0", "ruff>=0.16.1", "ty>=0.0.95"]`.
  - Define root `[tool.ruff]` with `target-version = "py314"`, `line-length = 120`.
  - Define root `[tool.ruff.lint]` with the 33 strict rule selects and 7 standard ignores.
  - Define root `[tool.ruff.lint.per-file-ignores]` for `tests/*`.
  - Define root `[tool.ruff.lint.flake8-tidy-imports.banned-api]` banning standard library `datetime` (`TID251`).
  - Define root `[tool.ruff.format]` with double quotes and space indentation.
  - Define root `[tool.ty.rules]` with all 20 elevated error rules.
  - Define root `[tool.pytest.ini_options]` with `addopts = ["--import-mode=importlib"]` to prevent duplicate test file collection collisions across workspace members.

---

### Phase 3: Restructure `homelab/status` into `src/homelab_status`
- [x] **3.1. Establish `src/` package layout via `git mv`**
  - Create directory `homelab/status/src/homelab_status/`.
  - `git mv` `commands/`, `services/`, `common.py`, `config.py`, `main.py`, and `models.py` into `src/homelab_status/`.
  - Create `src/homelab_status/__init__.py`.
- [x] **3.2. Adjust path discovery in `src/homelab_status/config.py`**
  - Update `Path(__file__).resolve().parent.parent` to `parents[3]` so homelab root `.env` is discovered correctly at the increased directory depth.
- [x] **3.3. Update imports in `homelab_status` and its tests**
  - Update internal imports to package imports (`from homelab_status...`).
  - Update tests in `homelab/status/tests/` to import from `homelab_status`.
- [x] **3.4. Update `homelab/status/pyproject.toml`**
  - Update `[project.scripts]` to point to `homelab_status.main:app`.
  - Set `packages = ["src/homelab_status"]` in `[tool.hatch.build.targets.wheel]`.
  - Set `pythonpath = ["src"]` in `[tool.pytest.ini_options]`.
  - Remove duplicate `[tool.ruff]`, `[tool.ty.rules]`, and `[dependency-groups] dev`.

---

### Phase 4: Restructure `homelab/auth` into `src/homelab_auth`
- [x] **4.1. Establish `src/` package layout via `git mv`**
  - Create directory `homelab/auth/src/homelab_auth/`.
  - `git mv` `services/`, `cli.py`, `common.py`, `compose.py`, `config.py`, `http_models.py`, `main.py`, and `models.py` into `src/homelab_auth/`.
  - Create `src/homelab_auth/__init__.py`.
- [x] **4.2. Adjust path discovery in `src/homelab_auth/config.py`**
  - Update `ROOT = Path(__file__).resolve().parents[1]` to `parents[3]` so `docker-compose.yml` and `.env` are resolved correctly from homelab root.
- [x] **4.3. Update imports in `homelab_auth` and its tests**
  - Update internal imports to package imports (`from homelab_auth...`).
  - Update tests in `homelab/auth/tests/` to import from `homelab_auth`.
- [x] **4.4. Update `homelab/auth/pyproject.toml`**
  - Update `[project.scripts]` to point to `homelab_auth.cli:typer_main`.
  - Set `packages = ["src/homelab_auth"]` in `[tool.hatch.build.targets.wheel]`.
  - Set `pythonpath = ["src"]` in `[tool.pytest.ini_options]`.
  - Remove duplicate `[tool.ruff]`, `[tool.ty.rules]`, and `[dependency-groups] dev`.

---

### Phase 5: Restructure `homelab/scripts` into `src/homelab_scripts`
- [x] **5.1. Establish `src/` package layout via `git mv`**
  - Create directory `homelab/scripts/src/homelab_scripts/`.
  - `git mv` scripts and metadata files (`download_anpanman.py`, `download_numberblocks.py`, `build_anpanman_metadata.py`, `build_maruko_metadata.py`, `sync_maruko.py`, `jellyfin.py`, and `*.json`) into `src/homelab_scripts/`.
  - Create `src/homelab_scripts/__init__.py`.
- [x] **5.2. Update imports in `homelab_scripts` and its tests**
  - Convert bare sibling imports (`import jellyfin`) to `from homelab_scripts import jellyfin`.
  - Update `homelab/scripts/tests/test_metadata_integrity.py` to load JSON metadata from `src/homelab_scripts/`.
  - Update all tests in `homelab/scripts/tests/` to import from `homelab_scripts`.
- [x] **5.3. Update `homelab/scripts/pyproject.toml`**
  - Update `[project.scripts]` entry points to point to `homelab_scripts.*:main`.
  - Set `packages = ["src/homelab_scripts"]` in `[tool.hatch.build.targets.wheel]`.
  - Set `pythonpath = ["src"]` in `[tool.pytest.ini_options]`.
  - Remove duplicate `[tool.ruff]`, `[tool.ty.rules]`, and `[dependency-groups] dev`.

---

### Phase 6: Clean Up `tools/bitwarden-extras` & `tools/soju-extras`
- [x] **6.1. Streamline `tools/bitwarden-extras/pyproject.toml`**
  - Retain `[project]` metadata, dependencies, and entrypoints.
  - Remove duplicate `[tool.ruff]`, `[tool.ty.rules]`, and `[dependency-groups] dev` (inherited from root).
- [x] **6.2. Streamline `tools/soju-extras/pyproject.toml`**
  - Retain `[project]` metadata, dependencies, and entrypoints.
  - Remove duplicate `[tool.ruff]`, `[tool.ty.rules]`, and `[dependency-groups] dev` (inherited from root).

---

### Phase 7: Lockfile & Environment Unification
- [x] **7.1. Generate workspace lockfile**
  - Run `uv lock` from `/home/ehtesh/dotfiles/`.
  - Verify clean resolution of unified `dotfiles/uv.lock`.
- [x] **7.2. Sync unified virtual environment**
  - Run `uv sync` from `/home/ehtesh/dotfiles/`.
  - Verify `.venv/bin/` contains all CLI binaries: `status`, `auth`, `download-anpanman`, `bw-vault`, `soju-backup`, `pytest`, `ruff`, `ty`.
- [x] **7.3. Clean up legacy artifacts**
  - Remove redundant member lockfiles: `homelab/status/uv.lock`, `homelab/auth/uv.lock`, `homelab/scripts/uv.lock`, `tools/bitwarden-extras/uv.lock`, `tools/soju-extras/uv.lock`.
  - Remove legacy subproject `.venv/` directories to free up disk space.

---

### Phase 8: Verification & Acceptance Testing
- [x] **8.1. Run unified test suite**
  - Execute `uv run pytest` from `/home/ehtesh/dotfiles/`.
  - Verify all 312 tests pass (78 status + 29 auth + 33 scripts + 25 bitwarden + 147 soju).
- [x] **8.2. Run unified lint and formatting checks**
  - Execute `uv run ruff check .` from root -> 0 diagnostics.
  - Execute `uv run ruff format --check .` from root -> 0 formatting changes.
- [x] **8.3. Run unified type checker**
  - Execute `uv run ty check homelab tools bin` from root -> 0 type errors.
- [x] **8.4. Verify CLI entry points**
  - Test `status --help`
  - Test `auth --help`
  - Test `download-anpanman --help`
  - Test `bw-vault --help`
  - Test `soju-backup --help`

---

## 3. Success Criteria
1. Single root workspace lockfile (`uv.lock`) and virtual environment (`.venv/`) at `/home/ehtesh/dotfiles/`.
2. All 5 member `pyproject.toml` files reduced by ~80 lines of duplicate configuration.
3. 312 / 312 tests passing via single `uv run pytest`.
4. 0 Ruff diagnostics and 0 Ty errors repo-wide (including `bin/extract.py` and `weechat_read_markers.py`).
5. All CLI commands operational without modification to shell scripts or systemd unit definitions.
