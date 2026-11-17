"""Stream files into individually compressed, checksummed, restorable snapshots."""

import gzip
import hashlib
import io
import os
import shutil
import sqlite3
import stat
from collections.abc import Buffer, Generator, Sequence
from compression import zstd
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO, Literal, override

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


class _HashingStream(io.RawIOBase):
    """Wrap a binary stream, updating a SHA-256 digest on every read or write."""

    def __init__(
        self,
        stream: io.BufferedReader | io.BufferedWriter,
        digest: hashlib._Hash,
        tee: io.BufferedWriter | None = None,
    ) -> None:
        self._stream = stream
        self._digest = digest
        self._tee = tee

    @override
    def read(self, size: int = -1, /) -> bytes:
        chunk = self._stream.read(size)
        if chunk:
            self._digest.update(chunk)
            if self._tee is not None:
                self._tee.write(chunk)
        return chunk

    @override
    def readinto(self, buffer: Buffer, /) -> int:
        n = self._stream.readinto(buffer)
        if n:
            view = memoryview(buffer)[:n]
            self._digest.update(view)
            if self._tee is not None:
                self._tee.write(view)
        return n

    @override
    def write(self, b: Buffer, /) -> int:
        self._digest.update(b)
        return self._stream.write(b)

    @override
    def flush(self) -> None:
        if not self._stream.closed:
            self._stream.flush()

    @override
    def readable(self) -> bool:
        return True

    @override
    def writable(self) -> bool:
        return True


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


def verify_zstd_payload(path: Path) -> tuple[str, int, str]:
    """Single-pass verification returning (stored_sha256, decoded_size, decoded_sha256)."""
    stored_digest = hashlib.sha256()
    decoded_digest_obj = hashlib.sha256()
    size = 0
    with path.open("rb") as raw:
        hashed = _HashingStream(raw, stored_digest)
        with zstd.open(hashed, "rb") as reader:  # type: ignore[arg-type]
            while chunk := reader.read(1024 * 1024):
                decoded_digest_obj.update(chunk)
                size += len(chunk)
        while hashed.read(1024 * 1024):
            pass
    return stored_digest.hexdigest(), size, decoded_digest_obj.hexdigest()


