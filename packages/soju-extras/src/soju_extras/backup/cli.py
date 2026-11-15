"""Create, verify, restore and prune compressed Soju backup directories."""

import argparse
import sqlite3
import subprocess
from compression import zstd
from pathlib import Path
from typing import Literal

from soju_extras.backup.models import BackupConfig, Retention
from soju_extras.backup.retention import prune
from soju_extras.backup.runner import create_backup
from soju_extras.backup.snapshot import restore_snapshot, verify_snapshot


class Arguments(argparse.Namespace):
    action: Literal["run", "verify", "restore", "prune"]
    path: Path
    destination: Path
    apply: bool = False
    daily: int = 7
    weekly: int = 4
    monthly: int = 6
    timezone: str = "America/Chicago"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for action, description in (
        ("run", "Create and transfer a snapshot using a JSON configuration"),
        ("verify", "Verify stored and decoded checksums"),
        ("restore", "Restore original paths into a new, absent directory"),
        ("prune", "Preview retention; delete only with --apply"),
    ):
        command = commands.add_parser(action, help=description)
        command.add_argument("path", type=Path)
        if action == "restore":
            command.add_argument("destination", type=Path)
        if action == "prune":
            command.add_argument("--apply", action="store_true")
            for period, count in (("daily", 7), ("weekly", 4), ("monthly", 6)):
                command.add_argument("--" + period, type=int, default=count)
            command.add_argument("--timezone", default="America/Chicago")
    args = parser.parse_args(namespace=Arguments())
    try:
        match args.action:
            case "run":
                config = BackupConfig.model_validate_json(args.path.read_bytes())
                print(f"Verified backup: {create_backup(config)}")
            case "verify":
                manifest = verify_snapshot(args.path)
                print(f"Verified {manifest.snapshot}: {len(manifest.entries)} entries")
            case "restore":
                restore_snapshot(args.path, args.destination)
                print(f"Restored to {args.destination}")
            case "prune":
                policy = Retention(
                    daily=args.daily,
                    weekly=args.weekly,
                    monthly=args.monthly,
                    timezone=args.timezone,
                )
                for name in prune(args.path, policy, apply=args.apply):
                    print(("Deleted " if args.apply else "Would delete ") + name)
    except (
        EOFError,
        OSError,
        ValueError,
        sqlite3.Error,
        subprocess.CalledProcessError,
        zstd.ZstdError,
    ) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
