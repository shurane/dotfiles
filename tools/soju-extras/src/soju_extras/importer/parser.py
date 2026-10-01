"""Stream log records while reporting invalid input with source locations."""

import gzip
from collections.abc import Generator, Iterator
from compression import zstd
from contextlib import contextmanager
from pathlib import Path

from soju_extras.models import WeeChatLogRecord


@contextmanager
def parse_weechat_log_file(
    file_path: Path, *, timezone: str = "UTC"
) -> Generator[Iterator[WeeChatLogRecord]]:
    """Keep the file lifetime explicit even when the consumer stops early."""

    def records(lines: Iterator[str]) -> Iterator[WeeChatLogRecord]:
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                record = WeeChatLogRecord.parse_line(line, timezone=timezone)
                if record is None:
                    raise ValueError("Expected a timestamp, tab, sender and message")
            except ValueError as exc:
                raise ValueError(f"{file_path}:{number}: {exc}") from exc
            yield record

    opener = {".gz": gzip.open, ".zst": zstd.open}.get(file_path.suffix, open)
    with opener(file_path, "rt", encoding="utf-8") as stream:
        yield records(iter(stream))
