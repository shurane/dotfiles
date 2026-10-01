"""Tests for SojuTargetResolver."""

from __future__ import annotations

import sqlite_utils

from soju.resolver import SojuTargetResolver


def test_resolver_create_and_cache() -> None:
    db = sqlite_utils.Database(memory=True)
    db.table("User").create({"id": int, "username": str, "admin": int}, pk="id")
    db.table("Network").create(
        {"id": int, "user": int, "name": str, "addr": str, "nick": str, "enabled": int},
        pk="id",
    )
    db.table("MessageTarget").create({"id": int, "network": int, "target": str}, pk="id")

    resolver = SojuTargetResolver(db)

    u1 = resolver.get_or_create_user("shurane")
    u2 = resolver.get_or_create_user("shurane")
    assert u1 == u2

    n1 = resolver.get_or_create_network(u1, "libera")
    n2 = resolver.get_or_create_network(u1, "libera")
    assert n1 == n2

    t1 = resolver.get_or_create_target(n1, "#python")
    t2 = resolver.get_or_create_target(n1, "#python")
    assert t1 == t2
