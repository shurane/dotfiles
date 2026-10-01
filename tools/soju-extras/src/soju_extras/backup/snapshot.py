"""Stream files into individually compressed, checksummed, restorable snapshots."""

import gzip
import hashlib
import os
import shutil
import sqlite3
import stat
from collections.abc import Generator
from compression import zstd
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO, Literal

from pydantic import BaseModel, ConfigDict

from soju_extras.backup.models import (
    DirectoryEntry,
    FileEntry,
    Manifest,
    SnapshotEntry,
    SymlinkEntry,
)
from soju_extras.db import execute, open_soju_db, query
from soju_extras.export_fs.storage import atomic_write, sync_directory

MANIFEST = "manifest.json"
RECEIPT = ".complete.json"


class IntegrityRow(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    integrity_check: str


class ForeignKeyRow(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    table: str
    rowid: int | None
    parent: str
    fkid: int


def check_database(path: Path) -> None:
    with open_soju_db(path, readonly=True) as conn:
        with query(conn, IntegrityRow, "PRAGMA integrity_check") as rows:
            if any(row.integrity_check != "ok" for row in rows):
                raise ValueError("SQLite integrity check failed")
        with query(conn, ForeignKeyRow, "PRAGMA foreign_key_check") as rows:
            if next(rows, None) is not None:
                raise ValueError("SQLite foreign-key check failed")


def backup_database(source: Path, destination: Path) -> None:
    if destination.is_symlink() or destination.parent.resolve() != destination.parent.absolute():
        raise ValueError("Database snapshot destination must not contain symlinks")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    with open_soju_db(source, readonly=True) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst, pages=1024)
        execute(dst, "PRAGMA journal_mode = DELETE")
    check_database(destination)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@contextmanager
def decoded(
    path: Path, encoding: Literal["plain", "gzip", "zstd"]
) -> Generator[BinaryIO | gzip.GzipFile | zstd.ZstdFile]:
    if encoding == "gzip":
        with gzip.open(path, "rb") as stream:
            yield stream
    elif encoding == "zstd":
        with zstd.open(path, "rb") as stream:
            yield stream
    else:
        with path.open("rb") as stream:
            yield stream


def decoded_digest(path: Path, encoding: Literal["plain", "gzip", "zstd"]) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with decoded(path, encoding) as reader:
        while chunk := reader.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def reuse_file(
    source: Path,
    destination: Path,
    previous: Path,
    entry: FileEntry,
    source_hash: str,
    mode: int,
) -> FileEntry | None:
    """Compare content, never just mtime/size; validate old bytes before linking."""
    prior_hash = entry.source_sha256
    if prior_hash is None:
        # Bootstrap snapshots written before encoded source hashes were recorded.
        prior_hash = (
            entry.sha256
            if entry.encoding == "plain"
            else (entry.stored_sha256 if entry.encoding == "zstd" else None)
        )
    if prior_hash is not None:
        if source_hash != prior_hash:
            return None
    elif decoded_digest(source, entry.encoding) != (entry.size, entry.sha256):
        return None
    try:
        old = stored_file(previous, entry.stored)
    except OSError, ValueError:
        return None
    if sha256(old) != entry.stored_sha256:
        return None  # Rebuild a damaged previous payload from the staged source.
    os.link(old, destination)
    return entry.model_copy(update={"mode": mode, "source_sha256": source_hash})


def pack_file(
    source: Path,
    destination: Path,
    relative: str,
    stored: str,
    *,
    source_hash: str | None = None,
) -> FileEntry:
    encoding: Literal["plain", "gzip", "zstd"] = (
        "gzip" if source.suffix == ".gz" else "zstd" if source.suffix == ".zst" else "plain"
    )
    digest = hashlib.sha256()
    size = 0
    before = source.stat()
    with decoded(source, encoding) as reader:
        if encoding == "zstd":
            # Validate its decoded contents; reuse the already compressed bytes.
            while chunk := reader.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
            shutil.copyfile(source, destination)
        else:
            with zstd.open(
                destination,
                "wb",
                options={
                    zstd.CompressionParameter.nb_workers: 2
                    if before.st_size >= 8 * 1024 * 1024
                    else 0,
                    zstd.CompressionParameter.checksum_flag: 1,
                },
            ) as writer:
                writer.write(b"")  # Emit a valid frame even when the source is empty.
                while chunk := reader.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                    writer.write(chunk)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"Source changed while packing: {source}")
    os.chmod(destination, 0o600)
    os.utime(destination, ns=(before.st_atime_ns, before.st_mtime_ns))
    with destination.open("rb") as stream:
        os.fsync(stream.fileno())
    return FileEntry(
        path=relative,
        stored=stored,
        mode=stat.S_IMODE(before.st_mode),
        size=size,
        sha256=digest.hexdigest(),
        stored_sha256=sha256(destination),
        encoding=encoding,
        source_sha256=source_hash if source_hash is not None else sha256(source),
    )


