"""Measure real backups of synthetic Soju databases at increasing message counts.

Dataset generation is excluded. Each backup runs in a fresh process so its peak
RSS excludes generation. By default the repeat changes only a read marker;
--repeat unchanged also leaves the database intact.
An optional Remote JSON uses a separately provisioned, disposable rsync receiver.
"""

import argparse
import json
import os
import platform
import random
import resource
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from soju_extras.backup.models import BackupConfig, CopySource, Remote
from soju_extras.backup.runner import create_backup
from soju_extras.db import execute, execute_many, open_soju_db, transaction
from soju_extras.export_fs.ordering import write_log

WORDS = """
the a this that my your our their is was are be have can could would should with from into about
after before for and or but because while when if then just really probably maybe still already
almost only also pretty some more less every first last next another same different good better
small large new old current server client channel network message history database backup
archive file folder read write sync copy restore check test update install configure package
release python rust linux windows sqlite system service process thread memory storage disk cache
index query transaction connection socket driver kernel device machine router wireless ethernet
packet address route gateway dns interface certificate login password account session buffer
terminal editor shell command script code function class type object string number list table
option setting default value error warning debug output input format timestamp timezone date
clock version build compile run start stop restart reload enable disable working broken fixed
works trying tried think know see find found looking looks seems need want use using change
changed add remove save load send receive wait quick slow easy hard thanks hello please yes no
sure okay right wrong question answer example issue support documentation upstream local remote
public private shared complete valid safe useful interesting available stable recent previous
direct actual expected result return failure success connection reconnect timeout status request
response source target permission owner group path content match compare count size time reason
problem solution approach behavior detail extra simple standard library
""".split()  # noqa: SIM905 — keep the fixed benchmark vocabulary compact and readable.


type Phase = Literal["first", "repeat", "unchanged"]
type Repeat = Literal["marker", "unchanged"]


class Arguments(argparse.Namespace):
    action: Literal["sweep", "measure"]
    root: Path
    config: Path
    sizes: list[int]
    remote: Path | None
    channels: int
    messages_per_day: int
    repeat: Repeat
    messages: int
    phase: Phase


