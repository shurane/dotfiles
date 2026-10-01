"""Atomic import, read receipts, compressed input, and CLI boundaries."""

import gzip
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from soju_extras.importer.cli import SojuLogImporter, main
from soju_extras.importer.parser import parse_weechat_log_file


def make_log(tmp_path: Path, text: str, *, compressed: bool = False) -> Path:
    root = tmp_path / "logs"
    root.mkdir()
    path = root / ("irc.libera.#python.weechatlog" + (".gz" if compressed else ""))
    if compressed:
        path.write_bytes(gzip.compress(text.encode()))
    else:
        path.write_text(text)
    return root


def test_import_rolls_back_messages_when_later_insert_fails(soju_db: Path, tmp_path: Path) -> None:
    logs = make_log(
        tmp_path, "2026-09-30 10:00:00\talice\thello\n2026-09-30 10:00:01\talice\treject\n"
    )
    with closing(sqlite3.connect(soju_db)) as db:
        db.execute(
            "CREATE TRIGGER reject_message BEFORE INSERT ON Message WHEN NEW.text = 'reject' BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        SojuLogImporter(logs, db_path=soju_db).run()
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT count(*) FROM Message").fetchone()[0] == 0
        assert (
            db.execute("SELECT count(*) FROM MessageFTS WHERE MessageFTS MATCH 'hello'").fetchone()[
                0
            ]
            == 0
        )
    with closing(sqlite3.connect(soju_db)) as db:
        db.execute("DROP TRIGGER reject_message")
    assert SojuLogImporter(logs, db_path=soju_db).run() == 2


def test_invalid_line_aborts_file_with_location(soju_db: Path, tmp_path: Path) -> None:
    logs = make_log(
        tmp_path, "2026-09-30 10:00:00\talice\thello\n2026-09-30 10:00:00garbage\talice\tbad\n"
    )
    with pytest.raises(ValueError, match=r"weechatlog:2:"):
        SojuLogImporter(logs, db_path=soju_db, batch_size=1).run()
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT count(*) FROM Message").fetchone()[0] == 0


def test_compressed_import_keeps_later_receipt(soju_db: Path, tmp_path: Path) -> None:
    logs = make_log(tmp_path, "2026-09-30 10:00:00\talice\thello\n", compressed=True)
    with closing(sqlite3.connect(soju_db)) as db, db:
        db.execute(
            "INSERT INTO ReadReceipt(network,target,timestamp) VALUES (1,'#python','2026-10-01T00:00:00.000Z')"
        )
    assert SojuLogImporter(logs, db_path=soju_db).run() == 1
    with closing(sqlite3.connect(soju_db)) as db:
        assert (
            db.execute("SELECT timestamp FROM ReadReceipt").fetchone()[0]
            == "2026-10-01T00:00:00.000Z"
        )


def test_dry_run_without_database(tmp_path: Path) -> None:
    logs = make_log(tmp_path, "2026-09-30 10:00:00\talice\thello\n")
    missing = tmp_path / "missing.db"
    assert SojuLogImporter(logs, db_path=missing, dry_run=True).run() == 1
    assert not missing.exists()
    assert main(["--logs-dir", str(logs), "--db-path", str(missing)]) == 2
    assert main(["--logs-dir", str(logs), "--dry-run", "--batch-size", "0"]) == 2
    assert main(["--logs-dir", str(logs / "missing"), "--dry-run"]) == 2
    with pytest.raises(SystemExit) as exc:
        main(["--mode", "fs"])
    assert exc.value.code == 2


def test_explicit_network_mapping(soju_db: Path, tmp_path: Path) -> None:
    logs = make_log(tmp_path, "2026-09-30 10:00:00\talice\thello\n")
    with closing(sqlite3.connect(soju_db)) as db, db:
        db.execute("UPDATE Network SET name = NULL")
    assert (
        main(
            [
                "--logs-dir",
                str(logs),
                "--db-path",
                str(soju_db),
                "--network-map",
                "libera=irc.libera.chat:6697",
            ]
        )
        == 0
    )


def test_parser_context_closes_on_early_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logs = make_log(tmp_path, "2026-09-30 10:00:00\talice\thi\n" * 2)
    path = next(logs.iterdir())
    stream = path.open()
    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", lambda *args, **kwargs: stream)
        with parse_weechat_log_file(path) as records:
            next(records)
    assert stream.closed


@pytest.mark.parametrize("initial_copies", [0, 1, 2])
def test_empty_and_populated_targets_preserve_source_multiplicity(
    soju_db: Path, tmp_path: Path, initial_copies: int
) -> None:
    line = "2026-09-30 10:00:00\talice\trepeated\n"
    logs = make_log(tmp_path, line * initial_copies)
    importer = SojuLogImporter(logs, db_path=soju_db, batch_size=1)
    assert importer.run() == initial_copies
    next(logs.iterdir()).write_text(line * 3)
    assert importer.run() == 3 - initial_copies
    assert importer.run() == 0
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT count(*) FROM Message").fetchone()[0] == 3
        assert (
            db.execute(
                "SELECT count(*) FROM MessageFTS WHERE MessageFTS MATCH 'repeated'"
            ).fetchone()[0]
            == 3
        )


@pytest.mark.parametrize("receipt", [None, "2026-09-29T00:00:00.000Z", "2026-10-01T00:00:00.000Z"])
def test_import_preserves_read_and_delivery_receipts(
    soju_db: Path, tmp_path: Path, receipt: str | None
) -> None:
    logs = make_log(tmp_path, "2026-09-30 10:00:00\talice\thello\n")
    with closing(sqlite3.connect(soju_db)) as db, db:
        if receipt is not None:
            db.execute(
                "INSERT INTO ReadReceipt(network,target,timestamp) VALUES(1,'#python',?)",
                (receipt,),
            )
        db.execute(
            "INSERT INTO DeliveryReceipt(network,target,client,internal_msgid) VALUES(1,'#python','weechat','42')"
        )
        before = [
            db.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("ReadReceipt", "DeliveryReceipt")
        ]
    SojuLogImporter(logs, db_path=soju_db).run()
    with closing(sqlite3.connect(soju_db)) as db:
        assert before == [
            db.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("ReadReceipt", "DeliveryReceipt")
        ]


def test_discovers_nested_rotated_and_zstd_logs(soju_db: Path, tmp_path: Path) -> None:
    from compression import zstd

    logs = tmp_path / "logs"
    nested = logs / "machine/2025/09"
    nested.mkdir(parents=True)
    for index, suffix in enumerate(["", ".1", ".2.gz", ".3.zst"]):
        data = f"2025-09-01 10:00:0{index}\talice\tmessage{index}\n".encode()
        if suffix.endswith(".gz"):
            data = gzip.compress(data)
        elif suffix.endswith(".zst"):
            data = zstd.compress(data)
        (nested / f"irc.libera.#python.weechatlog{suffix}").write_bytes(data)
    importer = SojuLogImporter(logs, db_path=soju_db)
    assert len(importer.discover_targets()) == 4
    assert importer.run() == 4
    assert importer.run() == 0


def test_unsupported_log_aborts_before_any_import(soju_db: Path, tmp_path: Path) -> None:
    logs = make_log(tmp_path, "2026-09-30 10:00:00\talice\thello\n")
    (logs / "irc.libera.#python.weechatlog.bz2").write_bytes(b"unsupported")
    assert main(["--logs-dir", str(logs), "--db-path", str(soju_db)]) == 2
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT count(*) FROM Message").fetchone()[0] == 0


def test_no_matching_logs_is_error(tmp_path: Path) -> None:
    assert main(["--logs-dir", str(tmp_path), "--dry-run"]) == 2


@pytest.mark.parametrize("live_time", ["2026-09-30T10:00:00.000Z", "2026-09-30T10:00:00.789Z"])
def test_live_overlap_aborts_whole_file(soju_db: Path, tmp_path: Path, live_time: str) -> None:
    logs = make_log(tmp_path, "2026-09-30 09:00:00\tbob\tnew\n2026-09-30 10:00:00\talice\thello\n")
    with closing(sqlite3.connect(soju_db)) as db, db:
        db.execute(
            "INSERT INTO Message(target,time,raw,sender,text) VALUES(1,?,?,?,?)",
            (
                live_time,
                f"@time={live_time};msgid=abc :alice!real@host PRIVMSG #python :hello",
                "alice",
                "hello",
            ),
        )
    assert main(["--logs-dir", str(logs), "--db-path", str(soju_db)]) == 2
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT count(*) FROM Message").fetchone()[0] == 1
    assert SojuLogImporter(logs, db_path=soju_db, allow_overlap=True).run() == 2


def test_before_cutoff_excludes_post_cutover_log_messages(soju_db: Path, tmp_path: Path) -> None:
    logs = make_log(
        tmp_path,
        "2026-09-30 09:59:59\talice\told\n2026-09-30 10:00:00\talice\tboundary\n2026-09-30 10:00:01\talice\tnew\n",
    )
    args = [
        "--logs-dir",
        str(logs),
        "--db-path",
        str(soju_db),
        "--before",
        "2026-09-30T05:00:00-05:00",
    ]
    assert main(args + ["--dry-run"]) == 0
    assert main(args) == 0
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT text FROM Message").fetchall() == [("old",)]
    assert main(args) == 0
    assert main(args[:-1] + ["not-a-time"]) == 2


def test_since_is_inclusive_and_combines_with_before(soju_db: Path, tmp_path: Path) -> None:
    logs = make_log(
        tmp_path,
        "2026-06-30 23:59:59\talice\told\n"
        "2026-07-01 00:00:00\talice\tboundary\n"
        "2026-07-01 07:00:01Z\talice\tnew\n"
        "2026-07-01 07:00:02Z\talice\tafter\n",
    )
    args = [
        "--logs-dir",
        str(logs),
        "--db-path",
        str(soju_db),
        "--timezone",
        "America/Los_Angeles",
        "--since",
        "2026-07-01T07:00:00Z",
        "--before",
        "2026-07-01T07:00:02Z",
    ]
    assert main(args + ["--dry-run"]) == 0
    assert main(args) == 0
    assert main(args) == 0
    with closing(sqlite3.connect(soju_db)) as db:
        assert db.execute("SELECT text FROM Message ORDER BY id").fetchall() == [
            ("boundary",),
            ("new",),
        ]
    assert main(args[:-1] + ["2026-07-01T07:00:00Z"]) == 2


def test_server_and_core_logs_are_explicitly_excluded(
    soju_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    logs = make_log(tmp_path, "2026-09-30 10:00:00\talice\thello\n")
    for name in ["irc.server.libera.weechatlog", "core.weechat.weechatlog"]:
        (logs / name).write_text("not a conversation")
    assert SojuLogImporter(logs, db_path=soju_db).run() == 1
    assert capsys.readouterr().err.count("excluded non-conversation log") == 2
