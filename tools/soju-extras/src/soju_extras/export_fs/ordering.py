"""Chronological daily logs with streaming merges and disk-backed legacy repair."""

import gzip
import os
import sqlite3
from collections.abc import Generator, Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from heapq import merge
from itertools import chain
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from whenever import Time

from soju_extras.db import execute, execute_many, query, transaction


@dataclass(frozen=True, slots=True)
class LogOrder:
    latest: str = ""
    ordered: bool = True


class StoredLine(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    line: str


def line_time(line: str) -> str:
    header, separator, _ = line.partition("] ")
    if not header.startswith("[") or not separator or not line.endswith("\n"):
        raise ValueError("Invalid exported log line; cannot safely reorder this file")
    return Time.parse_iso(header[1:]).format_iso(unit="nanosecond")


@contextmanager
def read_log(path: Path, *, compress: bool) -> Generator[Iterator[str]]:
    with (
        gzip.open(path, "rt", encoding="utf-8", newline="")
        if compress
        else path.open(encoding="utf-8", newline="")
    ) as stream:
        yield iter(stream)


def inspect_log(path: Path, *, compress: bool) -> LogOrder:
    latest = ""
    ordered = True
    with read_log(path, compress=compress) as lines:
        for line in lines:
            stamp = line_time(line)
            ordered = ordered and stamp >= latest
            latest = max(latest, stamp)
    return LogOrder(latest, ordered)


def write_log(path: Path, lines: Iterable[str], *, compress: bool, append: bool) -> None:
    with path.open("ab" if append else "xb") as stream:
        if compress:
            with gzip.GzipFile(
                fileobj=stream, mode="wb", filename="", mtime=0, compresslevel=6
            ) as compressed:
                for line in lines:
                    compressed.write(line.encode("utf-8"))
        else:
            for line in lines:
                stream.write(line.encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


def rewrite_log(
    source: Path,
    destination: Path,
    sort_file: Path,
    lines: list[str],
    *,
    compress: bool,
    ordered: bool,
) -> None:
    """Preserve every archived line, even when SQLite no longer has its message."""
    with read_log(source, compress=compress) as archived:
        if ordered:
            # Stable ties: archived lines first, then new lines in message-ID order.
            write_log(
                destination, merge(archived, lines, key=line_time), compress=compress, append=False
            )
        else:
            # Older exporter versions could leave unordered logs. Use SQLite's external
            # sort instead of collecting an entire decompressed daily file in memory.
            with closing(sqlite3.connect(sort_file, autocommit=True)) as db:
                db.row_factory = sqlite3.Row
                execute(db, "PRAGMA journal_mode = OFF")
                execute(db, "PRAGMA synchronous = OFF")
                execute(db, "PRAGMA temp_store = FILE")
                execute(db, "CREATE TABLE lines (seq INTEGER PRIMARY KEY, time TEXT, line TEXT)")
                with transaction(db):
                    execute_many(
                        db,
                        "INSERT INTO lines(time, line) VALUES (?, ?)",
                        ((line_time(line), line) for line in chain(archived, lines)),
                    )
                with query(db, StoredLine, "SELECT line FROM lines ORDER BY time, seq") as rows:
                    write_log(
                        destination, (row.line for row in rows), compress=compress, append=False
                    )
