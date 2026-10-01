# soju-extras

Python 3.14+ tools for Soju's SQLite message history:

- `sojugrep`: full-text search, with literal terms or explicit FTS5 syntax.
- `soju-export-fs`: incremental export to daily text or gzip logs.
- `weechat-to-soju`: repeatable imports of plain, gzip, or zstd WeeChat logs.

## Install and check

```sh
uv tool install --editable .
uv run pytest
uv run pyright
uv run ty check
uv run ruff check .
uv run ruff format --check .
```

Pyright uses strict mode for application code. Pydantic validates CLI options,
SQLite result rows, parsed records, and export recovery metadata. SQLite values
become concrete models before application code uses them.

The database layer uses stdlib `sqlite3`. Connections, cursors, transactions,
input streams, gzip streams, temporary files, and export locks have explicit
context managers. Transactions roll back on exceptions, including interruption.
Async database access would be useful in an application that must keep an event
loop responsive; these sequential CLI operations use synchronous bulk SQL.

## Connection, query, and transaction contexts

Use `open_soju_db()` for the connection lifetime and `query()` for a streaming,
typed result. Every row is validated as it is consumed. The query closes both
its iterator and its cursor when the block exits, including on `break`, `return`,
validation errors, and interruptions. Do not retain the iterator beyond the block.

```python
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from soju_extras.db import open_soju_db, query


class Target(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    id: int
    target: str


with open_soju_db(Path("/var/lib/soju/main.db"), readonly=True) as db:
    with query(db, Target, "SELECT id, target FROM MessageTarget") as targets:
        for target in targets:  # target is statically typed as Target
            print(target.id, target.target)
```

`query_rows()` remains a convenience for small or SQL-limited results; it uses
the same query context internally and returns a list. The exporter streams its
database rows into each bounded output batch without keeping an intermediate
list of database-row models.

Writes belong inside `with transaction(db):`. `execute()` and `execute_many()`
manage cursor cleanup but do not commit the surrounding transaction.
`execute_many()` accepts an iterable, so callers can supply bounded batches or
a generator. A failed input iterator or failed commit rolls back the transaction.
An `INSERT ... RETURNING` query also belongs inside the transaction; exiting
its query context does not commit it. Transaction contexts must not be nested.

