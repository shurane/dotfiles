"""Export chronological daily logs with bounded batches and recoverable file updates."""

import argparse
import os
import sqlite3
import stat
import sys
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from whenever import Instant

from soju_extras.db import open_soju_db, query, query_rows
from soju_extras.export_fs.ordering import LogOrder, inspect_log, line_time, rewrite_log, write_log
from soju_extras.export_fs.storage import (
    AppendJournal,
    ExportIdentity,
    FileOffset,
    atomic_write,
    durable_mkdir,
    export_lock,
    sync_directory,
)
from soju_extras.models import DatabaseMessage, ExportedLogRecord, MessageKind


class ExportOptions(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    db_path: Path
    output_dir: Path
    state_file: Path | None = None
    compress: bool = True
    dry_run: bool = False
    batch_size: int = Field(default=5000, ge=1, le=100000)


class MaximumID(BaseModel):
    model_config = ConfigDict(strict=True)
    id: int


def path_component(value: str) -> str:
    """Reversible encoding, preserving familiar names such as #python."""
    if not value:
        raise ValueError("Empty output path component")
    encoded = quote(value, safe="#&!+@")
    return encoded.replace(".", "%2E") if encoded in (".", "..") else encoded


def parse_irc_raw(raw: str, sender: str, text: str | None) -> tuple[MessageKind, str]:
    """Extract the command/prefix/trailing parameter from an IRC message."""
    rest = raw
    if rest.startswith("@"):
        _, _, rest = rest.partition(" ")
    hostmask = sender
    if rest.startswith(":"):
        prefix, _, rest = rest.partition(" ")
        hostmask = prefix[1:]
    command, _, params = rest.partition(" ")
    trailing = params[1:] if params.startswith(":") else params.partition(" :")[2]
    content = text if text is not None else trailing
    if command == "PRIVMSG" and trailing.startswith("\x01ACTION ") and trailing.endswith("\x01"):
        return MessageKind.ACTION, trailing[8:-1]
    if command in ("PRIVMSG", "NOTICE"):
        return MessageKind(command), content
    if command in ("JOIN", "PART", "QUIT"):
        reason = f" ({trailing})" if trailing and command != "JOIN" else ""
        return MessageKind(command), f"{sender} ({hostmask}){reason}"
    return MessageKind.SERVER, content


class SojuFSExporter:
    def __init__(
        self,
        db_path: Path,
        output_dir: Path,
        state_file: Path | None = None,
        compress: bool = True,
        dry_run: bool = False,
        batch_size: int = 5000,
    ) -> None:
        self.options = ExportOptions(
            db_path=db_path,
            output_dir=output_dir,
            state_file=state_file,
            compress=compress,
            dry_run=dry_run,
            batch_size=batch_size,
        )
        self.db_path = db_path
        self.output_dir = output_dir.resolve()
        self.state_file = (state_file or (self.output_dir / ".last_synced_id")).resolve()
        self.journal_file = self.output_dir / ".append-journal.json"
        self.compress = compress
        self.dry_run = dry_run
        self._log_orders: dict[Path, tuple[int, int, LogOrder]] = {}

    def get_last_synced_id(self) -> int:
        try:
            value = int(self.state_file.read_text(encoding="utf-8").strip())
        except FileNotFoundError:
            return 0
        if value < 0:
            raise ValueError("Checkpoint must not be negative")
        return value

    def set_last_synced_id(self, last_id: int) -> None:
        atomic_write(self.state_file, f"{last_id}\n")

    def fetch_new_records(
        self, start_id: int, end_id: int | None = None
    ) -> list[ExportedLogRecord]:
        records: list[ExportedLogRecord] = []
        with (
            open_soju_db(self.db_path, readonly=True) as db,
            query(
                db,
                DatabaseMessage,
                """
                SELECT m.id AS msg_id, u.username,
                       coalesce(nullif(n.name, ''), n.addr) AS network,
                       t.target, m.time, m.sender, m.text, m.raw
                FROM Message m JOIN MessageTarget t ON m.target = t.id
                JOIN Network n ON t.network = n.id JOIN User u ON n.user = u.id
                WHERE m.id > ? AND m.id <= ? ORDER BY m.id LIMIT ?
            """,
                (start_id, end_id if end_id is not None else 2**63 - 1, self.options.batch_size),
            ) as rows,
        ):
            for row in rows:
                kind, content = parse_irc_raw(row.raw, row.sender, row.text)
                records.append(
                    ExportedLogRecord(
                        msg_id=row.msg_id,
                        username=row.username,
                        network=row.network,
                        target=row.target,
                        timestamp=Instant.parse_iso(row.time),
                        kind=kind,
                        sender=row.sender,
                        content=content,
                    )
                )
        return records

    def format_log_line(self, record: ExportedLogRecord) -> str:
        time = record.timestamp.format_iso(unit="millisecond")[11:-1]
        match record.kind:
            case MessageKind.PRIVMSG:
                body = f"<{record.sender}> {record.content}"
            case MessageKind.ACTION:
                body = f"* {record.sender} {record.content}"
            case MessageKind.NOTICE:
                body = f"-{record.sender}- {record.content}"
            case MessageKind.JOIN:
                body = f"*** Joins: {record.content}"
            case MessageKind.PART:
                body = f"*** Parts: {record.content}"
            case MessageKind.QUIT:
                body = f"*** Quits: {record.content}"
            case _:
                body = f"*** {record.content}"
        return f"[{time}] {body}\n"

    def _contained_path(self, relative: str) -> Path:
        path = self.output_dir / relative
        if not path.resolve().is_relative_to(self.output_dir):
            raise ValueError(f"Output path escapes the export directory: {relative!r}")
        return path

    def get_target_log_path(self, record: ExportedLogRecord) -> Path:
        kind = "channels" if record.target.startswith(("#", "&", "!", "+")) else "users"
        ext = ".log.gz" if self.compress else ".log"
        path = (
            Path("users")
            / path_component(record.username)
            / "networks"
            / path_component(record.network)
            / kind
            / path_component(record.target)
            / (record.timestamp.format_iso()[:10] + ext)
        )
        return self._contained_path(str(path))

    def _recover(self) -> None:
        if not self.journal_file.exists():
            return
        journal = AppendJournal.model_validate_json(self.journal_file.read_bytes())
        checkpoint = self.get_last_synced_id()
        if checkpoint == journal.previous_id:
            self._log_orders.clear()
            for entry in journal.files:
                path = self._contained_path(entry.relative_path)
                if entry.backup_path is not None:
                    backup = self._contained_path(entry.backup_path)
                    if backup.exists():
                        os.replace(backup, path)
                    # No backup means replacement had not started, or a previous
                    # recovery already restored the original via atomic rename.
                    elif not path.exists() or path.stat().st_size != entry.size:
                        raise ValueError(f"Cannot recover replacement without its backup: {path}")
                elif entry.size is None:
                    path.unlink(missing_ok=True)
                else:
                    if not path.exists() or path.stat().st_size < entry.size:
                        raise ValueError(f"Cannot recover shortened/missing output: {path}")
                    with path.open("r+b") as stream:
                        stream.truncate(entry.size)
                        stream.flush()
                        os.fsync(stream.fileno())
                if path.parent.exists():
                    sync_directory(path.parent)
        elif checkpoint != journal.latest_id:
            raise ValueError("Checkpoint does not match the pending export journal")
        for entry in journal.files:
            for temporary in (entry.backup_path, entry.replacement_path, entry.sort_path):
                if temporary is not None:
                    path = self._contained_path(temporary)
                    path.unlink(missing_ok=True)
                    sync_directory(path.parent)
        self.journal_file.unlink()
        sync_directory(self.output_dir)

    def append_records_to_disk(self, records: list[ExportedLogRecord]) -> None:
        buffers: dict[Path, list[str]] = {}
        paths: dict[tuple[str, str, str, str], Path] = {}
        for record in records:
            key = (
                record.username,
                record.network,
                record.target,
                record.timestamp.format_iso()[:10],
            )
            if key not in paths:
                paths[key] = self.get_target_log_path(record)
            buffers.setdefault(paths[key], []).append(self.format_log_line(record))
        entries: list[FileOffset] = []
        orders: dict[Path, LogOrder] = {}
        for path, lines in buffers.items():
            lines.sort(key=line_time)
            order = self._get_log_order(path)
            orders[path] = order
            relative_path = str(path.relative_to(self.output_dir))
            if not order.ordered or (order.latest and line_time(lines[0]) < order.latest):
                temporary = path.parent / (".soju-reorder-" + uuid4().hex)
                relative_temp = str(temporary.relative_to(self.output_dir))
                entries.append(
                    FileOffset(
                        relative_path=relative_path,
                        size=path.stat().st_size,
                        backup_path=relative_temp + ".before",
                        replacement_path=relative_temp + ".after",
                        sort_path=relative_temp + ".sqlite",
                    )
                )
            else:
                entries.append(
                    FileOffset(
                        relative_path=relative_path,
                        size=path.stat().st_size if path.exists() else None,
                    )
                )
        journal = AppendJournal(
            previous_id=self.get_last_synced_id(), latest_id=records[-1].msg_id, files=entries
        )
        atomic_write(self.journal_file, journal.model_dump_json())
        for entry in entries:
            path = self._contained_path(entry.relative_path)
            lines = buffers[path]
            durable_mkdir(path.parent)
            if entry.backup_path is not None:
                assert entry.replacement_path is not None and entry.sort_path is not None
                backup = self._contained_path(entry.backup_path)
                replacement = self._contained_path(entry.replacement_path)
                sort_file = self._contained_path(entry.sort_path)
                os.link(path, backup)
                sync_directory(path.parent)
                rewrite_log(
                    path,
                    replacement,
                    sort_file,
                    lines,
                    compress=self.compress,
                    ordered=orders[path].ordered,
                )
                os.chmod(replacement, stat.S_IMODE(path.stat().st_mode))
                with replacement.open("rb") as stream:
                    os.fsync(stream.fileno())
                os.replace(replacement, path)
            else:
                write_log(path, lines, compress=self.compress, append=True)
            sync_directory(path.parent)
            self._remember_order(path, LogOrder(max(orders[path].latest, line_time(lines[-1]))))

    def _get_log_order(self, path: Path) -> LogOrder:
        if not path.exists():
            return LogOrder()
        info = path.stat()
        cached = self._log_orders.get(path)
        if cached is not None and cached[:2] == (info.st_size, info.st_mtime_ns):
            return cached[2]
        return inspect_log(path, compress=self.compress)

    def _remember_order(self, path: Path, order: LogOrder) -> None:
        # Bound metadata independently of the number of destinations in a history.
        if path not in self._log_orders and len(self._log_orders) >= 128:
            self._log_orders.pop(next(iter(self._log_orders)))
        info = path.stat()
        self._log_orders[path] = (info.st_size, info.st_mtime_ns, order)

    def _run(self, force_all: bool, since_id: int | None) -> int:
        identity = ExportIdentity(
            database=str(self.db_path.resolve()),
            checkpoint=str(self.state_file),
            compress=self.compress,
        )
        identity_path = self.output_dir / ".export-config.json"
        if identity_path.exists():
            saved = ExportIdentity.model_validate_json(identity_path.read_bytes())
            if saved != identity:
                raise ValueError(
                    "Database, checkpoint path or compression changed; use the original options or a fresh output directory"
                )
        self._recover()
        checkpoint = self.get_last_synced_id()
        if checkpoint == 0 and any(self.output_dir.rglob("*.log*")):
            raise ValueError(
                "Existing logs have no usable checkpoint; use a fresh output directory"
            )
        if force_all and checkpoint:
            raise ValueError(
                "--all requires a fresh output directory; existing exports resume automatically"
            )
        if since_id is not None and since_id < checkpoint:
            raise ValueError(
                "--since-id cannot precede the checkpoint; use a fresh output directory"
            )
        start = checkpoint if since_id is None else since_id
        with open_soju_db(self.db_path, readonly=True) as db:
            end = query_rows(db, MaximumID, "SELECT coalesce(max(id), 0) AS id FROM Message")[0].id
        if checkpoint > end:
            raise ValueError(
                "Checkpoint exceeds database history; verify the database and output directory"
            )
        if not identity_path.exists():
            atomic_write(identity_path, identity.model_dump_json())
        while records := self.fetch_new_records(start, end):
            self.append_records_to_disk(records)
            self.set_last_synced_id(records[-1].msg_id)
            self._recover()  # Committed batch: remove its journal without truncating.
            start = records[-1].msg_id
        return 0

    def run(self, force_all: bool = False, since_id: int | None = None) -> int:
        if since_id is not None and since_id < 0:
            raise ValueError("--since-id must not be negative")
        if self.dry_run:
            # Do not create files or recover pending writes during a preview.
            if self.journal_file.exists():
                raise ValueError("Pending interrupted export; run without --dry-run to recover it")
            checkpoint = self.get_last_synced_id()
            if force_all and checkpoint:
                raise ValueError("--all requires a fresh output directory")
            if since_id is not None and since_id < checkpoint:
                raise ValueError("--since-id cannot precede the checkpoint")
            start = since_id if since_id is not None else checkpoint
            with open_soju_db(self.db_path, readonly=True) as db:
                end = query_rows(db, MaximumID, "SELECT coalesce(max(id), 0) AS id FROM Message")[
                    0
                ].id
            count = 0
            while records := self.fetch_new_records(start, end):
                for record in records:
                    self.get_target_log_path(record)
                count += len(records)
                start = records[-1].msg_id
            print(f"Would export {count:,} messages.")
            return 0
        with export_lock(self.output_dir / ".export.lock"):
            return self._run(force_all, since_id)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=Path("/var/lib/soju/main.db"))
    parser.add_argument("--output-dir", type=Path, default=Path("/var/lib/soju/logs"))
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--uncompressed", action="store_true")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--all", action="store_true", dest="force_all")
    parser.add_argument("--since-id", type=int)
    parser.add_argument("--dry-run", action="store_true")
    try:
        args = ExportCLI.model_validate(vars(parser.parse_args(argv)))
        exporter = SojuFSExporter(
            args.db_path,
            args.output_dir,
            args.state_file,
            compress=not args.uncompressed,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
        )
        return exporter.run(args.force_all, args.since_id)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


class ExportCLI(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    db_path: Path
    output_dir: Path
    state_file: Path | None
    uncompressed: bool
    batch_size: int = Field(ge=1, le=100000)
    force_all: bool
    since_id: int | None = Field(ge=0)
    dry_run: bool


if __name__ == "__main__":
    sys.exit(main())
