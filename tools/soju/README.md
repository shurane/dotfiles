# soju-tools

Modern Python 3.14 toolkit for Soju IRC bouncer:
- **`sojugrep`**: Instant FTS5 full-text search across Soju SQLite IRC backlog.
- **`soju-export-fs`**: Daily incremental mirror of Soju SQLite messages to compressed flat logs (`.log.gz`).
- **`weechat-to-soju`**: High-performance parser and bulk importer from WeeChat logs into Soju.

## Installation

```bash
uv tool install --editable .
```

Installs `sojugrep`, `soju-export-fs`, and `weechat-to-soju` into `~/.local/bin/`.
