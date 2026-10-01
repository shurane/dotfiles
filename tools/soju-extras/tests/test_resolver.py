"""Resolution never invents accounts or enabled server connections."""

from pathlib import Path

import pytest

from soju_extras.db import execute, open_soju_db, transaction
from soju_extras.resolver import SojuTargetResolver


def test_resolver_existing_identities(soju_db: Path) -> None:
    with open_soju_db(soju_db) as db, transaction(db):
        resolver = SojuTargetResolver(db)
        assert resolver.resolve_user("shurane") == 1
        assert resolver.resolve_network(1, "libera") == 1
        assert resolver.resolve_network(1, "irc.libera.chat:6697") == 1
        target = resolver.get_or_create_target(1, "#new")
        assert resolver.get_or_create_target(1, "#new") == target
        with pytest.raises(ValueError):
            resolver.resolve_user("unknown")
        with pytest.raises(ValueError):
            resolver.resolve_network(1, "unknown")


def test_unnamed_network_by_address(soju_db: Path) -> None:
    with open_soju_db(soju_db) as db:
        execute(db, "UPDATE Network SET name = NULL")
        assert SojuTargetResolver(db).resolve_network(1, "irc.libera.chat:6697") == 1
