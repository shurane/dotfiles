import os
import sqlite3
import time
from pathlib import Path

import httpx
import typer

from .config import ROOT
from .models import SERVICE_NAMES, BootstrapOptions, ServiceName


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def ensure_state_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        root_stat = ROOT.stat()
        os.chown(path, root_stat.st_uid, root_stat.st_gid)


def wait_for_http(client: httpx.Client, url: str, ready_statuses: set[int], timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            response = client.get(url)
            last_error = f"HTTP {response.status_code}"
            if response.status_code in ready_statuses:
                return
        except httpx.HTTPError as error:
            last_error = str(error)
        time.sleep(2)
    raise RuntimeError(f"timed out waiting for {url}; last result: {last_error}")


def wait_for_sqlite_table(db_path: Path, table_name: str, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if db_path.exists():
            try:
                with sqlite3.connect(db_path) as db:
                    row = db.execute(
                        "select name from sqlite_master where type = 'table' and name = ?",
                        (table_name,),
                    ).fetchone()
                if row is not None:
                    return
            except sqlite3.Error:
                pass
        time.sleep(2)
    raise RuntimeError(f"timed out waiting for table {table_name!r} in {db_path}")


def build_options(skip_backup: bool, parallel: bool, services_value: str) -> BootstrapOptions:
    service_values = tuple(service.strip().lower() for service in services_value.split(",") if service.strip())
    unknown_services = sorted(set(service_values) - set(SERVICE_NAMES))
    if unknown_services:
        raise typer.BadParameter(f"unknown services: {', '.join(unknown_services)}", param_hint="--services")
    if not service_values:
        raise typer.BadParameter("must include at least one service", param_hint="--services")
    return BootstrapOptions(
        parallel=parallel,
        skip_backup=skip_backup,
        services=tuple(ServiceName(service) for service in service_values),
    )
