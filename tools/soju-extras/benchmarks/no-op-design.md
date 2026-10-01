# Fast no-op checks: proposed next step

Status: design only. The benchmark measures the existing backup implementation;
no watcher or verification schedule has been deployed by this experiment.

## Separate three operations

1. **Change detection:** decide locally whether a new recovery point is needed.
2. **Backup:** capture changes, verify new payloads, deliver them, and publish a
   completion receipt only after successful remote verification.
3. **Scrub:** periodically read and verify retained data in full, independently
   of whether sources changed. Remote availability checks are separate too.

A local no-op must not update the timestamp of the last verified remote backup
or claim that the destination was contacted. Monitoring needs distinct status
for a successful local check and a verified recovery point.

## Why cached hashes alone are insufficient

Calculating a hash reads the file. Remembering a previous hash avoids that read
only when another mechanism establishes that the bytes have not changed. Size
and modification time can be useful shortcuts, but cannot detect every edit.

For a decision that does not scan all historical files, retain a change cursor
from a background filesystem watcher. Prefer an existing implementation that
reports lost events and provides a synchronization barrier. For example,
[Watchman's query protocol](https://facebook.github.io/watchman/docs/cmd/query)
exposes fresh-instance detection and synchronizes with filesystem notifications;
[clock cursors](https://facebook.github.io/watchman/docs/clockspec) identify which
changes a successful backup covered. Watchman is not installed on m70q.

## Conditions for skipping a backup

- The watcher has uninterrupted coverage since a known successful backup.
- Its synchronized change query finds no relevant changes.
- Configuration and watched source identities still match that backup.
- The last completed snapshot and its completion receipt still exist.
- No forced reconciliation or full-verification deadline is due.

Restart, event overflow, a replaced or removed watch root, unavailable service,
invalid state, or a failed query must force reconciliation. A stale or absent
watcher must never be interpreted as an empty change list.

Save the coverage cursor only after successful backup completion. Changes during
a backup must remain pending unless their inclusion can be established. Failed
transfer, interruption and retry must not advance the successful cursor.

## Source-specific details

- **SQLite:** include WAL creation, writes, truncation, checkpointing, deletion
  and database replacement. The timestamp of `main.db` alone is insufficient.
  This detects changes; it does not make copying a changed database incremental.
- **Logs:** include old files rewritten by imports/backfills, renames, deletions
  and new directories, not just today's log paths.
- **WeeChat:** preserve the existing settings-flush requirement. Rewrites of
  small settings files may need a content comparison to avoid treating an
  identical save as a data change.
- **Backup bookkeeping:** exclude the backup's own locks/status files from
  change detection to prevent every successful backup dirtying itself.
- **Configuration:** changed source lists, exclusion rules or destinations
  invalidate prior coverage.

## Tests before enabling it

- Unchanged sources skip SQLite copying, historical hashing and SSH entirely.
- WAL-only commits and replacement databases prevent a no-op.
- Same-size edits with restored mtimes, old-log backfills, deletes, symlink
  changes and newly created subdirectories are detected.
- Restart, overflow, disconnection and corrupt state cause a full fallback.
- Changes during copying or transfer remain pending for the next backup.
- A failed transfer or interrupted backup cannot establish a clean baseline.
- Missing completion receipts prevent a no-op.
- Scheduled scrubs detect corrupted old backup payloads even when sources have
  remained unchanged.

Measure the local decision separately from Python CLI startup, settings flushes
and reconciliation. Millisecond no-op checks are a target, not yet a measured
property of this implementation.

## What this will not solve by itself

Active IRC history changes every day, so a fast no-op alone will not make normal
daily backups proportional to that day's messages. A changed database still
needs SQLite-aware incremental backup. Publishing an independent directory tree
of hard links, serializing its full manifest and recursively running rsync also
has a cost proportional to the number of files, even if their contents are
reused. Those costs should be measured separately before changing the existing
dated-directory recovery layout.
