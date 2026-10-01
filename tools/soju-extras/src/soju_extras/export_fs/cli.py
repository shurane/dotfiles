"""Incrementally mirror Soju SQLite backlog to compressed daily flat logs."""

from __future__ import annotations

import argparse
import datetime
import gzip
import re
import sys
from pathlib import Path

from soju_extras.db import open_soju_db
from soju_extras.models import ExportedLogRecord, MessageKind


def parse_irc_raw(raw: str, sender: str, text: str | None) -> tuple[MessageKind, str]:
    """Parse raw IRC line to determine display kind and clean text for flat logs."""
    clean_text = text or ""

    if "\x01ACTION " in raw or raw.endswith(" :\x01ACTION " + clean_text + "\x01"):
        action_match = re.search(r"\x01ACTION (.*?)\x01", raw)
        action_text = action_match.group(1) if action_match else clean_text
        return MessageKind.ACTION, action_text

    clean_raw = re.sub(r"^@\S+\s+", "", raw)
    m_cmd = re.search(r":\S+\s+([A-Z]+)\b", clean_raw)
    cmd = m_cmd.group(1).upper() if m_cmd else ""

    if cmd == "PRIVMSG":
        return MessageKind.PRIVMSG, clean_text
    elif cmd == "NOTICE":
        return MessageKind.NOTICE, clean_text
    elif cmd == "JOIN":
        m_host = re.search(r":(\S+!\S+)\s+JOIN", clean_raw)
        hostmask = m_host.group(1) if m_host else sender
        return MessageKind.JOIN, f"{sender} ({hostmask})"
    elif cmd == "PART":
        m_host = re.search(r":(\S+!\S+)\s+PART", clean_raw)
        hostmask = m_host.group(1) if m_host else sender
        reason = f" ({clean_text})" if clean_text else ""
        return MessageKind.PART, f"{sender} ({hostmask}){reason}"
    elif cmd == "QUIT":
        m_host = re.search(r":(\S+!\S+)\s+QUIT", clean_raw)
        hostmask = m_host.group(1) if m_host else sender
        reason = f" ({clean_text})" if clean_text else ""
        return MessageKind.QUIT, f"{sender} ({hostmask}){reason}"

    return MessageKind.SERVER, clean_text


