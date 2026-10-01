"""Pydantic data boundary models and parser logic for WeeChat and Soju."""

from __future__ import annotations

import datetime
import re
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

# Regex patterns for WeeChat log parsing
LOG_FILENAME_RE = re.compile(r"^irc\.(?P<network>[^.]+)\.(?P<target>.+)\.weechatlog(?:\.gz)?$")
TIMESTAMP_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})(?:\.\d+)?(?:Z)?"
)

# Strips ANSI escape codes, WeeChat color/format codes, and IRC color codes
COLOR_STRIP_RE = re.compile(
    r"\x1b\[[0-9;]*[a-zA-Z]|\x19(?:\d{2}|F\d{2}|B\d{2}|\*|\-|\/|b|i|u|r|v)?|"
    r"\x03(?:\d{1,2}(?:,\d{1,2})?)?|[\x02\x0f\x16\x1d\x1f]"
)


class MessageKind(StrEnum):
    PRIVMSG = "PRIVMSG"
    JOIN = "JOIN"
    PART = "PART"
    QUIT = "QUIT"
    ACTION = "ACTION"
    NOTICE = "NOTICE"
    SERVER = "SERVER"


class WeeChatLogRecord(BaseModel):
    """Parsed single line from a WeeChat log file."""

    model_config = ConfigDict(frozen=True)

    raw_timestamp: str
    prefix: str
    content: str
    parsed_datetime: datetime.datetime
    kind: MessageKind
    sender_nick: str
    sender_hostmask: str | None = None
    clean_text: str

    @classmethod
    def parse_line(cls, line: str) -> WeeChatLogRecord | None:
        line = line.rstrip("\r\n")
        if not line:
            return None

        line = COLOR_STRIP_RE.sub("", line)
        parts = line.split("\t", maxsplit=2)
        if len(parts) < 2:
            return None

        ts_raw = parts[0].strip()
        prefix = parts[1].strip()
        content = parts[2] if len(parts) > 2 else ""

        m_ts = TIMESTAMP_RE.match(ts_raw)
        if not m_ts:
            return None

        date_str = m_ts.group("date")
        time_str = m_ts.group("time")
        try:
            dt = datetime.datetime.fromisoformat(f"{date_str}T{time_str}+00:00")
        except ValueError:
            return None

        sender_hostmask: str | None = None

        if prefix == "-->":
            kind = MessageKind.JOIN
            sender_nick = content.split(" ")[0].lstrip("@+~&%")
            clean_text = content
            hm_match = re.search(r"\(([^)]+@[^)]+)\)", content)
            sender_hostmask = (
                f"{sender_nick}!{hm_match.group(1)}"
                if hm_match
                else f"{sender_nick}!unknown@unknown"
            )
        elif prefix == "<--":
            kind = MessageKind.QUIT if "quit" in content.lower() else MessageKind.PART
            sender_nick = content.split(" ")[0].lstrip("@+~&%")
            clean_text = content
            hm_match = re.search(r"\(([^)]+@[^)]+)\)", content)
            sender_hostmask = (
                f"{sender_nick}!{hm_match.group(1)}"
                if hm_match
                else f"{sender_nick}!unknown@unknown"
            )
        elif prefix == "--":
            m_notice = re.match(r"^(?:Pv)?Notice\(([^)]+)\):\s*(.*)$", content)
            if m_notice:
                kind = MessageKind.NOTICE
                sender_nick = m_notice.group(1)
                clean_text = m_notice.group(2)
                sender_hostmask = f"{sender_nick}!services@services"
            else:
                kind = MessageKind.SERVER
                sender_nick = "*"
                clean_text = content
                sender_hostmask = "*"
        elif prefix in ("*", " *") or prefix.lstrip("@+~&%") == "*":
            kind = MessageKind.ACTION
            action_parts = content.split(" ", 1)
            sender_nick = action_parts[0]
            clean_text = action_parts[1] if len(action_parts) > 1 else ""
            sender_hostmask = f"{sender_nick}!~user@unknown"
        else:
            clean_prefix = prefix.lstrip("@+~&%")
            if content.startswith("/me ") or content.startswith("\x01ACTION "):
                kind = MessageKind.ACTION
                sender_nick = clean_prefix
                clean_text = (
                    content.removeprefix("\x01ACTION ").removesuffix("\x01").removeprefix("/me ")
                )
            elif clean_prefix.startswith("*") and len(clean_prefix) > 1:
                kind = MessageKind.ACTION
                sender_nick = clean_prefix.lstrip("*")
                clean_text = content
            else:
                kind = MessageKind.PRIVMSG
                sender_nick = clean_prefix
                clean_text = content
            sender_hostmask = f"{sender_nick}!~user@unknown"

        return cls(
            raw_timestamp=ts_raw,
            prefix=prefix,
            content=content,
            parsed_datetime=dt,
            kind=kind,
            sender_nick=sender_nick,
            sender_hostmask=sender_hostmask,
            clean_text=clean_text,
        )


class SojuTargetFile(BaseModel):
    """Metadata representing a WeeChat log file targeted for import."""

    model_config = ConfigDict(frozen=True)

    source_path: Path
    network: str
    target: str

    @classmethod
    def from_path(cls, path: Path) -> SojuTargetFile | None:
        match = LOG_FILENAME_RE.match(path.name)
        if not match:
            return None
        return cls(
            source_path=path,
            network=match.group("network").lower(),
            target=match.group("target").lower(),
        )


class SojuMessage(BaseModel):
    """Record representing a message in Soju's SQLite Message table."""

    model_config = ConfigDict(frozen=True)

    id: int | None = None
    target_id: int
    raw: str
    time: str
    sender: str
    text: str | None = None


class ExportedLogRecord(BaseModel):
    """Record extracted from Soju database for filesystem export."""

    model_config = ConfigDict(frozen=True)

    msg_id: int
    username: str
    network: str
    target: str
    timestamp: datetime.datetime
    kind: MessageKind
    sender: str
    content: str


class SearchQuery(BaseModel):
    """Parameters for an FTS5 search query."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    pattern: str = Field(min_length=1, description="Search query string or FTS5 phrase")
    target: str | None = Field(default=None, description="Optional channel or nickname")
    network: str | None = Field(default=None, description="Optional IRC network filter")
    db_path: Path = Field(
        default=Path("/var/lib/soju/main.db"),
        description="Path to Soju SQLite database",
    )
    limit: int = Field(default=100, ge=1, le=10000, description="Max results")


class SearchResult(BaseModel):
    """A single matched IRC message from SQLite FTS5."""

    model_config = ConfigDict(frozen=True)

    message_id: int
    timestamp_str: str
    network: str
    target: str
    sender_nick: str
    text: str
