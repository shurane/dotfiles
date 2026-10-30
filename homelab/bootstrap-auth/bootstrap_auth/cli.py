from collections.abc import Callable
from typing import Annotated

import anyio
import typer
from pydantic import ValidationError
from rich.console import Console

from .common import build_options, format_path, load_env
from .config import AUTH_ENV
from .models import SERVICE_NAMES, BootstrapOptions, HomelabAuth, ServiceName
from .services.arcane import apply_and_verify_arcane, check_arcane
from .services.jellyfin import apply_and_verify_jellyfin, check_jellyfin
from .services.qbittorrent import apply_and_verify_qbittorrent, check_qbittorrent
from .services.qui import apply_and_verify_qui, check_qui

console = Console()
console_err = Console(stderr=True)
PREFIX = "[bold cyan]\\[bootstrap-auth][/]"

type BootstrapTask = Callable[[], None]
type CheckTask = Callable[[], bool]


def dry_run_service(name: str, task: CheckTask) -> bool:
    try:
        matches = task()
    except Exception as e:
        console_err.print(f"  [bold red]✗[/] [cyan]{name}[/] error checking credentials: {e}")
        return False
    if matches:
        console.print(f"  [bold green]✓[/] [cyan]{name}[/] credentials already match")
        return True
    else:
        console.print(f"  [bold yellow]✗[/] [cyan]{name}[/] credentials need update")
        return False


def check_task_definitions(auth: HomelabAuth) -> dict[ServiceName, tuple[str, CheckTask]]:
    return {
        ServiceName.QBITTORRENT: ("qBittorrent", lambda: check_qbittorrent(auth)),
        ServiceName.QUI: ("Qui", lambda: check_qui(auth)),
        ServiceName.ARCANE: ("Arcane", lambda: check_arcane(auth)),
        ServiceName.JELLYFIN: ("Jellyfin", lambda: check_jellyfin(auth)),
    }


async def run_service(name: str, task: BootstrapTask) -> None:
    try:
        await anyio.to_thread.run_sync(task)
    except Exception:
        console_err.print(f"  [bold red]✗[/] [cyan]{name}[/] bootstrap failed")
        raise
    console.print(f"  [bold green]✓[/] [cyan]{name}[/] credentials applied and verified")


def run_service_sync(name: str, task: BootstrapTask) -> None:
    try:
        task()
    except Exception:
        console_err.print(f"  [bold red]✗[/] [cyan]{name}[/] bootstrap failed")
        raise
    console.print(f"  [bold green]✓[/] [cyan]{name}[/] credentials applied and verified")


def task_definitions(auth: HomelabAuth, options: BootstrapOptions) -> dict[ServiceName, tuple[str, BootstrapTask]]:
    return {
        ServiceName.QBITTORRENT: ("qBittorrent", lambda: apply_and_verify_qbittorrent(auth)),
        ServiceName.QUI: ("Qui", lambda: apply_and_verify_qui(auth)),
        ServiceName.ARCANE: ("Arcane", lambda: apply_and_verify_arcane(auth)),
        ServiceName.JELLYFIN: ("Jellyfin", lambda: apply_and_verify_jellyfin(auth, options)),
    }


async def main_async(options: BootstrapOptions) -> int:
    if not AUTH_ENV.exists():
        console_err.print(f"{PREFIX} [bold red]missing auth env:[/] {AUTH_ENV}")
        return 1

    try:
        auth = HomelabAuth.model_validate(load_env(AUTH_ENV))
    except ValidationError as error:
        console_err.print(f"{PREFIX} [bold red]Auth validation error:[/] {error}")
        return 1

    is_dry_run = not options.apply
    mode_label = "[bold yellow](DRY RUN)[/]" if is_dry_run else "[bold green](APPLY)[/]"
    services_list = ", ".join(f"[bold green]{s.value}[/]" for s in options.services)
    console.print(f"{PREFIX} {mode_label} Target Services: {services_list}")
    console.print(f"{PREFIX} .env Path: [magenta]{format_path(AUTH_ENV)}[/]\n")

    if is_dry_run:
        check_tasks = [check_task_definitions(auth)[service] for service in options.services]
        all_matched = True
        for name, task in check_tasks:
            matched = dry_run_service(name, task)
            if not matched:
                all_matched = False
        if all_matched:
            console.print(
                "\n[bold green]All selected services already have matching credentials. No changes needed.[/]"
            )
        else:
            console.print(
                "\n[bold yellow]Dry-run complete. Re-run with [bold green]--apply[/bold green] to commit changes.[/]"
            )
        return 0

    selected_tasks = [task_definitions(auth, options)[service] for service in options.services]
    if options.parallel:
        async with anyio.create_task_group() as task_group:
            for name, task in selected_tasks:
                task_group.start_soon(run_service, name, task)
    else:
        for name, task in selected_tasks:
            run_service_sync(name, task)

    console.print("\n[bold green]Homelab credentials applied successfully.[/]")
    return 0


def main(
    apply: Annotated[
        bool,
        typer.Option("--apply", "-a", help="Apply credentials and bootstrap services (default: dry-run preview)."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Verify current credential state without modifying anything (default)."),
    ] = False,
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
    is_apply = apply and not dry_run
    options = build_options(skip_backup=skip_backup, parallel=parallel, services_value=services, apply=is_apply)
    raise typer.Exit(anyio.run(main_async, options, backend="trio"))


def typer_main() -> None:
    typer.run(main)
