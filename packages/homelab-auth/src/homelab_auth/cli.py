from collections.abc import Callable
from typing import Annotated

import anyio
import anyio.to_thread
import typer
from pydantic import ValidationError
from rich.console import Console

from homelab_auth.common import build_options, format_path, load_env
from homelab_auth.config import HOMELAB_ENV
from homelab_auth.models import SERVICE_NAMES, BootstrapOptions, HomelabAuth, Service
from homelab_auth.services.arcane import apply_and_verify_arcane, check_arcane
from homelab_auth.services.bookorbit import apply_and_verify_bookorbit, check_bookorbit
from homelab_auth.services.jellyfin import apply_and_verify_jellyfin, check_jellyfin
from homelab_auth.services.qbittorrent import apply_and_verify_qbittorrent, check_qbittorrent
from homelab_auth.services.qui import apply_and_verify_qui, check_qui

console = Console()
console_err = Console(stderr=True)
PREFIX = "[bold cyan]\\[auth/bootstrap][/]"

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
    console.print(f"  [bold yellow]✗[/] [cyan]{name}[/] credentials need update")
    return False


def check_task_definitions(auth: HomelabAuth) -> dict[Service, tuple[str, CheckTask]]:
    return {
        Service.QBITTORRENT: ("qBittorrent", lambda: check_qbittorrent(auth)),
        Service.QUI: ("Qui", lambda: check_qui(auth)),
        Service.ARCANE: ("Arcane", lambda: check_arcane(auth)),
        Service.JELLYFIN: ("Jellyfin", lambda: check_jellyfin(auth)),
        Service.BOOKORBIT: ("BookOrbit", lambda: check_bookorbit(auth)),
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


def task_definitions(auth: HomelabAuth, options: BootstrapOptions) -> dict[Service, tuple[str, BootstrapTask]]:
    return {
        Service.QBITTORRENT: ("qBittorrent", lambda: apply_and_verify_qbittorrent(auth)),
        Service.QUI: ("Qui", lambda: apply_and_verify_qui(auth)),
        Service.ARCANE: ("Arcane", lambda: apply_and_verify_arcane(auth)),
        Service.JELLYFIN: ("Jellyfin", lambda: apply_and_verify_jellyfin(auth, options)),
        Service.BOOKORBIT: ("BookOrbit", lambda: apply_and_verify_bookorbit(auth)),
    }


async def main_async(options: BootstrapOptions) -> int:
    if not HOMELAB_ENV.exists():
        console_err.print(f"{PREFIX} [bold red]missing auth env:[/] {HOMELAB_ENV}")
        return 1

    try:
        auth = HomelabAuth.model_validate(load_env(HOMELAB_ENV))
    except ValidationError as error:
        console_err.print(f"{PREFIX} [bold red]Auth validation error:[/] {error}")
        return 1

    is_dry_run = not options.apply
    mode_label = "[bold yellow](DRY RUN)[/]" if is_dry_run else "[bold green](APPLY)[/]"
    services_list = ", ".join(f"[bold green]{s.value}[/]" for s in options.services)
    console.print(f"{PREFIX} {mode_label} Target Services: {services_list}")
    console.print(f"{PREFIX} .env Path: [magenta]{format_path(HOMELAB_ENV)}[/]\n")

    if is_dry_run:
        check_tasks = [check_task_definitions(auth)[service] for service in options.services]
        results: list[tuple[int, str, bool, str | None]] = []

        def _run_check(idx: int, name: str, task: CheckTask) -> tuple[int, str, bool, str | None]:
            try:
                matched = task()
                return (idx, name, matched, None)
            except Exception as e:
                return (idx, name, False, str(e))

        async def _worker(idx: int, name: str, task: CheckTask) -> None:
            res = await anyio.to_thread.run_sync(_run_check, idx, name, task)
            results.append(res)

        async with anyio.create_task_group() as tg:
            for idx, (name, task) in enumerate(check_tasks):
                tg.start_soon(_worker, idx, name, task)

        results.sort(key=lambda x: x[0])
        all_matched = True
        for _, name, matched, err in results:
            if err:
                console_err.print(f"  [bold red]✗[/] [cyan]{name}[/] error checking credentials: {err}")
                all_matched = False
            elif matched:
                console.print(f"  [bold green]✓[/] [cyan]{name}[/] credentials already match")
            else:
                console.print(f"  [bold yellow]✗[/] [cyan]{name}[/] credentials need update")
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


if __name__ == "__main__":
    typer_main()
