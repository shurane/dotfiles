"""WeeChat log file parser streaming records."""

from __future__ import annotations

import gzip
from collections.abc import Iterator
from pathlib import Path

from soju_extras.models import WeeChatLogRecord


def parse_weechat_log_file(file_path: Path) -> Iterator[WeeChatLogRecord]:
    """Stream parsed WeeChatLogRecord instances from a log file (plain or .gz)."""
    if file_path.suffix == ".gz":
        with gzip.open(file_path, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                record = WeeChatLogRecord.parse_line(line)
                if record is not None:
                    yield record
    else:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                record = WeeChatLogRecord.parse_line(line)
                if record is not None:
                    yield record
