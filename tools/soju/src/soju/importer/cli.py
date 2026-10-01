"""Bulk import WeeChat log files into Soju IRC bouncer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from soju.db import open_soju_db
from soju.importer.parser import parse_weechat_log_file
from soju.models import MessageKind, SojuTargetFile, WeeChatLogRecord
from soju.resolver import SojuTargetResolver

console = Console()


class SojuLogImporter:
    """Manages parsing and importing historical WeeChat logs into Soju."""

    def __init__(
        self,
        logs_dir: Path,
        mode: str = "db",
        db_path: Path | None = None,
        fs_dir: Path | None = None,
        username: str = "shurane",
        batch_size: int = 5000,
        dry_run: bool = False,
    ) -> None:
        self.logs_dir = logs_dir
        self.mode = mode
        self.db_path = db_path or Path("/var/lib/soju/main.db")
        self.fs_dir = fs_dir or Path("/var/lib/soju/logs")
        self.username = username
        self.batch_size = batch_size
        self.dry_run = dry_run

    def discover_targets(self) -> list[SojuTargetFile]:
        """Scan logs_dir for WeeChat log files."""
        if not self.logs_dir.exists():
            console.print(f"[bold red]Error: logs directory {self.logs_dir} not found![/bold red]")
            return []

        targets: list[SojuTargetFile] = []
        for path in sorted(self.logs_dir.glob("irc.*.weechatlog*")):
            target = SojuTargetFile.from_path(path)
            if target:
                targets.append(target)
        return targets

    def import_to_db(self, targets: list[SojuTargetFile]) -> None:
        if not self.db_path.exists() and not self.dry_run:
            console.print(f"[bold red]Error: Database not found at {self.db_path}![/bold red]")
            sys.exit(1)

        total_imported = 0
        total_skipped = 0

        with open_soju_db(self.db_path, readonly=self.dry_run) as db:
            resolver = SojuTargetResolver(db)
            user_id = resolver.get_or_create_user(self.username) if not self.dry_run else 1

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                file_task = progress.add_task("[cyan]Importing files...", total=len(targets))

                for target_info in targets:
                    progress.update(
                        file_task,
                        description=f"[cyan]Processing {target_info.network}/{target_info.target}",
                    )

                    net_id = (
                        resolver.get_or_create_network(user_id, target_info.network)
                        if not self.dry_run
                        else 1
                    )
                    target_id = (
                        resolver.get_or_create_target(net_id, target_info.target)
                        if not self.dry_run
                        else 1
                    )

                    batch: list[dict[str, object]] = []
                    last_timestamp: str | None = None

                    for rec in parse_weechat_log_file(target_info.source_path):
                        iso_ts = rec.parsed_datetime.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                        last_timestamp = iso_ts

                        # Build raw IRC string
                        raw_irc = self._build_raw_irc(rec, iso_ts, target_info.target)

                        batch.append(
                            {
                                "target": target_id,
                                "raw": raw_irc,
                                "time": iso_ts,
                                "sender": rec.sender_nick,
                                "text": rec.clean_text,
                            }
                        )

                        if len(batch) >= self.batch_size:
                            if not self.dry_run:
                                db.table("Message").insert_all(batch)
                            total_imported += len(batch)
                            batch.clear()

                    if batch:
                        if not self.dry_run:
                            db.table("Message").insert_all(batch)
                        total_imported += len(batch)
                        batch.clear()

                    # Update ReadReceipt to latest message time
                    if (
                        last_timestamp
                        and not self.dry_run
                        and net_id != -1
                        and "ReadReceipt" in db.table_names()
                    ):
                        db.execute(
                            """
                                INSERT INTO ReadReceipt (network, target, timestamp)
                                VALUES (?, ?, ?)
                                ON CONFLICT(network, target) DO UPDATE SET timestamp = excluded.timestamp
                                """,
                            [net_id, target_info.target, last_timestamp],
                        )

                    progress.advance(file_task)

        console.print(
            f"[bold green]Import complete![/bold green] Processed {total_imported:,} messages "
            f"({total_skipped:,} lines skipped)."
        )

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

    def run(self) -> None:
        targets = self.discover_targets()
        if not targets:
            console.print("[yellow]No WeeChat log files found to import.[/yellow]")
            return

        console.print(
            f"Found [bold cyan]{len(targets)}[/bold cyan] log files in [bold]{self.logs_dir}[/bold]"
        )
        if self.mode == "db":
            self.import_to_db(targets)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="weechat-to-soju",
        description="Convert and import WeeChat log files into Soju IRC bouncer.",
    )
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=Path.home() / ".local/share/weechat/logs",
        help="Path to WeeChat logs directory",
    )
    parser.add_argument(
        "--mode",
        choices=["db", "fs"],
        default="db",
        help="Storage mode: 'db' (SQLite) or 'fs' (filesystem flat logs)",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("/var/lib/soju/main.db"),
        help="Path to Soju SQLite database",
    )
    parser.add_argument(
        "--fs-dir",
        type=Path,
        default=Path("/var/lib/soju/logs"),
        help="Root path for filesystem logs",
    )
    parser.add_argument(
        "--username",
        default="shurane",
        help="Soju username to associate the logs with",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Batch size for SQLite transactions",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate without writing to database or disk",
    )

    args = parser.parse_args()
    importer = SojuLogImporter(
        logs_dir=args.logs_dir,
        mode=args.mode,
        db_path=args.db_path,
        fs_dir=args.fs_dir,
        username=args.username,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )
    importer.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
