import sys
from collections.abc import Callable
from typing import Annotated

import anyio
import typer
from pydantic import ValidationError

from .common import build_options, load_env
from .config import AUTH_ENV
from .models import SERVICE_NAMES, BootstrapOptions, HomelabAuth, ServiceName
from .services.arcane import apply_and_verify_arcane
from .services.jellyfin import apply_and_verify_jellyfin
from .services.qbittorrent import apply_and_verify_qbittorrent
from .services.qui import apply_and_verify_qui

type BootstrapTask = Callable[[], None]


async def run_service(name: str, task: BootstrapTask) -> None:
    try:
        await anyio.to_thread.run_sync(task)
    except Exception:
        print(f"{name} bootstrap failed", file=sys.stderr)
        raise
    print(f"{name} credentials verified")


def run_service_sync(name: str, task: BootstrapTask) -> None:
    try:
        task()
    except Exception:
        print(f"{name} bootstrap failed", file=sys.stderr)
        raise
    print(f"{name} credentials verified")


def task_definitions(auth: HomelabAuth, options: BootstrapOptions) -> dict[ServiceName, tuple[str, BootstrapTask]]:
    return {
        ServiceName.QBITTORRENT: ("qBittorrent", lambda: apply_and_verify_qbittorrent(auth)),
        ServiceName.QUI: ("Qui", lambda: apply_and_verify_qui(auth)),
        ServiceName.ARCANE: ("Arcane", lambda: apply_and_verify_arcane(auth)),
        ServiceName.JELLYFIN: ("Jellyfin", lambda: apply_and_verify_jellyfin(auth, options)),
    }


async def main_async(options: BootstrapOptions) -> int:
    if not AUTH_ENV.exists():
        print(f"missing auth env: {AUTH_ENV}", file=sys.stderr)
        return 1

    try:
        auth = HomelabAuth.model_validate(load_env(AUTH_ENV))
    except ValidationError as error:
        print(error, file=sys.stderr)
        return 1

    selected_tasks = [task_definitions(auth, options)[service] for service in options.services]
    if options.parallel:
        async with anyio.create_task_group() as task_group:
            for name, task in selected_tasks:
                task_group.start_soon(run_service, name, task)
    else:
        for name, task in selected_tasks:
            run_service_sync(name, task)

    print("Homelab credentials applied")
    return 0


def main(
    skip_backup: Annotated[
        bool,
        typer.Option("--skip-backup", help="Do not back up SQLite files before changing auth state."),
    ] = False,
    parallel: Annotated[
        bool,
        typer.Option("--parallel", help="Bootstrap selected services concurrently. Defaults to serial execution."),
    ] = False,
    services: Annotated[
        str,
        typer.Option(
            "--services",
            help=f"Comma-separated services to bootstrap. Choices: {', '.join(SERVICE_NAMES)}.",
        ),
    ] = ",".join(SERVICE_NAMES),
) -> None:
    options = build_options(skip_backup=skip_backup, parallel=parallel, services_value=services)
    raise typer.Exit(anyio.run(main_async, options, backend="trio"))


def typer_main() -> None:
    typer.run(main)
