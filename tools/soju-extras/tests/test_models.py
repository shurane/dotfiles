"""Timestamp boundaries include offset conversion, precision and DST ambiguity."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from whenever import Instant

from soju_extras.models import SojuTargetFile, WeeChatLogRecord
from soju_extras.time import soju_timestamp


@pytest.mark.parametrize(
    ("timestamp", "timezone", "expected"),
    [
        ("2026-09-30 10:00:00", "UTC", "2026-09-30T10:00:00.000Z"),
        ("2026-09-30 10:00:00", "America/Chicago", "2026-09-30T15:00:00.000Z"),
        ("2026-01-30 10:00:00", "America/Chicago", "2026-01-30T16:00:00.000Z"),
        ("2026-09-30 10:00:00.123456789-05:00", "UTC", "2026-09-30T15:00:00.123Z"),
        ("2026-09-30 23:30:00-05:00", "UTC", "2026-10-01T04:30:00.000Z"),
        ("2026-09-30 10:00:00.123Z", "America/Chicago", "2026-09-30T10:00:00.123Z"),
    ],
)
def test_timestamp(timestamp: str, timezone: str, expected: str) -> None:
    rec = WeeChatLogRecord.parse_line(f"{timestamp}\talice\thello", timezone=timezone)
    assert rec is not None
    assert isinstance(rec.parsed_datetime, Instant)
    assert soju_timestamp(rec.parsed_datetime) == expected


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-03-08 02:30:00",
        "2026-11-01 01:30:00",
        "2026-09-30 10:00:00garbage",
        "2026-02-30 10:00:00",
    ],
)
def test_reject_invalid_or_ambiguous_time(timestamp: str) -> None:
    with pytest.raises(ValueError):
        WeeChatLogRecord.parse_line(f"{timestamp}\talice\thello", timezone="America/Chicago")


def test_frozen_record() -> None:
    rec = WeeChatLogRecord.parse_line("2026-09-30 10:00:00\talice\thi")
    assert rec is not None
    with pytest.raises(ValidationError):
        attribute = "sender_nick"
        setattr(rec, attribute, "bob")


def test_filename() -> None:
    target = SojuTargetFile.from_path(Path("irc.libera.#Python.weechatlog.gz"))
    assert target is not None
    assert target.target == "#Python"
    assert SojuTargetFile.from_path(Path("unrelated.txt")) is None
