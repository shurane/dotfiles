"""Estimate SQLite and compressed-source storage from bounded local log samples."""

import argparse
import gzip
import sqlite3
import sys
from collections import Counter
from collections.abc import Sequence
from compression import zstd
from contextlib import closing, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict, Field, model_validator

from soju_extras.db import execute, execute_many, query_rows, transaction
from soju_extras.importer.cli import SojuLogImporter
from soju_extras.models import WeeChatLogRecord


class Options(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    logs_dir: Path
    timezone: str = "UTC"
    stride: int = Field(default=10000, ge=1)
    sample_size: int = Field(default=100, ge=1)
    temp_dir: Path = Path(".")

    @model_validator(mode="after")
    def check_sample_size(self) -> Options:
        if self.sample_size > self.stride:
            raise ValueError("sample_size must not exceed stride")
        return self


class Footprint(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    name: str
    bytes: int


class Report(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    source_files: int
    source_records: int
    source_uncompressed_bytes: int
    sample_records: int
    sample_records_imported: int
    sample_records_skipped: dict[str, int]
    sample_source_bytes: int
    sample_gzip_bytes: int
    sample_zstd_bytes: int
    sample_sqlite_bytes: int
    sample_fts_bytes: int
    projected_sqlite_bytes: int
    projected_source_gzip_bytes: int
    projected_source_zstd_bytes: int
    limitations: tuple[str, ...]


def measure(options: Options) -> Report:
    targets = SojuLogImporter(options.logs_dir).discover_targets()
    source_records = source_bytes = sample_records = sample_bytes = 0
    gzip_bytes = zstd_bytes = 0
    skipped: Counter[str] = Counter()
    with TemporaryDirectory(prefix=".storage-benchmark-", dir=options.temp_dir) as directory:
        root = Path(directory)
        logs = root / "samples"
        logs.mkdir()
        for index, target in enumerate(targets):
            source_path = target.source_path
            destination = logs / source_path.relative_to(options.logs_dir)
            # Sample files retain their original names and compression so the
            # public importer handles rotations and duplicate detection normally.
            destination.parent.mkdir(parents=True, exist_ok=True)
            opener = {".gz": gzip.open, ".zst": zstd.open}.get(source_path.suffix, open)
            gzip_path, zstd_path = root / f"{index}.gz", root / f"{index}.zst"
            with (
                opener(source_path, "rb") as source,
                opener(destination, "wb") as sample,
                gzip.open(gzip_path, "wb", compresslevel=6) as gz,
                zstd.open(zstd_path, "wb") as zs,
            ):
                record_index = 0
                for raw in source:
                    source_bytes += len(raw)
                    if not raw.strip():
                        continue
                    selected = record_index % options.stride < options.sample_size
                    record_index += 1
                    source_records += 1
                    if not selected:
                        continue
                    sample_records += 1
                    sample_bytes += len(raw)
                    gz.write(raw)
                    zs.write(raw)
                    try:
                        record = WeeChatLogRecord.parse_line(
                            raw.decode("utf-8"), timezone=options.timezone
                        )
                        if record is None:
                            raise ValueError("Not a WeeChat record")
                    except ValueError as error:
                        skipped[type(error).__name__] += 1
                        continue
                    sample.write(raw)
            gzip_bytes += gzip_path.stat().st_size
            zstd_bytes += zstd_path.stat().st_size
        if not sample_records or sample_records == skipped.total():
            raise ValueError("No valid sampled records; check the source format and timezone")

        database = root / "sample.db"
        schema = (
            Path(__file__).resolve().parents[1] / "tests/fixtures/soju_schema.sql"
        ).read_text()
        with closing(sqlite3.connect(database, autocommit=True)) as db:
            db.row_factory = sqlite3.Row
            with closing(db.executescript(schema)):
                pass
            with transaction(db):
                execute(
                    db,
                    "INSERT INTO User(id,username,created_at) VALUES(1,?,?)",
                    ("benchmark", "2026-01-01T00:00:00.000Z"),
                )
                execute_many(
                    db,
                    "INSERT INTO Network(user,name,addr) VALUES(1,?,?)",
                    ((name, name) for name in sorted({target.network for target in targets})),
                )
            # Keep JSON on stdout; importer progress belongs on stderr.
            with redirect_stdout(sys.stderr):
                imported = SojuLogImporter(
                    logs, db_path=database, username="benchmark", timezone=options.timezone
                ).run()
            footprint = query_rows(
                db, Footprint, "SELECT name, sum(pgsize) AS bytes FROM dbstat GROUP BY name"
            )
        if not imported:
            raise ValueError("Sample import produced no messages")
        database_bytes = database.stat().st_size
        return Report(
            source_files=len(targets),
            source_records=source_records,
            source_uncompressed_bytes=source_bytes,
            sample_records=sample_records,
            sample_records_imported=imported,
            sample_records_skipped=dict(skipped),
            sample_source_bytes=sample_bytes,
            sample_gzip_bytes=gzip_bytes,
            sample_zstd_bytes=zstd_bytes,
            sample_sqlite_bytes=database_bytes,
            sample_fts_bytes=sum(
                row.bytes for row in footprint if row.name.startswith("MessageFTS")
            ),
            projected_sqlite_bytes=round(database_bytes / imported * source_records),
            projected_source_gzip_bytes=round(gzip_bytes / sample_bytes * source_bytes),
            projected_source_zstd_bytes=round(zstd_bytes / sample_bytes * source_bytes),
            limitations=(
                f"Samples the first {options.sample_size} nonblank records per {options.stride} "
                "in each file; short files are overrepresented. Inputs should be immutable.",
                "SQLite includes real schema indexes and FTS, but excludes WAL, staging, backups "
                "and filesystem allocation. Small samples overstate fixed schema overhead.",
                "Compression uses sampled source records grouped by source file. Daily Soju "
                "exports and monthly archives have different formats and compression boundaries.",
                "Sample parse failures are counted and skipped. Unsampled records are not "
                "validated. Invalid source records remain included in the projected totals.",
                "The sample import uses normal repeat detection. Unreconciled overlap can bias "
                "the projection; this report is not a migration validation pass.",
            ),
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs-dir", type=Path, required=True)
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--stride", type=int, default=10000)
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--temp-dir", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    try:
        result = measure(Options.model_validate(vars(args)))
    except (OSError, ValueError, sqlite3.Error, zstd.ZstdError) as error:
        print(f"Storage estimate failed: {error}", file=sys.stderr)
        return 2
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
