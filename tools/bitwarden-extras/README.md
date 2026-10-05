# Bitwarden Extras (`bw-vault`)

A modern Python 3.14+ toolkit for power users of Bitwarden. 

Features:
- **In-Memory SQLite Engine:** Query your entire vault using full SQL (`SELECT`, `JOIN`, `GROUP BY`, regex, json extraction) with sub-millisecond query speed and an interactive REPL (`bw-vault query`).
- **Safe Sanitized Metadata Export:** Extract structured YAML or JSON metadata across all items and folders with strict zero-secret leakage (passwords, TOTP seeds, PINs, and hidden fields strictly stripped).
- **Smart Cloud Auto-Sync:** Automatically pulls down edits made in your browser or mobile app if your local cache is older than 5 minutes, with `--sync` and `--no-sync` flags, manual `bw-vault sync`, and hot-reloading `.sync` command inside the REPL.
- **Accurate Empty-State Tracking:** Distinguishes genuine `NULL` unfiled items (`is_unfiled`) and unnamed items (`is_unnamed`) without artificial string placeholders.
- **Audit Recent Changes:** Populates `revision_date` and `creation_date` in SQL tables so you can audit what was modified recently.
- **Vault Cleaner (`clean-blank-notes`):** Safely cleans up phantom control characters (e.g. `0x10`) and empty notes with atomic read-modify-write safety guards and cloud synchronization.
- **Strong Typing with Pydantic 2:** Validated schemas and computed domain parsing.

---

## Installation & Setup

Using [`uv`](https://docs.astral.sh/uv/):

```bash
cd ~/dotfiles/tools/bitwarden-extras
uv sync
```

To run directly via `uv`:
```bash
uv run bw-vault --help
```

To install globally into your `~/.local/bin` / PATH:
```bash
uv tool install --editable ~/dotfiles/tools/bitwarden-extras
```

---

## Usage Guide

### 1. In-Memory SQL Querying

#### Run one-off SQL queries:
```bash
# Count total items and legitimate notes:
bw-vault query "SELECT count(*) AS total, count(notes) AS with_notes FROM items"

# Find unfiled items in the root vault:
bw-vault query "SELECT name, type, revision_date FROM vault WHERE is_unfiled"

# Inspect recently updated items:
bw-vault query "SELECT name, folder, revision_date FROM items ORDER BY revision_date DESC LIMIT 5"

# Group items by folder:
bw-vault query "SELECT COALESCE(folder, '(Unfiled)') AS folder, count(*) FROM items GROUP BY folder ORDER BY count(*) DESC"
```

#### Launch Interactive SQLite REPL:
```bash
bw-vault query
```
Commands inside the REPL:
* `vault> .schema` - View table and view definitions.
* `vault> .sync` - Re-sync with Bitwarden cloud and hot-reload in-memory tables.
* `vault> exit` or `quit` - Exit the REPL.

---

### 2. Sanitized Metadata Export

Export sanitized vault structure (passwords and TOTP keys strictly excluded):

```bash
# Export to YAML:
bw-vault export --format yaml --output ~/vault_backup.yaml

# Export to JSON:
bw-vault export --format json --output ~/vault_backup.json

# Include documentation notes (passwords still excluded):
bw-vault export --include-notes
```

---

### 3. Cloud Synchronization

```bash
# Trigger an immediate cloud sync:
bw-vault sync

# Force sync before running a query:
bw-vault query --sync "SELECT count(*) FROM items"

# Bypass sync (offline mode):
bw-vault query --no-sync "SELECT count(*) FROM items"
```

---

### 4. Vault Cleaner (`clean-blank-notes`)

Detect and wipe phantom ASCII control characters (such as `\x10` DLE) and empty notes across your vault:

```bash
# Dry run (inspect affected items without modifying):
bw-vault clean-blank-notes --dry-run

# Execute cleanup with confirmation:
bw-vault clean-blank-notes

# Execute cleanup without interactive prompt:
bw-vault clean-blank-notes --yes
```

---

## Testing & Quality

Run the test suite:
```bash
uv run pytest
```

Run linting and formatting:
```bash
uv run ruff check
uv run ruff format --check
```
