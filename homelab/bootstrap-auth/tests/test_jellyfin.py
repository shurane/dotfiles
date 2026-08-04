import sqlite3

import pytest
from bootstrap_auth.models import HomelabAuth
from bootstrap_auth.services.jellyfin import select_jellyfin_user_id, upsert_jellyfin_admin_permissions


def auth() -> HomelabAuth:
    return HomelabAuth.model_validate(
        {
            "HOMELAB_AUTH_USERNAME": "ehtesh",
            "HOMELAB_AUTH_PASSWORD": "plugin88",
        }
    )


def create_users_table(db: sqlite3.Connection) -> None:
    db.execute(
        """
        create table Users (
            Id text primary key,
            Username text,
            NormalizedUsername text
        )
        """
    )


def test_select_jellyfin_user_id_returns_matching_user() -> None:
    with sqlite3.connect(":memory:") as db:
        create_users_table(db)
        db.execute("insert into Users (Id, Username, NormalizedUsername) values ('abc', 'ehtesh', 'EHTESH')")

        assert select_jellyfin_user_id(db, auth()) == "abc"


def test_select_jellyfin_user_id_returns_only_user_when_no_match() -> None:
    with sqlite3.connect(":memory:") as db:
        create_users_table(db)
        db.execute("insert into Users (Id, Username, NormalizedUsername) values ('abc', 'admin', 'ADMIN')")

        assert select_jellyfin_user_id(db, auth()) == "abc"


def test_select_jellyfin_user_id_rejects_multiple_unmatched_users() -> None:
    with sqlite3.connect(":memory:") as db:
        create_users_table(db)
        db.execute("insert into Users (Id, Username, NormalizedUsername) values ('abc', 'admin', 'ADMIN')")
        db.execute("insert into Users (Id, Username, NormalizedUsername) values ('def', 'other', 'OTHER')")

        with pytest.raises(RuntimeError, match="found 2 Jellyfin users"):
            select_jellyfin_user_id(db, auth())


def test_upsert_jellyfin_admin_permissions_replaces_existing_rows() -> None:
    with sqlite3.connect(":memory:") as db:
        db.execute(
            """
            create table Permissions (
                Kind integer,
                Permission_Permissions_Guid text,
                RowVersion integer,
                UserId text,
                Value integer
            )
            """
        )
        db.execute(
            """
            create table Preferences (
                Kind integer,
                Preference_Preferences_Guid text,
                RowVersion integer,
                UserId text,
                Value text
            )
            """
        )
        db.execute("insert into Permissions (Kind, UserId, Value) values (99, 'abc', 0)")
        db.execute("insert into Preferences (Kind, UserId, Value) values (99, 'abc', 'old')")

        upsert_jellyfin_admin_permissions(db, "abc")

        permission_count = db.execute("select count(*) from Permissions where UserId = 'abc'").fetchone()[0]
        preference_count = db.execute("select count(*) from Preferences where UserId = 'abc'").fetchone()[0]
        stale_count = db.execute("select count(*) from Permissions where Kind = 99").fetchone()[0]

    assert permission_count == 24
    assert preference_count == 13
    assert stale_count == 0