The native `sqlite3.Connection` context manager does not close a connection,
and it does not manage transactions when `autocommit=True`. This project uses
`contextlib.closing()` for resource ownership and explicit SQL transaction scopes
to support `BEGIN IMMEDIATE` for writes and deferred staging transactions.
See the [Python sqlite3 documentation](https://docs.python.org/3.14/library/sqlite3.html#how-to-use-the-connection-context-manager).

## Search

```sh
sojugrep 'hello world' '#python' --network libera
sojugrep 'hello NOT world' --raw-fts
sojugrep 'c++' --db-path /var/lib/soju/main.db
```

The default quotes each whitespace-separated term and requires all terms to
match. Punctuation still follows SQLite's tokenizer behavior; it is not a byte
substring search. `--raw-fts` passes SQLite FTS5 syntax through unchanged,
including quoted phrases and boolean operators. Invalid syntax is an error.

Exit status: **0** for matches, **1** for no matches, **2** for errors.
Color is disabled when output is redirected. Unnamed networks display their
server address and can be selected by that address.

## Import

```sh
weechat-to-soju --logs-dir ~/.local/share/weechat/logs --username shurane
weechat-to-soju --logs-dir ./logs --timezone America/Chicago
weechat-to-soju --network-map libera=irc.libera.chat:6697
weechat-to-soju --logs-dir ./logs --dry-run
```

Timestamps without an offset default to **UTC**. Explicit offsets take
precedence over `--timezone`. `whenever` converts local times to instants and
rejects nonexistent or repeated DST wall times; resolve those timestamps with
an explicit offset in the source. Soju stores exactly milliseconds in UTC:
fractions below a millisecond are truncated. Invalid nonblank lines abort the
file and report its path and line number.

The user and networks must already exist in Soju. `--network-map LOG=NAME_OR_ADDRESS`
can be repeated, including for unnamed networks. The importer does not create
accounts or guess server addresses. `--mode db` remains accepted; the formerly
unimplemented `--mode fs` is rejected.

Imports stage one file in disk-backed SQLite temporary storage, using bounded
Python batches (`--batch-size`, default 5000). A final transaction inserts its
messages and leaves read and delivery receipts unchanged. Targets with no stored messages use a direct bulk insert; populated
targets perform the occurrence-count check. The emptiness check and insert run
under the same writer transaction, so another writer cannot invalidate the check. A failed file leaves its message history unchanged; previously
completed files remain committed. The final transaction holds SQLite's writer
lock, so a very large file can delay other writers.

Repeat detection uses **target, normalized timestamp, raw IRC message, and
occurrence count**. Two identical lines in one source remain two messages;
rereading that source inserts neither again. Overlapping source files contribute
the maximum occurrence count of each identity. Changed timestamps, timezone
interpretations, or message content create different identities. The tool does
not add permanent tables or indexes to Soju. Dry-run parses and validates input
without opening the database; it does not verify account/network resolution or
predict duplicate counts.

Discovery is recursive and supports unrotated and numbered rotations, including
gzip and zstd (`.weechatlog`, `.weechatlog.1`, `.weechatlog.2.gz`,
`.weechatlog.3.zst`). Zstd uses Python 3.14's `compression.zstd` module.
Each file reports eligible records and records excluded by the cutoff; committed
files report inserted counts. Core and IRC server logs are explicitly reported
as excluded. Unsupported `.weechatlog*` names and symlink files abort discovery
before writes; directory symlinks are not followed. No supported files is an
error. Custom logger masks need an explicit mapping/staging step. Keep different
machines' source logs in separate directories to avoid filename collisions.

Use `--since 2026-07-01T07:00:00Z` to include records starting at July 1, 2026,
midnight Pacific. The lower bound is inclusive; explicit offsets are recommended.
The parser still validates input outside the interval, so prepare a recent-only
tree first when older records have ambiguous timestamps.

Use `--before 2026-09-30T10:00:00Z` to exclude timestamps at or after a verified
cutover. This boundary defaults to UTC when no offset is supplied, independently
of `--timezone` for source records. Dry-run still validates excluded lines.
For populated targets, the default overlap guard rejects a file if an existing
message has the same sender and text within the same UTC second but different
raw IRC. This catches common live Soju versus WeeChat representations and uses
the existing target/time index. It is deliberately conservative: legitimate
repetitions can trigger it, and changed text, nick spelling, event messages, or
larger timestamp differences can evade it. It does not silently merge ambiguous
messages. `--allow-overlap` bypasses this check after review and may insert
duplicates; exact occurrence-based repeat detection still applies. Preserve a
cutover boundary and separate post-cutover logs even when this guard is enabled.

### Transferring read markers

Logs contain messages, not evidence of what was read. The importer preserves
existing receipts by default. Explicit markers can be supplied with
`--read-markers markers.json`:

```json
{"version": 1, "markers": [{"network": "libera", "target": "#python", "timestamp": "2026-09-20T12:34:56.123Z"}]}
```

Pydantic validates this document before any message imports. Timestamps require
an explicit offset. Markers are applied together in a separate transaction only
after all log files succeed, using `--network-map` as needed. Known targets use their stored ASCII casing;
ambiguous casing fails, and network-specific punctuation case mapping still
requires verification. Later existing
receipts are preserved; missing markers and delivery receipts remain unchanged.
Marker resolution failure rolls back all marker changes; previously committed
message files remain imported. Dry-run validates marker syntax without touching
the database or resolving identities.

Load `contrib/weechat_read_markers.py` in WeeChat and run:

```text
/soju_read_markers /absolute/path/markers.json
```

This reads live IRC buffers without changing markers. For an upgrade snapshot,
copy `weechat.upgrade` to `snapshot.upgrade` inside a separate WeeChat profile's
data directory, load only the Python plugin with `--no-connect --no-script`, and
run `/soju_read_markers /absolute/path/markers.json snapshot`. The script uses
WeeChat's own upgrade reader; it does not restore sessions or connect to servers.
The output must not already exist. It records the saved last-read line timestamp, including markers on JOINs,
numerics, and untagged lines. Buffers flagged with all retained lines unread appear in the explicit `unread`
list. Other missing markers appear in `unresolved`. No receipt is invented for
unread buffers. If Soju already has a receipt for one, transfer fails atomically
for reconciliation instead of silently accepting conflicting state. Unknown
entries leave their state unchanged. Unread applies to the retained snapshot
lines; it does not establish whether older history was ever read.
Timestamps are truncated to Soju's milliseconds, never rounded forward. Messages
sharing a millisecond cannot have distinct timestamp read positions. Historical
snapshots describe their saved state; use live extraction for fresher state.

Exit status: **0** on success, **2** on errors.

## Export

```sh
soju-export-fs --db-path /var/lib/soju/main.db --output-dir ./logs
soju-export-fs --output-dir ./logs --batch-size 5000
soju-export-fs --output-dir ./plain-logs --uncompressed
soju-export-fs --output-dir ./logs --dry-run
```

Logs are grouped by user, network, target, and UTC date. Names are reversibly
percent-encoded for filesystem safety; ordinary channel names such as `#python`
remain readable. Unnamed networks use their server address. Gzip output appends
standard concatenated gzip members for appends. Each run fixes an upper message ID so a
busy live database cannot extend that run indefinitely.

Daily files are chronological, including when older history is imported later.
Each batch is sorted within its destinations. Messages newer than a file's tail
are appended; backfills stream-merge with its archived contents into a replacement
file. Existing lines are retained even if database retention has deleted their
source messages. Equal timestamps preserve existing lines first, then new lines
in message-ID order. Touched files left unordered by older versions are repaired
using a disk-backed SQLite sort; untouched files are not proactively rewritten.

Memory is bounded by the configured batch size and the size of messages in
that batch. Before a batch changes files, a durable journal records append
lengths and replacement recovery paths. Replacements preserve a hard-link backup
of the original file until checkpointing completes. After writing and syncing
output, the exporter atomically replaces the checkpoint. On retry, uncommitted
appends are truncated (new files are removed), and uncommitted replacements are
restored from their backups. Committed batches are kept. A process lock prevents
overlapping exporters using the same output directory.

Backfilling a compressed daily file requires reading and recompressing it; a
legacy unordered file additionally needs temporary disk space for sorting.
Normal incremental appends remain available. A bounded cache of validated file
ordering avoids rescanning the same daily file for every batch in a run.

Keep the checkpoint, `.append-journal.json`, and `.export-config.json` with the
export. Each output directory must have its own checkpoint. Corrupt checkpoints,
missing checkpoints beside existing logs, and changes to database path or
compression mode are errors. Existing numeric `.last_synced_id` files remain
supported. The journal supports process-interruption recovery; it cannot repair
manual edits to already committed logs or identify every database restore/replacement.
It requires a local POSIX filesystem with working locking, fsync, and atomic rename.

Re-running normally resumes without duplicates. `--all` requires a fresh output
directory. `--since-id N` is exclusive and cannot move behind the checkpoint;
starting a fresh export at N intentionally omits earlier history. Checkpoints
advance by message ID while the daily file contents are ordered by timestamp.
Changing network names also changes output paths.
Dry-run validates pending records and paths without creating output files.

Exit status: **0** on success, **2** on errors.

## Explicit overlap between historical channel files

For a reviewed pair of duplicated histories, prepare immutable **plain** log
copies, then retain one intact and remove only shared occurrences from the other:

```sh
uv run python -m soju_extras.importer.overlap \
  --preferred 'originals/irc.libera.#c++.weechatlog' \
  --secondary 'originals/irc.libera.##c++.weechatlog' \
  --output 'prepared/irc.libera.##c++.weechatlog' > overlap-report.json
```

Copy the preferred file unchanged into `prepared` as well. Import only the
prepared directory. The output must not already exist. Originals remain intact;
SHA-256 checksums and occurrence counts are printed as JSON. Incomplete final
lines fail before output publication. Inputs must remain unchanged during the run.

Comparison includes the complete timestamp, prefix and message bytes, ignoring
only LF versus CRLF endings. If a record occurs twice in one file and once in the
other, two occurrences survive across the prepared pair. Unique records retain
their original channel and order. No channel renaming or read-marker rewriting
is performed. Do not apply this across arbitrary channels: shared QUIT events,
notices and identical messages can be legitimate. The helper uses a temporary
SQLite multiset, bounded Python memory and one transaction; no production database
is opened. Errors exit with status 2.

## Monthly historical archives and recent-only imports

After reconciling any explicitly approved overlapping files, split an immutable
plain-log snapshot into compressed monthly histories and a separate import tree:

```sh
uv run python -m soju_extras.importer.archive \
  --source ./reconciled --output ./partitioned \
  --since 2026-07-01 --timezone America/Los_Angeles --username shurane
```

The destination must not exist. The resulting layout is:

```text
partitioned/
  archives/shurane/libera/#c++/2026-06.weechatlog.zst
  archives/shurane/oftc/#fdroid/2026-06.weechatlog.zst
  import/irc.libera.#c++.weechatlog
  manifest.json
```

Each archive is an individual compressed WeeChat log, not a tar file. Source
timestamp spelling, messages, line endings, occurrence counts and relative order
within each output are preserved. Archives use the familiar user/network/target
layout, but contain WeeChat records, not Soju's ZNC-format records. Neither these
compressed archives nor their monthly naming are a live Soju filesystem store.

Month boundaries follow the supplied source timezone; offset-bearing timestamps
are converted only for choosing their bucket. Offset-free old DST timestamps can
be archived without inventing an instant. Recent records are validated by the
normal strict importer. One plain source file per network/target is required.

The tool streams records with bounded memory, reads back every output (including
decompression) and checks SHA-256 digests, bytes and record counts before publishing
the destination. The manifest records source/output digests, counts, compressed
sizes, timezone and cutoff. Failure leaves no published destination, so an unchanged
source can be retried. Originals are never edited. This is a new snapshot operation,
not an incremental archive updater; keep each snapshot's manifest with its files.

Import only the recent tree, with a matching inclusive lower bound:

```sh
weechat-to-soju --logs-dir ./partitioned/import \
  --timezone America/Los_Angeles --since 2026-07-01T07:00:00Z --dry-run
```

Records before that date remain in the archives and are unavailable to Soju clients.
This fixed migration cutoff does not enable ongoing expiry of newer Soju history.

## Tests and performance

Tests use the actual upstream Soju schema, pinned with its source and license in
[`tests/fixtures`](tests/fixtures/README.md). They cover FTS triggers, repeated
imports, transaction rollback, timestamps/DST, unnamed networks, CLI errors,
bounded batches, and subprocess death before and after checkpoint replacement.
They also verify recovery after partial gzip output, interruption around backfill
replacements, and preservation of archived messages deleted by database retention.

Run measurements in separate processes so peak RSS is comparable:

```sh
uv run python benchmarks/throughput.py export --messages 20000
uv run python benchmarks/throughput.py export --messages 200000
uv run python benchmarks/throughput.py import --messages 20000
uv run python benchmarks/throughput.py import --messages 200000
```

The benchmark reports elapsed operation time, messages/second, and peak process
RSS on Linux. Setup is excluded from timing but included in peak RSS. Its
synthetic input uses one channel, sequential timestamps and approximately
100-character messages; throughput depends on storage, compression, message
sizes and destination count. Imports include the real FTS maintenance triggers.

Estimate storage from an immutable local copy of real logs:

```sh
uv run python benchmarks/storage.py --logs-dir ./logs --timezone America/Los_Angeles
```

This streams plain, gzip, or zstd sources, samples 100 records per 10,000 per
file, and imports valid samples into a temporary database with the real schema.
It reports JSON with SQLite/FTS sizes and gzip/zstd source compression estimates;
import progress goes to stderr. `--sample-size`, `--stride`, and `--temp-dir`
control sampling and scratch storage. Source files are never changed. No SSH
connection or separate audit report is needed.

The report counts rejected sample records and explains sampling bias and omitted
storage costs. Unsampled records are not validated, and compression estimates do
not model daily or monthly output boundaries. Use a prepared recent-only source
tree to estimate a partial migration. Local reports and scratch scripts belong
in the ignored `tmp/` directory.

To compare commit frequency independently of parsing and duplicate detection:

```sh
uv run python benchmarks/transactions.py --messages 2000000
```

This benchmark prepares the source once, inserts 5,000 rows per SQL statement,
and varies only how many statements share a transaction. It uses the real Soju
indexes/FTS triggers and verifies both message and FTS counts. Cases run in forward
and reverse order on the regular filesystem. Local results for two million rows:

| Rows per transaction | Transactions | Timed write phase |
| --- | ---: | ---: |
| All rows | 1 | 5.59–5.76 s |
| 50,000 | 40 | 5.49–5.76 s |
| 5,000 | 400 | 7.78–8.03 s |

The single transaction and 50,000-row transactions were effectively tied in this
workload. The importer keeps one transaction per file for its all-or-nothing
behavior. These measurements cover the write phase only; whole-import timings
include parsing, staging and duplicate detection. Smaller transactions could
reduce waits for other writers, but they would permit partially committed files.
