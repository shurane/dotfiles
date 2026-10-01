"""Durable state files and a process lock for append/replacement recovery."""

import fcntl
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FileOffset(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    relative_path: str
    size: int | None = Field(ge=0)
    backup_path: str | None = None
    replacement_path: str | None = None
    sort_path: str | None = None

    @model_validator(mode="after")
    def validate_replacement(self) -> Self:
        paths = (self.backup_path, self.replacement_path, self.sort_path)
        if any(path is not None for path in paths) and (
            self.size is None or any(path is None for path in paths)
        ):
            raise ValueError("A replacement requires the original size and all recovery paths")
        return self


class AppendJournal(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    previous_id: int = Field(ge=0)
    latest_id: int = Field(ge=0)
    files: list[FileOffset]


class ExportIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    database: str
    checkpoint: str
    compress: bool


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: Path, content: str) -> None:
    durable_mkdir(path.parent)
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".soju-", delete_on_close=False
    ) as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
        os.replace(stream.name, path)
        sync_directory(path.parent)


def durable_mkdir(path: Path) -> None:
    """Persist newly created parent directory entries before checkpointing files."""
    missing: list[Path] = []
    parent = path
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        directory.mkdir(exist_ok=True)
        sync_directory(directory.parent)


@contextmanager
def export_lock(path: Path, *, label: str = "exporter") -> Generator[None]:
    durable_mkdir(path.parent)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(f"Another {label} is using this output directory") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