def reuse_file(
    source: Path,
    destination: Path,
    previous: Path,
    entry: FileEntry,
    *,
    source_hash: str,
    mode: int,
) -> FileEntry | None:
    """Compare content, never just mtime/size; validate old bytes before linking."""
    prior_hash = entry.source_sha256
    if prior_hash is None:
        # Bootstrap snapshots written before encoded source hashes were recorded.
        prior_hash = (
            entry.sha256 if entry.encoding == "plain" else (entry.stored_sha256 if entry.encoding == "zstd" else None)
        )
    if prior_hash is not None:
        if source_hash != prior_hash:
            return None
    elif decoded_digest(source, entry.encoding) != (entry.size, entry.sha256):
        return None
    try:
        old = _regular_stored_file(previous, entry.stored)
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
    source_digest = hashlib.sha256()
    stored_digest = hashlib.sha256()
    size = 0
    with source.open("rb") as raw_source:
        before = os.fstat(raw_source.fileno())
        with destination.open("wb") as raw_dest:
            if encoding == "zstd":
                # Validate decoded contents while streaming raw bytes to destination in one pass.
                hashed_source = _HashingStream(raw_source, source_digest, tee=raw_dest)
                with zstd.open(hashed_source, "rb") as reader:
                    while chunk := reader.read(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                while hashed_source.read(1024 * 1024):
                    pass
            else:
                hashed_source = _HashingStream(raw_source, source_digest)
                hashed_dest = _HashingStream(raw_dest, stored_digest)
                with zstd.open(
                    hashed_dest,
                    "wb",
                    options={
                        zstd.CompressionParameter.nb_workers: 2 if before.st_size >= 8 * 1024 * 1024 else 0,
                        zstd.CompressionParameter.checksum_flag: 1,
                    },
                ) as writer:
                    writer.write(b"")  # Emit a valid frame even when the source is empty.
                    if encoding == "gzip":
                        with gzip.GzipFile(fileobj=hashed_source, mode="rb") as gz_reader:  # type: ignore[arg-type]
                            while chunk := gz_reader.read(1024 * 1024):
                                digest.update(chunk)
                                size += len(chunk)
                                writer.write(chunk)
                        while hashed_source.read(1024 * 1024):
                            pass
                    else:
                        while chunk := hashed_source.read(1024 * 1024):
                            digest.update(chunk)
                            size += len(chunk)
                            writer.write(chunk)
            after = os.fstat(raw_source.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError(f"Source changed while packing: {source}")
            raw_dest.flush()
            os.fchmod(raw_dest.fileno(), 0o600)
            os.utime(raw_dest.fileno(), ns=(before.st_atime_ns, before.st_mtime_ns))
            os.fsync(raw_dest.fileno())
    actual_source_hash = source_hash if source_hash is not None else source_digest.hexdigest()
    return FileEntry(
        path=relative,
        stored=stored,
        mode=stat.S_IMODE(before.st_mode),
        size=size,
        sha256=digest.hexdigest(),
        stored_sha256=actual_source_hash if encoding == "zstd" else stored_digest.hexdigest(),
        encoding=encoding,
        source_sha256=actual_source_hash,
    )


def _stored_name(relative: str, stored_paths: set[str]) -> str:
    stored = (
        relative[:-3] + ".zst"
        if relative.endswith(".gz")
        else (relative if relative.endswith(".zst") else relative + ".zst")
    )
    if stored in stored_paths or stored in (MANIFEST, RECEIPT):
        raise ValueError(f"Compressed path collision: {relative}")
    stored_paths.add(stored)
    return stored


def pack_tree(
    source: Path,
    destination: Path,
    name: str,
    *,
    previous: Path | None = None,
) -> Manifest:
    """Input is a private staging tree. No source symlinks are followed."""
    destination.mkdir(mode=0o700)
    prior: dict[str, FileEntry] = {}
    if previous is not None:
        prior_manifest = read_manifest(previous)
        _validate_snapshot_dirs(previous, prior_manifest.entries)
        prior = {entry.path: entry for entry in prior_manifest.entries if isinstance(entry, FileEntry)}
    entries: list[SnapshotEntry] = []
    stored_paths: set[str] = set()
    synced_dirs: set[Path] = {destination}
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source).as_posix()
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISLNK(info.st_mode):
            entries.append(SymlinkEntry(path=relative, mode=mode, target=str(path.readlink())))
        elif stat.S_ISDIR(info.st_mode):
            entries.append(DirectoryEntry(path=relative, mode=mode))
            out_dir = destination / relative
            out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            synced_dirs.add(out_dir)
        elif stat.S_ISREG(info.st_mode):
            stored = _stored_name(relative, stored_paths)
            output = destination / stored
            if output.parent not in synced_dirs:
                output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                synced_dirs.add(output.parent)
            old = prior.get(relative)
            entry = None
            source_hash: str | None = None
            if previous is not None and old is not None and old.stored == stored:
                source_hash = sha256(path)
                entry = reuse_file(
                    path,
                    output,
                    previous,
                    old,
                    source_hash=source_hash,
                    mode=mode,
                )
            entries.append(entry or pack_file(path, output, relative, stored, source_hash=source_hash))
        else:
            raise ValueError(f"Cannot back up special file: {path}")
    manifest = Manifest(snapshot=name, entries=entries)
    atomic_write(destination / MANIFEST, manifest.model_dump_json(indent=2) + "\n")
    for directory in sorted(synced_dirs, reverse=True):
        sync_directory(directory)
    return manifest


def read_manifest(root: Path) -> Manifest:
    path = root / MANIFEST
    if path.is_symlink():
        raise ValueError("Manifest must not be a symlink")
    return Manifest.model_validate_json(path.read_bytes())


def stored_file(root: Path, relative: str) -> Path:
    path = root / relative
    cur = root
    parts = Path(relative).parts
    for i, part in enumerate(parts):
        cur = cur / part
        try:
            st = cur.lstat()
        except OSError as error:
            raise ValueError(f"Expected a regular stored file: {relative}") from error
        if stat.S_ISLNK(st.st_mode):
            raise ValueError(f"Expected a regular stored file: {relative}")
        is_last = i == len(parts) - 1
        if is_last and not stat.S_ISREG(st.st_mode):
            raise ValueError(f"Expected a regular stored file: {relative}")
        if not is_last and not stat.S_ISDIR(st.st_mode):
            raise ValueError(f"Expected a regular stored file: {relative}")
    return path


def _validate_snapshot_dirs(root: Path, entries: Sequence[SnapshotEntry]) -> None:
    parents = {
        str(parent)
        for entry in entries
        if isinstance(entry, FileEntry)
        for parent in Path(entry.stored).parents
        if str(parent) != "."
    }
    for rel_dir in sorted(parents):
        cur = root / rel_dir
        try:
            st = cur.lstat()
        except OSError as error:
            raise ValueError(f"Expected a regular stored file: {rel_dir}") from error
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise ValueError(f"Expected a regular stored file: {rel_dir}")


def _regular_stored_file(root: Path, relative: str) -> Path:
    path = root / relative
    try:
        st = path.lstat()
    except OSError as error:
        raise ValueError(f"Expected a regular stored file: {relative}") from error
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ValueError(f"Expected a regular stored file: {relative}")
    return path


def verify_snapshot(root: Path) -> Manifest:
    manifest = read_manifest(root)
    _validate_snapshot_dirs(root, manifest.entries)
    for entry in manifest.entries:
        if isinstance(entry, FileEntry):
            path = _regular_stored_file(root, entry.stored)
            try:
                stored_hash, size, decoded_hash = verify_zstd_payload(path)
            except (EOFError, zstd.ZstdError) as error:
                if sha256(path) != entry.stored_sha256:
                    raise ValueError(f"Stored checksum mismatch: {entry.path}") from error
                raise ValueError(f"Invalid Zstandard payload: {entry.path}") from error
            if stored_hash != entry.stored_sha256:
                raise ValueError(f"Stored checksum mismatch: {entry.path}")
            if (size, decoded_hash) != (entry.size, entry.sha256):
                raise ValueError(f"Decoded checksum mismatch: {entry.path}")
    return manifest


def _restore_file_entry(root: Path, stage: Path, entry: FileEntry) -> None:
    output = stage / entry.path
    output.parent.mkdir(parents=True, exist_ok=True)
    source = _regular_stored_file(root, entry.stored)
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
            if isinstance(entry, DirectoryEntry):
                output = stage / entry.path
                output.parent.mkdir(parents=True, exist_ok=True)
                output.mkdir(exist_ok=True)
            elif isinstance(entry, FileEntry):
                _restore_file_entry(root, stage, entry)
        # Create links last: no restoration writes can traverse a restored link.
        for entry in manifest.entries:
            if isinstance(entry, SymlinkEntry):
                (stage / entry.path).symlink_to(entry.target)
        for entry in reversed(manifest.entries):
            if isinstance(entry, DirectoryEntry):
                (stage / entry.path).chmod(entry.mode)
        stage.rename(destination)
        sync_directory(destination.parent)