class SojuFSExporter:
    """Incrementally extracts new messages from SQLite and appends to daily log files."""

    def __init__(
        self,
        db_path: Path,
        output_dir: Path,
        state_file: Path | None = None,
        compress: bool = True,
        dry_run: bool = False,
    ) -> None:
        self.db_path = db_path
        self.output_dir = output_dir
        self.compress = compress
        self.dry_run = dry_run
        self.state_file = state_file or (output_dir / ".last_synced_id")

    def get_last_synced_id(self) -> int:
        if self.state_file.exists():
            try:
                content = self.state_file.read_text(encoding="utf-8").strip()
                return int(content)
            except ValueError, OSError:
                return 0
        return 0

    def set_last_synced_id(self, last_id: int) -> None:
        if not self.dry_run:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(f"{last_id}\n", encoding="utf-8")

    def fetch_new_records(self, start_id: int) -> list[ExportedLogRecord]:
        query = """
        SELECT
            m.id,
            u.username,
            n.name AS network,
            t.target,
            m.time,
            m.sender,
            m.text,
            m.raw
        FROM Message m
        JOIN MessageTarget t ON m.target = t.id
        JOIN Network n ON t.network = n.id
        JOIN User u ON n.user = u.id
        WHERE m.id > ?
        ORDER BY m.id ASC
        """
        records: list[ExportedLogRecord] = []
        with open_soju_db(self.db_path, readonly=True) as db:
            for row in db.query(query, [start_id]):
                clean_iso = str(row["time"]).replace("Z", "+00:00")
                try:
                    dt = datetime.datetime.fromisoformat(clean_iso)
                except ValueError:
                    dt = datetime.datetime.now(datetime.UTC)

                kind, content = parse_irc_raw(row["raw"] or "", row["sender"] or "", row["text"])
                records.append(
                    ExportedLogRecord(
                        msg_id=row["id"],
                        username=row["username"],
                        network=row["network"],
                        target=row["target"],
                        timestamp=dt,
                        kind=kind,
                        sender=row["sender"] or "",
                        content=content,
                    )
                )
        return records

    def format_log_line(self, record: ExportedLogRecord) -> str:
        time_str = record.timestamp.strftime("%H:%M:%S")
        if record.kind == MessageKind.PRIVMSG:
            return f"[{time_str}] <{record.sender}> {record.content}\n"
        elif record.kind == MessageKind.ACTION:
            return f"[{time_str}] * {record.sender} {record.content}\n"
        elif record.kind == MessageKind.NOTICE:
            return f"[{time_str}] -{record.sender}- {record.content}\n"
        elif record.kind == MessageKind.JOIN:
            return f"[{time_str}] *** Joins: {record.content}\n"
        elif record.kind == MessageKind.PART:
            return f"[{time_str}] *** Parts: {record.content}\n"
        elif record.kind == MessageKind.QUIT:
            return f"[{time_str}] *** Quits: {record.content}\n"
        return f"[{time_str}] *** {record.content}\n"

    def get_target_log_path(self, record: ExportedLogRecord) -> Path:
        date_str = record.timestamp.strftime("%Y-%m-%d")
        ext = ".log.gz" if self.compress else ".log"
        filename = f"{date_str}{ext}"

        is_channel = record.target.startswith(("#", "&", "!", "+"))
        target_type = "channels" if is_channel else "users"

        safe_target = record.target.replace("/", "_").replace("\\", "_")
        return (
            self.output_dir
            / "users"
            / record.username
            / "networks"
            / record.network
            / target_type
            / safe_target
            / filename
        )

    def append_records_to_disk(self, records: list[ExportedLogRecord]) -> None:
        file_buffers: dict[Path, list[str]] = {}
        for record in records:
            path = self.get_target_log_path(record)
            file_buffers.setdefault(path, []).append(self.format_log_line(record))

        for path, lines in file_buffers.items():
            payload = "".join(lines).encode("utf-8")
            if self.dry_run:
                continue

            path.parent.mkdir(parents=True, exist_ok=True)
            if self.compress:
                compressed_chunk = gzip.compress(payload)
                with open(path, "ab") as f:
                    f.write(compressed_chunk)
            else:
                with open(path, "ab") as f:
                    f.write(payload)

    def run(self, force_all: bool = False, since_id: int | None = None) -> int:
        if not self.db_path.exists():
            print(f"Error: Soju database not found at {self.db_path}", file=sys.stderr)
            return 1

        if since_id is not None:
            start_id = since_id
        elif force_all:
            start_id = 0
        else:
            start_id = self.get_last_synced_id()

        records = self.fetch_new_records(start_id)
        if not records:
            return 0

        self.append_records_to_disk(records)
        latest_id = max(r.msg_id for r in records)
        self.set_last_synced_id(latest_id)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="soju-export-fs",
        description="Incrementally export Soju SQLite message history to compressed daily flat logs.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("/var/lib/soju/main.db"),
        help="Path to Soju SQLite database",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/var/lib/soju/logs"),
        help="Root directory for flat logs",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=None,
        help="Path to checkpoint state file",
    )
    parser.add_argument(
        "--uncompressed",
        action="store_true",
        help="Write plain .log files instead of .log.gz files",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Force export of all messages regardless of checkpoint",
    )
    parser.add_argument(
        "--since-id",
        type=int,
        default=None,
        help="Export messages starting from a specific message ID",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview export without writing files or updating checkpoint",
    )

    args = parser.parse_args()
    exporter = SojuFSExporter(
        db_path=args.db_path,
        output_dir=args.output_dir,
        state_file=args.state_file,
        compress=not args.uncompressed,
        dry_run=args.dry_run,
    )
    return exporter.run(force_all=args.all, since_id=args.since_id)


if __name__ == "__main__":
    sys.exit(main())
