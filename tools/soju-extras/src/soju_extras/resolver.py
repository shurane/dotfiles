"""Resolve existing Soju identities without inventing server configuration."""

import sqlite3

from pydantic import BaseModel, ConfigDict

from soju_extras.db import execute, query_rows


class IDRow(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    id: int


class SojuTargetResolver:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def resolve_user(self, username: str) -> int:
        rows = query_rows(self.db, IDRow, "SELECT id FROM User WHERE username = ?", (username,))
        if len(rows) != 1:
            raise ValueError(f"Soju user {username!r} does not exist")
        return rows[0].id

    def resolve_network(self, user_id: int, name: str) -> int:
        rows = query_rows(
            self.db,
            IDRow,
            "SELECT id FROM Network WHERE user = ? AND (name = ? COLLATE NOCASE OR addr = ?)",
            (user_id, name, name),
        )
        if len(rows) != 1:
            raise ValueError(
                f"Network {name!r} must identify one existing network; use --network-map"
            )
        return rows[0].id

    def get_or_create_target(self, network_id: int, target: str) -> int:
        # Target casing is preserved. Soju owns network-specific IRC case mapping.
        execute(
            self.db,
            "INSERT INTO MessageTarget(network, target) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (network_id, target),
        )
        return query_rows(
            self.db,
            IDRow,
            "SELECT id FROM MessageTarget WHERE network = ? AND target = ?",
            (network_id, target),
        )[0].id
