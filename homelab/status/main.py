#!/usr/bin/env python3
"""Homelab Deep Health & Content Inspector - CLI Entrypoint."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# If executed directly with system Python outside uv, re-exec via uv run --project
if "VIRTUAL_ENV" not in os.environ:
    project_dir = Path(__file__).resolve().parent
    uv_path = shutil.which("uv")
    if not uv_path:
        local_uv = Path.home() / ".local" / "bin" / "uv"
        if local_uv.is_file():
            uv_path = str(local_uv)
    if uv_path and os.path.isfile(uv_path):
        os.execv(uv_path, [uv_path, "run", "--project", str(project_dir), str(__file__), *sys.argv[1:]])

import contextlib
import datetime
import json
import logging
import time
from collections import deque
from dataclasses import asdict
from typing import Any

import anyio
import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from config import format_size, get_docker_client, load_env, render_sparkbar, resolve_target_connection
from models import HealthStatus, ServiceResult, StatusContext
from services import CHECK_REGISTRY, CheckFn

# Silence noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("docker").setLevel(logging.WARNING)

app = typer.Typer(
    help="Homelab Deep Health & Content Inspector",
    add_completion=False,
)
console = Console()


async def _run_all_checks(
    ctx: StatusContext,
    checks: dict[str, CheckFn],
    show_progress: bool = True,
) -> list[ServiceResult]:
    """Execute all selected checks concurrently using an AnyIO task group."""
    check_items = list(checks.items())
    total_count = len(check_items)
    results: list[ServiceResult | None] = [None] * total_count
    completed_count = 0
    recent: deque[str] = deque(maxlen=3)
    t0 = time.perf_counter()

    def _render_ticker() -> Table:
        tbl = Table.grid(padding=(0, 1))
        elapsed = time.perf_counter() - t0
        spinner = Spinner("dots", style="magenta")
        hdr = Text.assemble(
            (" Checking services... ", "bold magenta"),
            (f"{completed_count}/{total_count}", "bold green"),
            (" completed ", "dim"),
            (f"({elapsed:.1f}s)", "dim"),
        )
        tbl.add_row(spinner, hdr)
        for item in recent:
            tbl.add_row("", Text.from_markup(f"  {item}"))
        return tbl

    async def _execute(idx: int, service_id: str, fn: CheckFn, live: Live | None) -> None:
        nonlocal completed_count
        try:
            res = await fn(ctx)
            results[idx] = res
        except Exception as exc:
            res = ServiceResult(
                service_id=service_id,
                name=service_id.capitalize(),
                container=f"homelab-{service_id}-1",
                status=HealthStatus.UNHEALTHY,
                latency_ms=0.0,
                summary=f"Unexpected check failure: {exc}",
                branches=[f"[bold red]✖ Unexpected check failure: {exc}[/bold red]"],
                error=str(exc),
            )
            results[idx] = res

        completed_count += 1
        if live is not None:
            if res.status == HealthStatus.HEALTHY:
                icon_prefix = ""
            elif res.status == HealthStatus.DEGRADED:
                icon_prefix = "🟡 "
            else:
                icon_prefix = "🔴 "

            if res.latency_ms < 100:
                lat_color = "green"
            elif res.latency_ms < 500:
                lat_color = "yellow"
            else:
                lat_color = "red"

            ver = f" [dim cyan]({res.version})[/dim cyan]" if res.version else ""
            line = (
                f"{icon_prefix}[bold white]{res.name}[/bold white]{ver} "
                f"[dim]•[/dim] [{lat_color}]{res.latency_ms:.0f}ms[/{lat_color}]"
            )
            recent.append(line)
            live.update(_render_ticker())

    async def _fetch_disk() -> None:
        with contextlib.suppress(Exception):
            await ctx.get_disk_usage()

    if show_progress:
        with Live(_render_ticker(), console=console, refresh_per_second=10, transient=True) as live:
            with contextlib.suppress(Exception):
                await ctx.get_all_containers()
            async with anyio.create_task_group() as tg:
                tg.start_soon(_fetch_disk)
                for idx, (service_id, fn) in enumerate(check_items):
                    tg.start_soon(_execute, idx, service_id, fn, live)
    else:
        with contextlib.suppress(Exception):
            await ctx.get_all_containers()
        async with anyio.create_task_group() as tg:
            tg.start_soon(_fetch_disk)
            for idx, (service_id, fn) in enumerate(check_items):
                tg.start_soon(_execute, idx, service_id, fn, None)

    return [r for r in results if r is not None]


def render_tree(
    results: list[ServiceResult],
    total_elapsed: float,
    disks: list[dict[str, Any]] | None = None,
) -> None:
    """Render check results as a hierarchical, deep-inspection Rich Tree."""
    all_healthy = all(r.is_healthy for r in results)
    passed_count = sum(1 for r in results if r.is_healthy)
    total_count = len(results)

    if all_healthy:
        status_tag = f"[bold green][{passed_count}/{total_count} healthy][/bold green]"
    else:
        status_tag = f"[bold yellow][{passed_count}/{total_count} healthy][/bold yellow]"

    console.print(f"[bold magenta]🔮 Homelab Services[/bold magenta] {status_tag} [dim]({total_elapsed:.2f}s)[/dim]")

    if disks:
        mango = next((d for d in disks if d.get("mount") == "/mnt/mango"), None)
        root_d = next((d for d in disks if d.get("mount") == "/"), None)
        parts = []
        if mango:
            used = format_size(mango["used_bytes"])
            total = format_size(mango["total_bytes"])
            free = format_size(mango["free_bytes"])
            pct = mango["use_percent"]
            spark = render_sparkbar(pct / 100.0, width=10)
            pct_color = "red" if pct >= 90 else ("yellow" if pct >= 70 else "green")
            parts.append(
                f"💾 [bold white]Storage (/mnt/mango):[/bold white] "
                f"[bold cyan]{used}[/bold cyan] / [bold cyan]{total}[/bold cyan] "
                f"{spark} [{pct_color}]{pct}%[/{pct_color}] [dim]•[/dim] "
                f"[bold green]{free} free[/bold green]"
            )
        if root_d:
            used = format_size(root_d["used_bytes"])
            total = format_size(root_d["total_bytes"])
            pct = root_d["use_percent"]
            spark = render_sparkbar(pct / 100.0, width=8)
            pct_color = "red" if pct >= 90 else ("yellow" if pct >= 70 else "green")
            if mango:
                parts.append(f"[dim]• System (/): {used} / {total} {spark} {pct}%[/dim]")
            else:
                free = format_size(root_d["free_bytes"])
                parts.append(
                    f"💾 [bold white]Storage (/):[/bold white] "
                    f"[bold cyan]{used}[/bold cyan] / [bold cyan]{total}[/bold cyan] "
                    f"{spark} [{pct_color}]{pct}%[/{pct_color}] [dim]•[/dim] "
                    f"[bold green]{free} free[/bold green]"
                )
        if parts:
            console.print(" ".join(parts))

    root = Tree("", hide_root=True, guide_style="dim")

    for r in results:
        if r.status == HealthStatus.HEALTHY:
            icon_prefix = ""
        elif r.status == HealthStatus.DEGRADED:
            icon_prefix = "🟡 "
        else:
            icon_prefix = "🔴 "

        if r.latency_ms < 100:
            lat_str = f"[green]{r.latency_ms:.0f}ms[/green]"
        elif r.latency_ms < 500:
            lat_str = f"[yellow]{r.latency_ms:.0f}ms[/yellow]"
        else:
            lat_str = f"[red]{r.latency_ms:.0f}ms[/red]"

        ver_str = f" [dim cyan]({r.version})[/dim cyan]" if r.version else ""
        node_header = (
            f"{icon_prefix}[bold white]{r.name}[/bold white] "
            f"[dim cyan]{r.container}[/dim cyan]{ver_str} [dim]•[/dim] {lat_str}"
        )
        branch_node = root.add(node_header)

        # Add child branches
        if r.branches:
            for b in r.branches:
                branch_node.add(b)
        else:
            branch_node.add(f"[dim]{r.summary}[/dim]")

    console.print(root)


@app.command()
def main(
    services: list[str] = typer.Option(
        None,
        "--service",
        "-s",
        help="Specific service(s) to check (e.g. -s jellyfin -s bookorbit)",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output raw check results as formatted JSON",
    ),
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        "-e",
        help="Path to homelab .env file",
    ),
    docker_host: str | None = typer.Option(
        None,
        "--docker-host",
        help="Override Docker daemon URL (e.g. ssh://ehtesh@m70q.lan)",
    ),
    no_docker: bool = typer.Option(
        False,
        "--no-docker",
        help="Skip Docker inspection and execute network/HTTP checks only",
    ),
    lan_host: str | None = typer.Option(
        None,
        "--lan-host",
        "--host",
        "-H",
        help="Target host for SMB/Docker connection (auto-resolves m70q.lan or m70q on Tailscale)",
    ),
    timeout: float = typer.Option(
        10.0,
        "--timeout",
        "-t",
        help="Per-service check timeout in seconds",
    ),
) -> None:
    """Run deep health & content availability checks across homelab services."""
    conn = resolve_target_connection(lan_host)
    env = load_env(env_file, conn.host)
    username = env.get("HOMELAB_USERNAME", "ehtesh")
    password = env.get("HOMELAB_PASSWORD", "")
    base_domain = env.get("HOSTNAME_BASE", "009973.xyz")

    if not password:
        console.print("[bold red]Error:[/bold red] HOMELAB_PASSWORD not found in .env or environment")
        sys.exit(1)

    docker_client = get_docker_client(docker_host, conn.host, no_docker)

    ctx = StatusContext(
        env=env,
        username=username,
        password=password,
        base_domain=base_domain,
        lan_host=conn.host,
        docker_client=docker_client,
        http_timeout=timeout,
        no_docker=no_docker,
        connection=conn,
    )

    # Determine which checks to run
    if services:
        selected_keys = [s.lower().strip() for s in services]
        invalid = [s for s in selected_keys if s not in CHECK_REGISTRY]
        if invalid:
            console.print(f"[bold red]Unknown service(s):[/bold red] {', '.join(invalid)}")
            console.print(f"Available services: {', '.join(CHECK_REGISTRY.keys())}")
            sys.exit(1)
        selected_checks = {k: fn for k, fn in CHECK_REGISTRY.items() if k in selected_keys}
    else:
        selected_checks = CHECK_REGISTRY

    # Terminal UI output mode: print header panel immediately before checks
    if not json_output:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header_text = Text()
        header_text.append("🔮 Homelab Deep Health & Content Inspector\n", style="bold magenta")

        if conn.route == "local":
            route_badge = f"[bold magenta]🏠 {conn.description}[/bold magenta]"
        elif conn.route == "tailscale":
            route_badge = f"[bold cyan]🔒 {conn.description}[/bold cyan]"
        elif conn.route == "lan":
            route_badge = f"[bold green]🟢 {conn.description}[/bold green]"
        else:
            route_badge = f"[bold yellow]🌐 {conn.description}[/bold yellow]"

        ip_info = f" ({conn.ip})" if conn.ip and conn.ip != "unknown" else ""
        header_text.append(f"Target: {conn.host}{ip_info}  •  Route: ", style="dim")
        header_text.append_text(Text.from_markup(route_badge))
        header_text.append(f"\nDomain: {base_domain}  •  Auth: {username}  •  Time: {now_str}", style="dim")
        console.print(Panel(header_text, border_style="magenta", expand=False))

    show_progress = not json_output and console.is_terminal
    t_start = time.perf_counter()
    results = anyio.run(_run_all_checks, ctx, selected_checks, show_progress)
    total_elapsed = time.perf_counter() - t_start

    # Preserve consistent ordering matching CHECK_REGISTRY
    order = list(CHECK_REGISTRY.keys())
    results.sort(key=lambda r: order.index(r.service_id) if r.service_id in order else 999)

    # JSON output mode
    if json_output:
        out_dict = {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "connection": asdict(conn),
            "target_host": conn.host,
            "base_domain": base_domain,
            "total_elapsed_seconds": round(total_elapsed, 3),
            "all_healthy": all(r.is_healthy for r in results),
            "disk_usage": ctx.disk_usage or [],
            "services": [asdict(r) for r in results],
        }
        print(json.dumps(out_dict, indent=2))
        sys.exit(0 if all(r.is_healthy for r in results) else 1)

    render_tree(results, total_elapsed, ctx.disk_usage)

    # Summary footer
    passed_count = sum(1 for r in results if r.is_healthy)
    total_count = len(results)
    all_passed = all(r.is_healthy for r in results)

    console.print()
    if all_passed:
        console.print(
            f"✔ [bold green]All {passed_count}/{total_count} services healthy[/bold green] "
            f"[dim]•[/dim] [bold white]Total time:[/bold white] [bold cyan]{total_elapsed:.2f}s[/bold cyan] "
            f"[dim](verified logins, content & containers)[/dim]\n"
        )
        sys.exit(0)
    else:
        failed_count = total_count - passed_count
        console.print(
            f"✖ [bold red]{failed_count}/{total_count} services unhealthy or degraded[/bold red] "
            f"[dim]•[/dim] [bold white]Total time:[/bold white] [bold yellow]{total_elapsed:.2f}s[/bold yellow]\n"
        )
        sys.exit(1)


if __name__ == "__main__":
    app()
