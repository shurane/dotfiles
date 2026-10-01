"""Unit tests for models in soju package."""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from soju.models import MessageKind, SojuTargetFile, WeeChatLogRecord


def test_weechat_log_record_parse_privmsg() -> None:
    line = "2026-09-30 10:00:00\tshurane\thello world"
    rec = WeeChatLogRecord.parse_line(line)
    assert rec is not None
    assert rec.kind == MessageKind.PRIVMSG
    assert rec.sender_nick == "shurane"
    assert rec.clean_text == "hello world"


def test_weechat_log_record_immutability() -> None:
    rec = WeeChatLogRecord(
        raw_timestamp="2026-09-30 10:00:00",
        prefix="shurane",
        content="hello world",
        parsed_datetime=datetime.datetime(2026, 9, 30, 10, 0, 0, tzinfo=datetime.UTC),
        kind=MessageKind.PRIVMSG,
        sender_nick="shurane",
        clean_text="hello world",
    )
    with pytest.raises(ValidationError):
        attr = "sender_nick"
        setattr(rec, attr, "modified")


def test_soju_target_file_validation() -> None:
    valid = SojuTargetFile.from_path(Path("/var/log/irc.libera.#python.weechatlog"))
    assert valid is not None
    assert valid.network == "libera"
    assert valid.target == "#python"

    invalid = SojuTargetFile.from_path(Path("random_log.txt"))
    assert invalid is None
