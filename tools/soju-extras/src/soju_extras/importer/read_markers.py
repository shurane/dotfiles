"""Explicitly transfer known read markers without guessing from log contents."""

import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from soju_extras.db import execute, open_soju_db, query_rows, transaction
from soju_extras.resolver import SojuTargetResolver
from soju_extras.time import parse_timestamp, soju_timestamp


class ReadMarker(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    network: str = Field(min_length=1)
    target: str = Field(min_length=1)
    timestamp: str

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: str) -> str:
        if not (value.endswith("Z") or "+" in value[10:] or "-" in value[10:]):
            raise ValueError("Read marker timestamps require an explicit UTC offset")
        return soju_timestamp(parse_timestamp(value))


class UnresolvedMarker(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    network: str = Field(min_length=1)
    target: str = Field(min_length=1)
    reason: Literal["marker_unavailable"]


class UnreadBuffer(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    network: str = Field(min_length=1)
    target: str = Field(min_length=1)
    scope: Literal["retained_lines"] = "retained_lines"


class ReadMarkers(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    version: Literal[1]
    markers: list[ReadMarker]
    unread: list[UnreadBuffer] = Field(default_factory=list[UnreadBuffer])
    unresolved: list[UnresolvedMarker] = Field(default_factory=list[UnresolvedMarker])


class TargetRow(BaseModel):
    model_config = ConfigDict(strict=True)
    target: str


def resolve_target(db: sqlite3.Connection, network: int, target: str) -> str:
    targets = query_rows(
        db,
        TargetRow,
        "SELECT target FROM MessageTarget WHERE network = ? AND target = ? COLLATE NOCASE",
        (network, target),
    )
    if len(targets) > 1:
        raise ValueError(f"Ambiguous target casing for {target}")
    return targets[0].target if targets else target


def import_read_markers(
    markers: ReadMarkers, db_path: Path, username: str, network_map: dict[str, str]
) -> None:
    """Apply the explicitly supplied markers atomically; preserve later existing reads."""
    with open_soju_db(db_path) as db, transaction(db):
        resolver = SojuTargetResolver(db)
        user_id = resolver.resolve_user(username)
        unread_targets: set[tuple[int, str]] = set()
        for unread in markers.unread:
            network = resolver.resolve_network(
                user_id, network_map.get(unread.network.lower(), unread.network)
            )
            target = resolve_target(db, network, unread.target)
            if query_rows(
                db,
                TargetRow,
                "SELECT target FROM ReadReceipt WHERE network = ? AND target = ? COLLATE NOCASE",
                (network, target),
            ):
                raise ValueError(
                    f"{unread.network}/{target}: snapshot records unread history but Soju has "
                    "a read receipt. Reconcile these states before transfer; no markers changed."
                )
            unread_targets.add((network, target.lower()))
        for marker in markers.markers:
            network = resolver.resolve_network(
                user_id, network_map.get(marker.network.lower(), marker.network)
            )
            target = resolve_target(db, network, marker.target)
            if (network, target.lower()) in unread_targets:
                raise ValueError(
                    f"Conflicting read and unread states for {marker.network}/{target}"
                )
            execute(
                db,
                """
                INSERT INTO ReadReceipt(network, target, timestamp) VALUES (?, ?, ?)
                ON CONFLICT(network, target) DO UPDATE
                SET timestamp = max(ReadReceipt.timestamp, excluded.timestamp)
                """,
                (network, target, marker.timestamp),
            )