def pack_tree(
    source: Path,
    destination: Path,
    name: str,
    *,
    previous: Path | None = None,
) -> Manifest:
    """Input is a private staging tree. No source symlinks are followed."""
    destination.mkdir(mode=0o700)
    prior = (
        {
            entry.path: entry
            for entry in read_manifest(previous).entries
            if isinstance(entry, FileEntry)
        }
        if previous
        else {}
    )
    entries: list[SnapshotEntry] = []
    stored_paths: set[str] = set()
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source).as_posix()
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if path.is_symlink():
            entries.append(SymlinkEntry(path=relative, mode=mode, target=os.readlink(path)))
        elif path.is_dir():
            entries.append(DirectoryEntry(path=relative, mode=mode))
        elif path.is_file():
            stored = (
                relative[:-3] + ".zst"
                if relative.endswith(".gz")
                else (relative if relative.endswith(".zst") else relative + ".zst")
            )
            if stored in stored_paths or stored in (MANIFEST, RECEIPT):
                raise ValueError(f"Compressed path collision: {relative}")
            stored_paths.add(stored)
            output = destination / stored
            output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            source_hash = sha256(path)
            old = prior.get(relative)
            entry = None
            if previous is not None and old is not None and old.stored == stored:
                entry = reuse_file(path, output, previous, old, source_hash, mode)
            if entry is None:
                entry = pack_file(path, output, relative, stored, source_hash=source_hash)
            entries.append(entry)
        else:
            raise ValueError(f"Cannot back up special file: {path}")
    manifest = Manifest(snapshot=name, entries=entries)
    atomic_write(destination / MANIFEST, manifest.model_dump_json(indent=2) + "\n")
    for directory in sorted((p for p in destination.rglob("*") if p.is_dir()), reverse=True):
        sync_directory(directory)
    sync_directory(destination)
    return manifest


def read_manifest(root: Path) -> Manifest:
    path = root / MANIFEST
    if path.is_symlink():
        raise ValueError("Manifest must not be a symlink")
    return Manifest.model_validate_json(path.read_bytes())


def stored_file(root: Path, relative: str) -> Path:
    path = root / relative
    if path.is_symlink() or path.resolve() != path.absolute() or not path.is_file():
        raise ValueError(f"Expected a regular stored file: {relative}")
    return path


def verify_snapshot(root: Path) -> Manifest:
    manifest = read_manifest(root)
    for entry in manifest.entries:
        if isinstance(entry, FileEntry):
            path = stored_file(root, entry.stored)
            if sha256(path) != entry.stored_sha256:
                raise ValueError(f"Stored checksum mismatch: {entry.path}")
            try:
                contents = decoded_digest(path, "zstd")
            except (EOFError, zstd.ZstdError) as error:
                raise ValueError(f"Invalid Zstandard payload: {entry.path}") from error
            if contents != (entry.size, entry.sha256):
                raise ValueError(f"Decoded checksum mismatch: {entry.path}")
    return manifest


def restore_snapshot(root: Path, destination: Path) -> None:
    """Verify, restore off to the side, then publish to an absent destination.

    Original names, gzip encoding, permissions and symlinks are reconstructed.
    Ownership belongs to the restoring user; service ownership is set by the operator.
    """
    manifest = verify_snapshot(root)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    with TemporaryDirectory(prefix=".restore-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "tree"
        stage.mkdir(mode=0o700)
        for entry in manifest.entries:
            output = stage / entry.path
            output.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(entry, DirectoryEntry):
                output.mkdir(exist_ok=True)
            elif isinstance(entry, FileEntry):
                source = stored_file(root, entry.stored)
                if entry.encoding == "zstd":
                    shutil.copyfile(source, output)
                else:
                    with zstd.open(source, "rb") as reader:
                        if entry.encoding == "gzip":
                            with gzip.open(output, "wb") as writer:
                                shutil.copyfileobj(reader, writer, 1024 * 1024)
                        else:
                            with output.open("wb") as writer:
                                shutil.copyfileobj(reader, writer, 1024 * 1024)
                output.chmod(entry.mode)
        # Create links last: no restoration writes can traverse a restored link.
        for entry in manifest.entries:
            if isinstance(entry, SymlinkEntry):
                (stage / entry.path).symlink_to(entry.target)
        for entry in reversed(manifest.entries):
            if isinstance(entry, DirectoryEntry):
                (stage / entry.path).chmod(entry.mode)
        os.rename(stage, destination)
        sync_directory(destination.parent)
