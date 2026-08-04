import sqlite3

import pytest
from werkzeug.security import check_password_hash

from bootstrap_auth.models import HomelabAuth
from bootstrap_auth.services.cwa import write_cwa_admin_user


def create_cwa_db(path):
    with sqlite3.connect(path) as db:
        db.execute(
            """
            create table user (
                id integer primary key,
                name text unique,
                email text unique,
                password text
            )
            """
        )
        db.execute(
            "insert into user (id, name, email, password) values (1, 'admin', 'admin@example.org', 'old')"
        )


def test_write_cwa_admin_user_updates_id_one(tmp_path):
    db_path = tmp_path / "app.db"
    create_cwa_db(db_path)
    auth = HomelabAuth.model_validate(
        {
            "HOMELAB_AUTH_USERNAME": "ehtesh",
            "HOMELAB_AUTH_PASSWORD": "plugin88",
        }
    )

    write_cwa_admin_user(db_path, auth)

    with sqlite3.connect(db_path) as db:
        row = db.execute("select name, email, password from user where id = 1").fetchone()

    assert row[0] == "ehtesh"
    assert row[1] == "admin@localhost"
    assert check_password_hash(row[2], "plugin88")


def test_write_cwa_admin_user_rejects_conflicting_user(tmp_path):
    db_path = tmp_path / "app.db"
    create_cwa_db(db_path)
    with sqlite3.connect(db_path) as db:
        db.execute(
            "insert into user (id, name, email, password) values (2, 'ehtesh', 'other@example.org', 'old')"
        )
    auth = HomelabAuth.model_validate(
        {
            "HOMELAB_AUTH_USERNAME": "ehtesh",
            "HOMELAB_AUTH_PASSWORD": "plugin88",
        }
    )

    with pytest.raises(RuntimeError, match="found another Calibre-Web-Automated user"):
        write_cwa_admin_user(db_path, auth)
