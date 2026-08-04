#!/usr/bin/env python3
import os
import secrets
import sys
from datetime import date, timedelta
from pathlib import Path


CRONJOB = Path("/home/withings-sync/cronjob")
ENTRYPOINT = "/home/withings-sync/entrypoint.py"
SUPERCRONIC = "/usr/bin/supercronic"
WITHINGS_SYNC = "/home/withings-sync/.venv/bin/withings-sync"


def run_sync() -> None:
    fromdate = (date.today() - timedelta(days=2)).isoformat()
    os.execv(
        WITHINGS_SYNC,
        [
            "withings-sync",
            "--config-folder",
            "/config",
            "--fromdate",
            fromdate,
        ],
    )


def run_cron() -> None:
    offset = secrets.randbelow(120)
    minute = offset % 60
    hour = 12 + (offset // 60)
    CRONJOB.write_text(f"{minute} {hour} * * * {ENTRYPOINT} sync\n")
    os.execv(SUPERCRONIC, ["supercronic", "-passthrough-logs", str(CRONJOB)])


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "sync":
        run_sync()
    run_cron()


if __name__ == "__main__":
    main()
