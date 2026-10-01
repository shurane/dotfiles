"""Database fixtures copied from a pinned upstream Soju release schema."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest


@pytest.fixture
def soju_db(tmp_path: Path) -> Path:
    path = tmp_path / "soju.db"
    schema = (Path(__file__).parent / "fixtures/soju_schema.sql").read_text()
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(schema)
        db.execute(
            "INSERT INTO User (id, username, created_at) VALUES (1, 'shurane', ?)",
            ("2026-01-01T00:00:00.000Z",),
        )
        db.execute(
            "INSERT INTO Network (id, user, name, addr) VALUES (1, 1, 'libera', ?)",
            ("irc.libera.chat:6697",),
        )
        db.execute("INSERT INTO MessageTarget (id, network, target) VALUES (1, 1, '#python')")
    return path


def add_message(
    path: Path, text: str = "hello world", *, time: str = "2026-09-30T10:00:00.123Z"
) -> None:
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "INSERT INTO Message (target, raw, time, sender, text) VALUES (1, ?, ?, 'alice', ?)",
            (f"@time={time} :alice!u@h PRIVMSG #python :{text}", time, text),
        )
