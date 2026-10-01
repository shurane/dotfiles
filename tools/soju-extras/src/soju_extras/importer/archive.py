"""Split immutable plain WeeChat logs into monthly Zstd archives and recent input."""

import argparse
import hashlib
import os
from compression import zstd
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO

from pydantic import BaseModel, ConfigDict
from whenever import OffsetDateTime, PlainDateTime

from soju_extras.export_fs.cli import path_component
from soju_extras.importer.cli import SojuLogImporter


class FileSummary(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    records: int
    bytes: int
    sha256: str


class ArchiveManifest(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    version: int = 1
    since: str
    timezone: str
    username: str
    source_records: int
    archived_records: int
    import_records: int
    sources: dict[str, FileSummary]
    outputs: dict[str, FileSummary]
    stored_bytes: dict[str, int]


class Digest:
    def __init__(self) -> None:
        self.records = 0
        self.bytes = 0
        self.hash = hashlib.sha256()

    def update(self, data: bytes) -> None:
        self.records += 1
        self.bytes += len(data)
        self.hash.update(data)

    def summary(self) -> FileSummary:
        return FileSummary(records=self.records, bytes=self.bytes, sha256=self.hash.hexdigest())


def record_date(line: bytes, timezone: str) -> str:
    """Bucket in source-local calendar dates without guessing an ambiguous instant.

    An offset-free repeated DST hour still has an unambiguous month/date. Retain
    its exact bytes in the archive; the importer remains strict about instants.
    """
    if not line.endswith(b"\n"):
        raise ValueError("Incomplete final line; restage after flushing")
    parts = line.split(b"\t", 2)
    if len(parts) != 3:
        raise ValueError("Expected timestamp, sender and message separated by tabs")
    stamp = parts[0].decode("ascii").replace(" ", "T", 1)
    if stamp.endswith("Z") or "+" in stamp[10:] or "-" in stamp[10:]:
        return str(OffsetDateTime.parse_iso(stamp).to_tz(timezone).date())
    return str(PlainDateTime.parse_iso(stamp).date())


def verify_output(path: Path, expected: FileSummary) -> None:
    digest = Digest()
    opener = zstd.open if path.suffix == ".zst" else open
    with opener(path, "rb") as stream:
        for line in stream:
            digest.update(line)
    if digest.summary() != expected:
        raise ValueError(f"Verification failed: {path}")


def prepare_history(
    source: Path, output: Path, *, since: str, timezone: str, username: str = "shurane"
) -> ArchiveManifest:
    """Publish only after every output has been read back and verified.

    Inputs must be immutable, plain, and contain one file per network/target.
    Memory is bounded by a source file's number of months, not its record count.
    """
    boundary = PlainDateTime.parse_iso(since + "T00:00:00")
    boundary.assume_tz(timezone, disambiguate="raise")
    if since != str(boundary.date()) or not since.endswith("-01"):
        raise ValueError("--since must be the first day of a month, YYYY-MM-01")
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if output.resolve().is_relative_to(source.resolve()):
        raise ValueError("Output must be outside the source tree")
    targets = SojuLogImporter(source, dry_run=True).discover_targets()
    identities: set[tuple[str, str]] = set()
    for target in targets:
        identity = (target.network, target.target)
        if not target.source_path.name.endswith(".weechatlog") or identity in identities:
            raise ValueError("Stage exactly one plain .weechatlog per network/target first")
        identities.add(identity)
    sources: dict[str, FileSummary] = {}
    outputs: dict[str, FileSummary] = {}
    stored: dict[str, int] = {}
    with TemporaryDirectory(prefix=".history-", dir=output.parent) as temporary:
        root = Path(temporary) / "prepared"
        (root / "import").mkdir(parents=True)
        (root / "archives").mkdir()
        for target in targets:
            source_digest = Digest()
            digests: dict[Path, Digest] = {}
            with ExitStack() as stack:
                streams: dict[Path, BinaryIO | zstd.ZstdFile] = {}
                source_stream = stack.enter_context(target.source_path.open("rb"))
                for number, line in enumerate(source_stream, 1):
                    try:
                        date = record_date(line, timezone)
                    except ValueError as error:
                        raise ValueError(f"{target.source_path}:{number}: {error}") from error
                    source_digest.update(line)
                    if date >= since:
                        relative = Path("import") / target.source_path.name
                    else:
                        relative = (
                            Path("archives")
                            / path_component(username)
                            / path_component(target.network)
                            / path_component(target.target)
                            / (date[:7] + ".weechatlog.zst")
                        )
                    if relative not in streams:
                        path = root / relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        streams[relative] = stack.enter_context(
                            zstd.open(path, "wb") if path.suffix == ".zst" else path.open("wb")
                        )
                        digests[relative] = Digest()
                    streams[relative].write(line)
                    digests[relative].update(line)
            sources[str(target.source_path.relative_to(source))] = source_digest.summary()
            for relative, digest in digests.items():
                expected = digest.summary()
                verify_output(root / relative, expected)
                outputs[str(relative)] = expected
                stored[str(relative)] = (root / relative).stat().st_size
        total = sum(item.records for item in sources.values())
        archived = sum(
            item.records for path, item in outputs.items() if path.startswith("archives/")
        )
        imported = sum(item.records for path, item in outputs.items() if path.startswith("import/"))
        if total != archived + imported or sum(s.bytes for s in sources.values()) != sum(
            s.bytes for s in outputs.values()
        ):
            raise ValueError("Record/byte accounting mismatch")
        manifest = ArchiveManifest(
            since=since,
            timezone=timezone,
            username=username,
            source_records=total,
            archived_records=archived,
            import_records=imported,
            sources=sources,
            outputs=outputs,
            stored_bytes=stored,
        )
        (root / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")
        if output.exists() or output.is_symlink():
            raise FileExistsError(output)
        os.rename(root, output)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--since", required=True)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--username", default="shurane")
    args = parser.parse_args()
    try:
        result = prepare_history(
            args.source,
            args.output,
            since=args.since,
            timezone=args.timezone,
            username=args.username,
        )
    except (OSError, ValueError, zstd.ZstdError) as error:
        parser.exit(2, f"{error}\n")
    print(
        f"Verified {result.archived_records:,} archived and {result.import_records:,} import records"
    )


if __name__ == "__main__":
    main()
