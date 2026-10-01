"""Reproducible local throughput/RSS measurements; setup is outside the timer.

uv run python benchmarks/throughput.py export --messages 200000
uv run python benchmarks/throughput.py import --messages 200000
"""

import argparse
import json
import resource
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from itertools import batched
from pathlib import Path
from tempfile import TemporaryDirectory

from soju_extras.export_fs.cli import SojuFSExporter
from soju_extras.importer.cli import SojuLogImporter


def run(operation: str, count: int, batch_size: int) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "soju.db"
        schema = (
            Path(__file__).resolve().parents[1] / "tests/fixtures/soju_schema.sql"
        ).read_text()
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript(schema)
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "INSERT INTO User(id,username,created_at) VALUES(1,'shurane','2026-01-01T00:00:00.000Z')"
            )
            db.execute(
                "INSERT INTO Network(id,user,name,addr) VALUES(1,1,'libera','irc.libera.chat:6697')"
            )
            db.execute("INSERT INTO MessageTarget(id,network,target) VALUES(1,1,'#python')")
            base = datetime(2026, 1, 1, tzinfo=UTC)
            if operation == "export":
                rows = (
                    (
                        1,
                        f":alice!u@h PRIVMSG #python :message {i} " + "x" * 100,
                        (base + timedelta(seconds=i))
                        .isoformat(timespec="milliseconds")
                        .replace("+00:00", "Z"),
                        "alice",
                        f"message {i} " + "x" * 100,
                    )
                    for i in range(count)
                )
                for batch in batched(rows, batch_size, strict=False):
                    db.executemany(
                        "INSERT INTO Message(target,raw,time,sender,text) VALUES(?,?,?,?,?)", batch
                    ).close()
        if operation == "export":
            started = time.perf_counter()
            SojuFSExporter(path, root / "out", batch_size=batch_size).run()
        else:
            logs = root / "logs"
            logs.mkdir()
            with (logs / "irc.libera.#python.weechatlog").open("w") as stream:
                for i in range(count):
                    stamp = (base + timedelta(seconds=i)).strftime("%Y-%m-%d %H:%M:%S")
                    stream.write(f"{stamp}\talice\tmessage {i} " + "x" * 100 + "\n")
            started = time.perf_counter()
            SojuLogImporter(logs, db_path=path, batch_size=batch_size).run()
        seconds = time.perf_counter() - started
        print(
            json.dumps(
                {
                    "operation": operation,
                    "messages": count,
                    "batch_size": batch_size,
                    "seconds": round(seconds, 3),
                    "messages_per_second": round(count / seconds),
                    "peak_rss_mib": round(
                        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1
                    ),
                }
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["export", "import"])
    parser.add_argument("--messages", type=int, default=100000)
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()
    run(args.operation, args.messages, args.batch_size)
