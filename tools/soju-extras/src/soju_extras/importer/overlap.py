"""Remove exact shared occurrences from one explicitly selected plain log.

Inputs must be immutable staging copies. The preferred log is left intact;
the output contains only surplus occurrences from the secondary log, in order.
No channel aliases or timestamp equivalence are inferred.
"""

import argparse
import hashlib
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from itertools import batched
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict


class OverlapReport(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    preferred_sha256: str
    secondary_sha256: str
    output_sha256: str
    preferred_records: int
    secondary_records: int
    removed_records: int
    retained_records: int


def _lines(path: Path) -> Iterator[bytes]:
    with path.open("rb") as stream:
        for number, line in enumerate(stream, 1):
            if not line.endswith(b"\n"):
                raise ValueError(f"{path}:{number}: incomplete final line; restage after flushing")
            yield line


def deduplicate_overlap(preferred: Path, secondary: Path, output: Path) -> OverlapReport:
    """Keep max(count in preferred, count in secondary) of each exact record.

    Uses a disk-backed multiset and one transaction, with bounded Python memory.
    Output publication is atomic and refuses to overwrite an existing path.
    Original byte spelling is preserved; only LF/CRLF differences are ignored.
    """
    if preferred.resolve() == secondary.resolve() or preferred.samefile(secondary):
        raise ValueError("Preferred and secondary logs must be different files")
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    preferred_hash = hashlib.sha256()
    secondary_hash = hashlib.sha256()
    output_hash = hashlib.sha256()
    preferred_records = secondary_records = removed = retained = 0

    with TemporaryDirectory(prefix=".overlap-", dir=output.parent) as temporary:
        root = Path(temporary)
        with closing(sqlite3.connect(root / "counts.db")) as db, db:
            db.execute("PRAGMA cache_size=-8192")
            db.execute(
                "CREATE TABLE counts(line BLOB PRIMARY KEY, remaining INTEGER) WITHOUT ROWID"
            )

            with closing(db.cursor()) as cursor, (root / "output").open("xb") as destination:

                def primary_rows() -> Iterator[tuple[bytes]]:
                    nonlocal preferred_records
                    for line in _lines(preferred):
                        preferred_hash.update(line)
                        if line.strip():
                            preferred_records += 1
                            yield (line.removesuffix(b"\n").removesuffix(b"\r"),)

                for batch in batched(primary_rows(), 5000, strict=False):
                    cursor.executemany(
                        "INSERT INTO counts VALUES (?,1) ON CONFLICT(line) DO UPDATE "
                        "SET remaining=remaining+1",
                        batch,
                    )
                for line in _lines(secondary):
                    secondary_hash.update(line)
                    if line.strip():
                        secondary_records += 1
                        cursor.execute(
                            "UPDATE counts SET remaining=remaining-1 WHERE line=? AND remaining>0",
                            (line.removesuffix(b"\n").removesuffix(b"\r"),),
                        )
                        if cursor.rowcount:
                            removed += 1
                            continue
                        retained += 1
                    destination.write(line)
                    output_hash.update(line)
                destination.flush()
                os.fsync(destination.fileno())
        report = OverlapReport(
            preferred_sha256=preferred_hash.hexdigest(),
            secondary_sha256=secondary_hash.hexdigest(),
            output_sha256=output_hash.hexdigest(),
            preferred_records=preferred_records,
            secondary_records=secondary_records,
            removed_records=removed,
            retained_records=retained,
        )
        os.link(root / "output", output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preferred", type=Path, required=True)
    parser.add_argument("--secondary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = deduplicate_overlap(args.preferred, args.secondary, args.output)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(2, f"{error}\n")
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
