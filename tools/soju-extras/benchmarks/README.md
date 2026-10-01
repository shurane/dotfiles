# Backup scaling benchmark

Run from the project root with a **new disposable directory**:

```sh
uv run --frozen python benchmarks/backup.py sweep /tmp/soju-backup-scaling
```

The default counts are 200, 2,000, 20,000, 200,000, 2 million and 20 million
messages. For a quick local check, add `--sizes 200 2000`. Allow tens of GB of
free space for the full sweep. Source generation is outside the measured time.

Each size uses the pinned Soju SQLite schema, including indexes and FTS, and
matching daily gzip exports. Messages are deterministic synthetic IRC PRIVMSGs
distributed across 34 channels at 10,000 messages per day. `--channels` and
`--messages-per-day` change the file distribution independently of message count.
No real Soju database or credentials are needed.

Each measurement runs the actual `create_backup()` in a fresh Python process:

- **First:** no previous snapshot for this size.
- **Repeat:** change one read receipt, leave all messages and logs unchanged,
  then back up again with the preceding snapshot available for reuse.

Use `--repeat unchanged` to leave the database unchanged as well. This labels
the second measurement `unchanged` instead of `repeat`.

This repeat tests the cost of retaining an increasing amount of unchanged
history while the database still changes. It does not measure importing or
exporting that day's new messages. Source caches are not flushed, and each
case is measured once; results are paired observations, not statistical medians.

To include transfer and checksum verification, pass `--remote remote.json`.
The JSON must match `soju_extras.backup.models.Remote`. Provision a dedicated,
restricted rsync receiver rooted in an empty test directory; **never point it at
the production backup receiver**. Remote test snapshots are intentionally left
for inspection. Remove them and revoke the test key after collecting results.

The sweep writes `results.jsonl` and `environment.json`. Elapsed time includes
database copying and checks, source staging, compression or reuse, full local
verification, optional remote delivery and checks, and completion receipts.
CPU time includes local subprocesses; peak RSS measures the Python backup
process only. Snapshot bytes count a complete logical view, including files
shared through hard links; they do not measure additional disk allocation.

Per-size local snapshots are removed after both runs. The synthetic source
remains for inspection and must be removed manually. An interrupted sweep
leaves its files in place; start a new sweep in another disposable directory.

The October 1, 2026 measurements are in [results/2026-10-01](results/2026-10-01/README.md).
