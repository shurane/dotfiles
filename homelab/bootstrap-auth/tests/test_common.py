import sqlite3

import pytest
import typer

from bootstrap_auth.common import build_options, load_env, wait_for_sqlite_table
from bootstrap_auth.models import ServiceName


def test_load_env_parses_simple_quoted_and_ignored_lines(tmp_path):
    env_file = tmp_path / "homelab.env"
    env_file.write_text(
        """
        # ignored
        HOMELAB_AUTH_USERNAME=ehtesh
        HOMELAB_AUTH_PASSWORD="plugin88"
        EMPTY_LINE_IGNORED
        SINGLE='value'
        """
    )

    assert load_env(env_file) == {
        "HOMELAB_AUTH_USERNAME": "ehtesh",
        "HOMELAB_AUTH_PASSWORD": "plugin88",
        "SINGLE": "value",
    }


def test_build_options_parses_services_to_enum_values():
    options = build_options(skip_backup=True, parallel=True, services_value="qui,cwa")

    assert options.skip_backup is True
    assert options.parallel is True
    assert options.services == (ServiceName.QUI, ServiceName.CWA)


def test_build_options_rejects_unknown_services():
    with pytest.raises(typer.BadParameter, match="unknown services"):
        build_options(skip_backup=False, parallel=False, services_value="qui,nope")


def test_build_options_rejects_empty_services():
    with pytest.raises(typer.BadParameter, match="must include at least one service"):
        build_options(skip_backup=False, parallel=False, services_value=" , ")


def test_wait_for_sqlite_table_returns_when_table_exists(tmp_path):
    db_path = tmp_path / "app.db"
    with sqlite3.connect(db_path) as db:
        db.execute("create table user (id integer primary key)")

    wait_for_sqlite_table(db_path, "user", timeout_seconds=1)


def test_wait_for_sqlite_table_times_out_for_missing_table(tmp_path):
    db_path = tmp_path / "app.db"
    with sqlite3.connect(db_path) as db:
        db.execute("create table other (id integer primary key)")

    with pytest.raises(RuntimeError, match="timed out waiting for table"):
        wait_for_sqlite_table(db_path, "user", timeout_seconds=0)
