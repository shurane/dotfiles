"""Bounded-memory, repeatable WeeChat imports into an existing Soju database."""

import argparse
import sqlite3
import sys
from collections.abc import Iterator, Sequence
from compression import zstd
from itertools import batched
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from rich.console import Console
from rich.progress import track

from soju_extras.db import execute, execute_many, open_soju_db, query_rows, transaction
from soju_extras.importer.parser import parse_weechat_log_file
from soju_extras.importer.read_markers import ReadMarkers, import_read_markers
from soju_extras.models import MessageKind, SojuTargetFile, WeeChatLogRecord
from soju_extras.resolver import SojuTargetResolver
from soju_extras.time import parse_timestamp, soju_timestamp

console = Console(stderr=True)


class ImportOptions(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    logs_dir: Path
    db_path: Path = Path("/var/lib/soju/main.db")
    username: str = "shurane"
    batch_size: int = Field(default=5000, ge=1, le=100000)
    dry_run: bool = False
    timezone: str = "UTC"
    mode: Literal["db"] = "db"
    network_map: dict[str, str] = Field(default_factory=dict)
    before: str | None = None
    since: str | None = None
    allow_overlap: bool = False
    read_markers: Path | None = None


class CountRow(BaseModel):
    model_config = ConfigDict(strict=True)
    count: int


def raise_walk_error(error: OSError) -> None:
    raise error


class SojuLogImporter:
    def __init__(
        self,
        logs_dir: Path,
        mode: Literal["db"] = "db",
        db_path: Path | None = None,
        username: str = "shurane",
        batch_size: int = 5000,
        dry_run: bool = False,
        timezone: str = "UTC",
        network_map: dict[str, str] | None = None,
        before: str | None = None,
        allow_overlap: bool = False,
        read_markers: Path | None = None,
        since: str | None = None,
    ) -> None:
        self.options = ImportOptions(
            logs_dir=logs_dir,
            mode=mode,
            db_path=db_path or Path("/var/lib/soju/main.db"),
            username=username,
            batch_size=batch_size,
            dry_run=dry_run,
            timezone=timezone,
            network_map=network_map or {},
            before=before,
            since=since,
            allow_overlap=allow_overlap,
            read_markers=read_markers,
        )
        self.before = parse_timestamp(before) if before is not None else None
        self.since = parse_timestamp(since) if since is not None else None
        if self.before is not None and self.since is not None and self.since >= self.before:
            raise ValueError("--since must be earlier than --before")

    def discover_targets(self) -> list[SojuTargetFile]:
        if not self.options.logs_dir.is_dir():
            raise ValueError(f"Logs directory does not exist: {self.options.logs_dir}")
        targets: list[SojuTargetFile] = []
        unsupported: list[Path] = []
        for directory, _, filenames in self.options.logs_dir.walk(on_error=raise_walk_error):
            for filename in filenames:
                if ".weechatlog" not in filename:
                    continue
                path = directory / filename
                if filename.startswith(("irc.server.", "core.weechat.weechatlog")):
                    console.print(f"{path}: excluded non-conversation log", markup=False)
                    continue
                target = SojuTargetFile.from_path(path)
                if target is None or path.is_symlink():
                    unsupported.append(path)
                else:
                    targets.append(target)
        if unsupported:
            names = "\n".join(str(path) for path in sorted(unsupported))
            raise ValueError(f"Unsupported log names or symlinks; no files imported:\n{names}")
        if not targets:
            raise ValueError(f"No supported WeeChat logs found in {self.options.logs_dir}")
        return sorted(targets, key=lambda target: target.source_path)

    def _input_rows(
        self, records: Iterator[WeeChatLogRecord], target: SojuTargetFile
    ) -> Iterator[tuple[int, str, str, str, str | None]]:
        included = excluded = 0
        for rec in records:
            if (self.before is not None and rec.parsed_datetime >= self.before) or (
                self.since is not None and rec.parsed_datetime < self.since
            ):
                excluded += 1
                continue
            timestamp = soju_timestamp(rec.parsed_datetime)
            yield (
                included,
                timestamp,
                self._build_raw_irc(rec, timestamp, target.target),
                rec.sender_nick,
                rec.clean_text
                if rec.kind in (MessageKind.PRIVMSG, MessageKind.NOTICE, MessageKind.ACTION)
                else None,
            )
            included += 1
        console.print(
            f"{target.source_path}: {included:,} eligible, {excluded:,} excluded by cutoff",
            markup=False,
        )

    def import_to_db(self, targets: list[SojuTargetFile]) -> int:
        opts = self.options
        imported = 0
        if opts.dry_run:
            for target in targets:
                with parse_weechat_log_file(target.source_path, timezone=opts.timezone) as records:
                    imported += sum(1 for _ in self._input_rows(records, target))
            return imported

        with open_soju_db(opts.db_path) as db:
            execute(
                db,
                "CREATE TEMP TABLE incoming (seq INTEGER PRIMARY KEY, time TEXT, raw TEXT, sender TEXT, text TEXT)",
            )
            execute(db, "CREATE INDEX incoming_key ON incoming(time, raw)")
            execute(
                db,
                "CREATE TEMP TABLE existing (time TEXT, raw TEXT, count INTEGER, PRIMARY KEY(time, raw)) WITHOUT ROWID",
            )
            resolver = SojuTargetResolver(db)
            user_id = resolver.resolve_user(opts.username)
            for target in track(
                targets, description="Importing", console=console, disable=not console.is_terminal
            ):
                network_id = resolver.resolve_network(
                    user_id, opts.network_map.get(target.network, target.network)
                )
                # Parse to disk-backed SQLite temporary storage before taking the main writer lock.
                with transaction(db, immediate=False):
                    execute(db, "DELETE FROM incoming")
                    execute(db, "DELETE FROM existing")
                    with parse_weechat_log_file(
                        target.source_path, timezone=opts.timezone
                    ) as records:
                        rows = self._input_rows(records, target)
                        for batch in batched(rows, opts.batch_size, strict=False):
                            execute_many(db, "INSERT INTO incoming VALUES (?, ?, ?, ?, ?)", batch)
                with transaction(db):
                    target_id = resolver.get_or_create_target(network_id, target.target)
                    has_history = query_rows(
                        db,
                        CountRow,
                        "SELECT EXISTS(SELECT 1 FROM Message WHERE target = ?) AS count",
                        (target_id,),
                    )[0].count
                    if has_history:
                        if not opts.allow_overlap:
                            overlap = query_rows(
                                db,
                                CountRow,
                                """
                                SELECT EXISTS(
                                    SELECT 1 FROM incoming i CROSS JOIN Message m
                                    ON m.target = ?
                                    AND m.time >= substr(i.time, 1, 19) || '.000Z'
                                    AND m.time <= substr(i.time, 1, 19) || '.999Z'
                                    WHERE m.sender = i.sender AND m.text = i.text
                                    AND m.raw != i.raw
                                ) AS count
                                """,
                                (target_id,),
                            )[0].count
                            if overlap:
                                raise ValueError(
                                    f"{target.source_path}: possible overlap with stored history "
                                    "(same sender/text/second, different raw IRC). This file was "
                                    "not imported. Use --before with a verified cutover timestamp, "
                                    "or --allow-overlap after reviewing possible duplicates."
                                )
                        # Preserve multiplicity: two identical source lines remain two messages;
                        # rereading that file inserts neither again. Snapshot counts before insertion.
                        execute(
                            db,
                            """
                            INSERT INTO existing
                            SELECT s.time, s.raw, count(m.id)
                            FROM (SELECT DISTINCT time, raw FROM incoming) s
                            LEFT JOIN Message m ON m.target = ? AND m.time = s.time AND m.raw = s.raw
                            GROUP BY s.time, s.raw
                        """,
                            (target_id,),
                        )
                        execute(
                            db,
                            """
                            INSERT INTO Message (target, time, raw, sender, text)
                            SELECT ?, i.time, i.raw, i.sender, i.text
                            FROM (SELECT *, row_number() OVER (PARTITION BY time, raw ORDER BY seq) AS occurrence FROM incoming) i
                            JOIN existing e ON e.time = i.time AND e.raw = i.raw
                            WHERE i.occurrence > e.count ORDER BY i.seq
                        """,
                            (target_id,),
                        )
                    else:
                        # Nothing can be a reimport when this target has no stored messages.
                        # The writer transaction keeps the check and insert atomic. Every
                        # source occurrence is retained, including identical repeated lines.
                        execute(
                            db,
                            """
                            INSERT INTO Message(target, time, raw, sender, text)
                            SELECT ?, time, raw, sender, text FROM incoming ORDER BY seq
                        """,
                            (target_id,),
                        )
                    inserted = query_rows(db, CountRow, "SELECT changes() AS count")[0].count
                imported += inserted
                console.print(
                    f"{target.source_path}: committed {inserted:,} messages", markup=False
                )
        return imported

    def _build_raw_irc(self, rec: WeeChatLogRecord, iso_ts: str, target: str) -> str:
        if rec.kind == MessageKind.PRIVMSG:
            return f"@time={iso_ts} :{rec.sender_hostmask} PRIVMSG {target} :{rec.clean_text}"
        elif rec.kind == MessageKind.ACTION:
            return (
                f"@time={iso_ts} :{rec.sender_hostmask} PRIVMSG {target} "
                f":\x01ACTION {rec.clean_text}\x01"
            )
        elif rec.kind == MessageKind.JOIN:
            return f"@time={iso_ts} :{rec.sender_hostmask} JOIN {target}"
        elif rec.kind == MessageKind.PART:
            return f"@time={iso_ts} :{rec.sender_hostmask} PART {target} :{rec.clean_text}"
        elif rec.kind == MessageKind.QUIT:
            return f"@time={iso_ts} :{rec.sender_hostmask} QUIT :{rec.clean_text}"
        elif rec.kind == MessageKind.NOTICE:
            return f"@time={iso_ts} :{rec.sender_hostmask} NOTICE {target} :{rec.clean_text}"
        return f"@time={iso_ts} :* NOTICE {target} :{rec.clean_text}"

    def run(self) -> int:
        opts = self.options
        markers = (
            ReadMarkers.model_validate_json(opts.read_markers.read_bytes())
            if opts.read_markers is not None
            else None
        )
        targets = self.discover_targets()
        count = self.import_to_db(targets)
        if markers is not None and not opts.dry_run:
            import_read_markers(markers, opts.db_path, opts.username, opts.network_map)
        verb = "Validated" if self.options.dry_run else "Imported"
        console.print(f"{verb} {count:,} messages from {len(targets)} files.", markup=False)
        return count


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs-dir", type=Path, default=Path.home() / ".local/share/weechat/logs")
    parser.add_argument("--db-path", type=Path, default=Path("/var/lib/soju/main.db"))
    parser.add_argument("--username", default="shurane")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument(
        "--timezone", default="UTC", help="Timezone for timestamps without an offset (default: UTC)"
    )
    parser.add_argument("--mode", choices=["db"], default="db")
    parser.add_argument(
        "--network-map", action="append", default=[], metavar="LOG_NAME=SOJU_NAME_OR_ADDRESS"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--read-markers",
        type=Path,
        help="Explicit versioned JSON read markers; applied after all log files succeed",
    )
    parser.add_argument(
        "--since", help="Import timestamps at or after this ISO timestamp (UTC if naive)"
    )
    parser.add_argument(
        "--before", help="Import only timestamps before this ISO timestamp (UTC if naive)"
    )
    parser.add_argument(
        "--allow-overlap",
        action="store_true",
        help="Allow ambiguous matches with existing history; may insert duplicates",
    )
    values: dict[str, object] = vars(parser.parse_args(argv))
    try:
        mappings = values.pop("network_map")
        # Validate dynamic argparse data before using it.
        entries = TypeAdapter(list[str]).validate_python(mappings, strict=True)
        mapping: dict[str, str] = {}
        for entry in entries:
            key, separator, value = entry.partition("=")
            if not separator or not key or not value:
                raise ValueError("--network-map requires LOG_NAME=SOJU_NAME_OR_ADDRESS")
            mapping[key.lower()] = value
        opts = ImportOptions.model_validate({**values, "network_map": mapping})
        importer = SojuLogImporter(
            logs_dir=opts.logs_dir,
            db_path=opts.db_path,
            username=opts.username,
            batch_size=opts.batch_size,
            dry_run=opts.dry_run,
            timezone=opts.timezone,
            network_map=opts.network_map,
            before=opts.before,
            since=opts.since,
            allow_overlap=opts.allow_overlap,
            read_markers=opts.read_markers,
        )
        importer.run()
    except (OSError, EOFError, zstd.ZstdError, sqlite3.Error, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
