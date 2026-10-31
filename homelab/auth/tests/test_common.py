import sqlite3
from pathlib import Path

import pytest
import typer
from bootstrap_auth.common import build_options, format_path, load_env, wait_for_sqlite_table
from bootstrap_auth.models import ServiceName


def test_load_env_parses_simple_quoted_and_ignored_lines(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
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


def test_build_options_parses_services_to_enum_values() -> None:
    options = build_options(skip_backup=True, parallel=True, services_value="qui,jellyfin")

    assert options.apply is False
    assert options.skip_backup is True
    assert options.parallel is True
    assert options.services == (ServiceName.QUI, ServiceName.JELLYFIN)


def test_build_options_accepts_explicit_apply() -> None:
    options = build_options(skip_backup=False, parallel=False, services_value="jellyfin", apply=True)

    assert options.apply is True


def test_build_options_rejects_unknown_services() -> None:
    with pytest.raises(typer.BadParameter, match="unknown services"):
        build_options(skip_backup=False, parallel=False, services_value="qui,nope")


def test_build_options_rejects_empty_services() -> None:
    with pytest.raises(typer.BadParameter, match="must include at least one service"):
        build_options(skip_backup=False, parallel=False, services_value=" , ")


def test_wait_for_sqlite_table_returns_when_table_exists(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    with sqlite3.connect(db_path) as db:
        db.execute("create table user (id integer primary key)")

    wait_for_sqlite_table(db_path, "user", timeout_seconds=1)


def test_wait_for_sqlite_table_times_out_for_missing_table(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    with sqlite3.connect(db_path) as db:
        db.execute("create table other (id integer primary key)")

    with pytest.raises(RuntimeError, match="timed out waiting for table"):
        wait_for_sqlite_table(db_path, "user", timeout_seconds=0)


def test_format_path_home_relative() -> None:
    home = Path.home()
    test_file = home / "dotfiles" / "test.txt"
    assert format_path(test_file) == "~/dotfiles/test.txt"


def test_format_path_non_home() -> None:
    test_file = Path("/tmp/outside/test.txt")
    assert format_path(test_file) == "/tmp/outside/test.txt"


def test_format_path_none() -> None:
    assert format_path(None) == "<none>"
