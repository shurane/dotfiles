"""Target and network resolution utilities for Soju database."""

from __future__ import annotations

import sqlite_utils


class SojuTargetResolver:
    """Resolves and caches Soju Network and MessageTarget mappings."""

    def __init__(self, db: sqlite_utils.Database) -> None:
        self.db = db
        self._user_ids: dict[str, int] = {}
        self._network_ids: dict[tuple[int, str], int] = {}
        self._target_ids: dict[tuple[int, str], int] = {}

    def get_or_create_user(self, username: str) -> int:
        """Resolve user ID or create user record."""
        if username in self._user_ids:
            return self._user_ids[username]

        rows = list(self.db.query("SELECT id FROM User WHERE username = ?", [username]))
        if rows:
            uid = int(rows[0]["id"])
        else:
            t = self.db.table("User").insert({"username": username, "admin": 0})
            uid = int(t.last_pk or t.last_rowid or 0)

        self._user_ids[username] = uid
        return uid

    def get_or_create_network(self, user_id: int, network_name: str) -> int:
        """Resolve network ID for a user or create network record."""
        key = (user_id, network_name.lower())
        if key in self._network_ids:
            return self._network_ids[key]

        rows = list(
            self.db.query(
                "SELECT id FROM Network WHERE user = ? AND LOWER(name) = ?",
                [user_id, network_name.lower()],
            )
        )
        if rows:
            net_id = int(rows[0]["id"])
        else:
            t = self.db.table("Network").insert(
                {
                    "user": user_id,
                    "name": network_name.lower(),
                    "addr": f"irc.{network_name.lower()}.net:6697",
                    "nick": "user",
                    "enabled": 1,
                }
            )
            net_id = int(t.last_pk or t.last_rowid or 0)

        self._network_ids[key] = net_id
        return net_id

    def get_or_create_target(self, network_id: int, target: str) -> int:
        """Resolve MessageTarget ID or create target record."""
        key = (network_id, target.lower())
        if key in self._target_ids:
            return self._target_ids[key]

        rows = list(
            self.db.query(
                "SELECT id FROM MessageTarget WHERE network = ? AND LOWER(target) = ?",
                [network_id, target.lower()],
            )
        )
        if rows:
            target_id = int(rows[0]["id"])
        else:
            t = self.db.table("MessageTarget").insert(
                {
                    "network": network_id,
                    "target": target.lower(),
                }
            )
            target_id = int(t.last_pk or t.last_rowid or 0)

        self._target_ids[key] = target_id
        return target_id