class Options(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    root: Path
    sizes: list[int] = Field(default_factory=lambda: [200, 2000, 20000, 200000, 2000000, 20000000])
    channels: int = Field(default=34, ge=1)
    messages_per_day: int = Field(default=10000, ge=1)
    repeat: Repeat = "marker"
    remote: Remote | None = None


class Result(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    messages: int
    phase: Phase
    seconds: float
    cpu_seconds: float
    peak_rss_mib: float
    database_bytes: int
    log_bytes: int
    log_files: int
    snapshot_bytes: int
    snapshot: str
    remote: bool


def initialize(root: Path, channels: int) -> Path:
    database = root / "source/main.db"
    database.parent.mkdir(parents=True)
    schema = (Path(__file__).resolve().parents[1] / "tests/fixtures/soju_schema.sql").read_text()
    with closing(sqlite3.connect(database, autocommit=True)) as db:
        with closing(db.executescript(schema)):
            pass
        execute(db, "PRAGMA journal_mode=WAL")
        execute(db, "PRAGMA user_version=30")
        with transaction(db):
            execute(
                db,
                "INSERT INTO User(id,username,created_at) VALUES(1,'benchmark','2026-07-01T00:00:00.000Z')",
            )
            execute(
                db, "INSERT INTO Network(id,user,name,addr) VALUES(1,1,'synthetic','irc.invalid')"
            )
            execute_many(
                db,
                "INSERT INTO MessageTarget(id,network,target) VALUES(?,1,?)",
                ((i, f"#channel-{i:02}") for i in range(1, channels + 1)),
            )
            execute(
                db,
                "INSERT INTO ReadReceipt(network,target,timestamp) VALUES(1,'#channel-01','2026-07-01T00:00:00.000Z')",
            )
    return database


def corpus() -> list[str]:
    randomizer = random.Random(20261001)
    return [
        " ".join(randomizer.choices(WORDS, k=randomizer.randrange(5, 26))) for _ in range(65536)
    ]


def extend(options: Options, database: Path, start: int, end: int, phrases: list[str]) -> None:
    logs = options.root / "source/logs"
    began = time.monotonic()
    with open_soju_db(database) as db:
        execute(db, "PRAGMA cache_size=-65536")
        execute(db, "PRAGMA synchronous=NORMAL")
        with transaction(db):
            for offset in range(start, end, options.messages_per_day):
                stop = min(end, (offset // options.messages_per_day + 1) * options.messages_per_day)
                # The outer stride needs to follow partial days at the small checkpoints.
                if offset % options.messages_per_day and stop < end:
                    raise ValueError("Partial day must be generated separately")
                day = date(2026, 7, 1) + timedelta(days=offset // options.messages_per_day)
                lines: defaultdict[int, list[str]] = defaultdict(list)
                rows: list[tuple[int, str, str, str, str]] = []
                for i in range(offset, stop):
                    channel = i % options.channels + 1
                    sender = f"user{i * 37 % 512:03}"
                    seconds = (i % options.messages_per_day) * 86400 // options.messages_per_day
                    hour, remainder = divmod(seconds, 3600)
                    minute, second = divmod(remainder, 60)
                    clock = f"{hour:02}:{minute:02}:{second:02}.000"
                    timestamp = f"{day}T{clock}Z"
                    # Deterministic mixed sentences; avoid a repeated padding string.
                    text = phrases[((i * 2654435761) ^ (i >> 8)) % len(phrases)]
                    if i % 20 == 0:
                        text += f" reference {i // 20}"
                    raw = f"@time={timestamp} :{sender}!user@irc.invalid PRIVMSG #channel-{channel:02} :{text}"
                    rows.append((channel, raw, timestamp, sender, text))
                    lines[channel].append(f"[{clock}] <{sender}> {text}\n")
                execute_many(
                    db, "INSERT INTO Message(target,raw,time,sender,text) VALUES(?,?,?,?,?)", rows
                )
                for channel, messages in lines.items():
                    path = (
                        logs
                        / f"users/benchmark/networks/synthetic/channels/#channel-{channel:02}/{day}.log.gz"
                    )
                    path.parent.mkdir(parents=True, exist_ok=True)
                    write_log(path, messages, compress=True, append=path.exists())
                if stop % 100000 == 0:
                    print(
                        json.dumps(
                            {
                                "event": "generate",
                                "messages": stop,
                                "target": end,
                                "elapsed_seconds": round(time.monotonic() - began, 1),
                            }
                        ),
                        flush=True,
                    )
    (logs / ".last_synced_id").write_text(str(end) + "\n")


def generate(options: Options, database: Path, start: int, end: int, phrases: list[str]) -> None:
    if start % options.messages_per_day:
        boundary = min(end, (start // options.messages_per_day + 1) * options.messages_per_day)
        extend(options, database, start, boundary, phrases)
        start = boundary
    if start < end:
        extend(options, database, start, end, phrases)


def measure(config_path: Path, count: int, phase: Phase) -> Result:
    config = BackupConfig.model_validate_json(config_path.read_bytes())
    before = resource.getrusage(resource.RUSAGE_SELF)
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    snapshot = create_backup(config)
    elapsed = time.perf_counter() - started
    after = resource.getrusage(resource.RUSAGE_SELF)
    children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    logs = list(config.export_directory.rglob("*.gz"))
    return Result(
        messages=count,
        phase=phase,
        seconds=round(elapsed, 3),
        cpu_seconds=round(
            after.ru_utime
            + after.ru_stime
            - before.ru_utime
            - before.ru_stime
            + children_after.ru_utime
            + children_after.ru_stime
            - children_before.ru_utime
            - children_before.ru_stime,
            3,
        ),
        peak_rss_mib=round(after.ru_maxrss / 1024, 1),
        database_bytes=config.database.stat().st_size,
        log_bytes=sum(path.stat().st_size for path in logs),
        log_files=len(logs),
        snapshot_bytes=sum(path.stat().st_size for path in snapshot.rglob("*") if path.is_file()),
        snapshot=snapshot.name,
        remote=config.remote is not None,
    )


def sweep(options: Options) -> None:
    if options.sizes != sorted(set(options.sizes)) or any(n < 1 for n in options.sizes):
        raise ValueError("Sizes must be distinct positive counts in ascending order")
    # Only this newly created source subtree is ever modified by generation.
    database = initialize(options.root, options.channels)
    logs = options.root / "source/logs"
    results = options.root / "results.jsonl"
    if results.exists():
        raise FileExistsError(results)
    (options.root / "environment.json").write_text(
        json.dumps(
            {
                "python": sys.version,
                "platform": platform.platform(),
                "cpus": os.cpu_count(),
                "channels": options.channels,
                "messages_per_day": options.messages_per_day,
                "cache_policy": "No cache flush; first followed by repeat on the same source",
                "remote": options.remote is not None,
                "repeat": options.repeat,
                "workload": "Real Soju schema with indexes and FTS; deterministic synthetic PRIVMSG content",
            },
            indent=2,
        )
    )
    phrases = corpus()
    count = 0
    for target in options.sizes:
        began = time.monotonic()
        generate(options, database, count, target, phrases)
        count = target
        with open_soju_db(database, readonly=True) as db, closing(db.cursor()) as cursor:
            actual = cursor.execute("SELECT COUNT(*) FROM Message").fetchone()[0]
            if actual != count:
                raise ValueError(f"Expected {count} messages, found {actual}")
        print(
            json.dumps(
                {
                    "event": "ready",
                    "messages": count,
                    "setup_seconds": round(time.monotonic() - began, 3),
                    "database_bytes": database.stat().st_size,
                }
            ),
            flush=True,
        )
        backup_root = options.root / f"backups-{count}"
        config = BackupConfig(
            database=database,
            export_directory=logs,
            root=backup_root,
            sources=[CopySource(source=logs, destination="soju/logs", excludes=[".export.lock"])],
            remote=options.remote,
        )
        config_path = options.root / "config.json"
        config_path.write_text(config.model_dump_json(indent=2) + "\n")
        for phase in ("first", "repeat" if options.repeat == "marker" else "unchanged"):
            if phase == "repeat":
                with open_soju_db(database) as db, transaction(db):
                    execute(
                        db,
                        "UPDATE ReadReceipt SET timestamp=?",
                        (
                            (datetime(2032, 1, 1, tzinfo=UTC) + timedelta(seconds=count))
                            .isoformat(timespec="milliseconds")
                            .replace("+00:00", "Z"),
                        ),
                    )
            time.sleep(1.05)  # Unique snapshot names, outside the timed operation.
            raw = subprocess.check_output(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "measure",
                    str(config_path),
                    "--messages",
                    str(count),
                    "--phase",
                    phase,
                ],
                text=True,
            )
            result = Result.model_validate_json(raw)
            with results.open("a") as stream:
                stream.write(result.model_dump_json() + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            print(result.model_dump_json(), flush=True)
        shutil.rmtree(backup_root)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    command = commands.add_parser("sweep")
    command.add_argument("root", type=Path)
    command.add_argument(
        "--sizes", type=int, nargs="+", default=[200, 2000, 20000, 200000, 2000000, 20000000]
    )
    command.add_argument("--remote", type=Path)
    command.add_argument("--channels", type=int, default=34)
    command.add_argument("--messages-per-day", type=int, default=10000)
    command.add_argument("--repeat", choices=["marker", "unchanged"], default="marker")
    command = commands.add_parser("measure")
    command.add_argument("config", type=Path)
    command.add_argument("--messages", type=int, required=True)
    command.add_argument("--phase", choices=["first", "repeat", "unchanged"], required=True)
    args = parser.parse_args(namespace=Arguments())
    if args.action == "measure":
        print(measure(args.config, args.messages, args.phase).model_dump_json())
    else:
        sweep(
            Options(
                root=args.root.resolve(),
                sizes=args.sizes,
                channels=args.channels,
                messages_per_day=args.messages_per_day,
                repeat=args.repeat,
                remote=Remote.model_validate_json(args.remote.read_bytes())
                if args.remote
                else None,
            )
        )


if __name__ == "__main__":
    main()
