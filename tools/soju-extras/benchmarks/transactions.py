"""Compare commit frequency with identical insert statements and Soju FTS triggers.

uv run python benchmarks/transactions.py --messages 2000000

Data preparation, schema setup, and row-count verification are outside the timer.
Each SQL statement inserts 5,000 rows regardless of transaction size. Cases run
in forward and reverse order to reduce systematic cache-order bias. Databases
and SQLite scratch files use the regular filesystem beneath --temp-dir.
"""

import argparse
import json
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from soju_extras.db import execute, execute_many, transaction


def source_rows(count: int) -> Iterator[tuple[int, str, str, str, str]]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(count):
        text = f"message {index} " + "x" * 100
        timestamp = (
            (base + timedelta(seconds=index))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        yield index, f":alice!u@h PRIVMSG #python :{text}", timestamp, "alice", text


def measure(
    root: Path, prepared: Path, schema: str, count: int, transaction_rows: int, round_number: int
) -> None:
    with TemporaryDirectory(dir=root, prefix="case-") as directory:
        path = Path(directory) / "soju.db"
        with closing(sqlite3.connect(path, autocommit=True)) as db:
            with closing(db.executescript(schema)):
                pass
            execute(db, "PRAGMA journal_mode=WAL")
            execute(db, "PRAGMA foreign_keys=ON")
            execute(db, "ATTACH DATABASE ? AS prepared", (str(prepared),))
            execute(
                db,
                "INSERT INTO User(id,username,created_at) VALUES(1,'shurane','2026-01-01T00:00:00.000Z')",
            )
            execute(
                db,
                "INSERT INTO Network(id,user,name,addr) VALUES(1,1,'libera','irc.libera.chat:6697')",
            )
            execute(db, "INSERT INTO MessageTarget(id,network,target) VALUES(1,1,'#python')")
            transaction_durations: list[float] = []
            started = time.perf_counter()
            for batch_start in range(0, count, transaction_rows or count):
                batch_end = min(count, batch_start + (transaction_rows or count))
                tx_started = time.perf_counter()
                with transaction(db):
                    for statement_start in range(batch_start, batch_end, 5000):
                        execute(
                            db,
                            """
                            INSERT INTO Message(target,raw,time,sender,text)
                            SELECT 1,raw,time,sender,text FROM prepared.incoming
                            WHERE seq >= ? AND seq < ? ORDER BY seq
                        """,
                            (statement_start, min(batch_end, statement_start + 5000)),
                        )
                transaction_durations.append(time.perf_counter() - tx_started)
            elapsed = time.perf_counter() - started
            with closing(db.execute("SELECT count(*) FROM Message")) as cursor:
                assert cursor.fetchone()[0] == count
            with closing(
                db.execute("SELECT count(*) FROM MessageFTS WHERE MessageFTS MATCH 'message'")
            ) as cursor:
                assert cursor.fetchone()[0] == count
            print(
                json.dumps(
                    {
                        "round": round_number,
                        "messages": count,
                        "rows_per_statement": 5000,
                        "rows_per_transaction": transaction_rows or "all",
                        "transactions": len(transaction_durations),
                        "seconds": round(elapsed, 3),
                        "messages_per_second": round(count / elapsed),
                        "longest_transaction_seconds": round(max(transaction_durations), 3),
                    }
                ),
                flush=True,
            )


def run(count: int, temp_dir: Path) -> None:
    schema = (Path(__file__).resolve().parents[1] / "tests/fixtures/soju_schema.sql").read_text()
    with TemporaryDirectory(dir=temp_dir, prefix=".transaction-benchmark-") as directory:
        root = Path(directory).resolve()
        prepared = root / "prepared.db"
        # Set before the first SQLite connection for its temporary sort files.
        previous = os.environ.get("SQLITE_TMPDIR")
        os.environ["SQLITE_TMPDIR"] = str(root)
        try:
            print(f"Preparing {count:,} source rows on disk...", flush=True)
            with closing(sqlite3.connect(prepared, autocommit=True)) as db:
                execute(
                    db,
                    "CREATE TABLE incoming(seq INTEGER PRIMARY KEY, raw TEXT, time TEXT, sender TEXT, text TEXT)",
                )
                with transaction(db):
                    execute_many(db, "INSERT INTO incoming VALUES(?,?,?,?,?)", source_rows(count))
            for round_number, sizes in enumerate(((0, 50000, 5000), (5000, 50000, 0)), 1):
                for size in sizes:
                    measure(root, prepared, schema, count, size, round_number)
        finally:
            if previous is None:
                os.environ.pop("SQLITE_TMPDIR", None)
            else:
                os.environ["SQLITE_TMPDIR"] = previous


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--messages", type=int, default=2000000)
    parser.add_argument("--temp-dir", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if args.messages < 1:
        parser.error("--messages must be positive")
    run(args.messages, args.temp_dir)
