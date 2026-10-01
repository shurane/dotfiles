"""Validate configuration and on-disk manifests at the backup boundary."""

from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from soju_extras.time import parse_timestamp


def relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or str(path) != value or value == ".":
        raise ValueError("Expected a normalized relative path without traversal")
    return value


def snapshot_name(value: str) -> str:
    if len(value) != 18 or value[10] != "T" or value[-1] != "Z":
        raise ValueError("Expected YYYY-MM-DDTHHMMSSZ")
    stamp = f"{value[:13]}:{value[13:15]}:{value[15:17]}Z"
    if parse_timestamp(stamp).format_iso(unit="second").replace(":", "") != value:
        raise ValueError("Invalid snapshot timestamp")
    return value


class Boundary(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class Retention(Boundary):
    daily: int = Field(default=7, ge=1)
    weekly: int = Field(default=4, ge=0)
    monthly: int = Field(default=6, ge=0)
    timezone: str = "America/Chicago"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"Unknown timezone: {value}") from error
        return value


class CopySource(Boundary):
    source: Path
    destination: str
    excludes: list[str] = Field(default_factory=list)

    _destination = field_validator("destination")(relative_path)

    @field_validator("source")
    @classmethod
    def absolute_source(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("Source must be absolute")
        return value


class Remote(Boundary):
    # rrsync on the receiver anchors all paths within its dedicated backup root.
    host: str = Field(pattern=r"^[a-zA-Z0-9_][a-zA-Z0-9_.@-]*$")
    identity_file: Path
    known_hosts: Path


class WeeChatCheckpoint(Boundary):
    user: str = Field(pattern=r"^[a-z_][a-z0-9_-]*$")
    command: Path
    ready_file: Path


class BackupConfig(Boundary):
    database: Path
    export_directory: Path
    root: Path
    sources: list[CopySource]
    database_destination: str = "soju/main.db"
    remote: Remote | None = None
    weechat: WeeChatCheckpoint | None = None
    retention: Retention = Field(default_factory=Retention)
    success_file: Path | None = None
    last_file: Path | None = None

    _database_destination = field_validator("database_destination")(relative_path)

    @model_validator(mode="after")
    def valid_paths(self) -> Self:
        paths = [self.database, self.export_directory, self.root]
        paths += [p for p in (self.success_file, self.last_file) if p is not None]
        if not all(p.is_absolute() for p in paths):
            raise ValueError("Backup paths must be absolute")
        for source in self.sources:
            if self.root.resolve().is_relative_to(source.source.resolve()):
                raise ValueError("Backup root must be outside its sources")
        destinations = [PurePosixPath(s.destination) for s in self.sources]
        if any(
            a.is_relative_to(b) or b.is_relative_to(a)
            for i, a in enumerate(destinations)
            for b in destinations[i + 1 :]
        ):
            raise ValueError("Copy destinations must not overlap")
        return self


class Entry(Boundary):
    path: str
    mode: int = Field(ge=0, le=0o7777)

    _path = field_validator("path")(relative_path)


class FileEntry(Entry):
    kind: Literal["file"] = "file"
    stored: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    stored_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    encoding: Literal["plain", "gzip", "zstd"]

    _stored = field_validator("stored")(relative_path)


class DirectoryEntry(Entry):
    kind: Literal["directory"] = "directory"


class SymlinkEntry(Entry):
    kind: Literal["symlink"] = "symlink"
    target: str


type SnapshotEntry = Annotated[
    FileEntry | DirectoryEntry | SymlinkEntry, Field(discriminator="kind")
]


class Manifest(Boundary):
    version: Literal[1] = 1
    snapshot: str
    entries: list[SnapshotEntry]

    _snapshot = field_validator("snapshot")(snapshot_name)

    @model_validator(mode="after")
    def unique_paths(self) -> Self:
        paths = [e.path for e in self.entries]
        stored = [e.stored for e in self.entries if isinstance(e, FileEntry)]
        if len(set(paths)) != len(paths) or len(set(stored)) != len(stored):
            raise ValueError("Duplicate manifest paths")
        non_directories = {e.path for e in self.entries if not isinstance(e, DirectoryEntry)}
        for path in paths:
            if any(str(parent) in non_directories for parent in PurePosixPath(path).parents):
                raise ValueError("Manifest entry descends through a file or symlink")
        return self


class Receipt(Boundary):
    version: Literal[1] = 1
    snapshot: str
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    _snapshot = field_validator("snapshot")(snapshot_name)
