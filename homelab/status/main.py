#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "anyio>=4.7.0",
#   "docker>=7.1.0",
#   "httpx>=0.27.0",
#   "paramiko>=3.5.0",
#   "python-dotenv>=1.0.0",
#   "rich>=13.0.0",
#   "typer>=0.16.0",
# ]
# ///
"""Homelab Deep Health & Content Inspector - CLI Entrypoint."""

from __future__ import annotations

import datetime
import json
import logging
import sys
import time
from dataclasses import asdict
from pathlib import Path

# Ensure package root is in sys.path when executed directly
_PKG_DIR = Path(__file__).resolve().parent
_HOMELAB_DIR = _PKG_DIR.parent
if str(_HOMELAB_DIR) not in sys.path:
    sys.path.insert(0, str(_HOMELAB_DIR))

import anyio
import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.tree import Tree

from status.config import get_docker_client, load_env, resolve_target_host
from status.models import HealthStatus, ServiceResult, StatusContext
from status.services import CHECK_REGISTRY, CheckFn

# Silence noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("docker").setLevel(logging.WARNING)
logging.getLogger("paramiko").setLevel(logging.WARNING)

app = typer.Typer(
    help="Homelab Deep Health & Content Inspector",
    add_completion=False,
)
console = Console()


async def _run_all_checks(
    ctx: StatusContext,
    checks: dict[str, CheckFn],
) -> list[ServiceResult]:
    """Execute all selected checks concurrently using an AnyIO task group."""
    check_items = list(checks.items())
    results: list[ServiceResult | None] = [None] * len(check_items)

    async def _execute(idx: int, service_id: str, fn: CheckFn) -> None:
        try:
            results[idx] = await fn(ctx)
        except Exception as exc:
            results[idx] = ServiceResult(
                service_id=service_id,
                name=service_id.capitalize(),
                container=f"homelab-{service_id}-1",
                status=HealthStatus.UNHEALTHY,
                latency_ms=0.0,
                summary=f"Unexpected check failure: {exc}",
                branches=[f"[bold red]✖ Unexpected check failure: {exc}[/bold red]"],
                error=str(exc),
            )

    async with anyio.create_task_group() as tg:
        for idx, (service_id, fn) in enumerate(check_items):
            tg.start_soon(_execute, idx, service_id, fn)

    return [r for r in results if r is not None]


def render_tree(results: list[ServiceResult], total_elapsed: float) -> None:
    """Render check results as a hierarchical, deep-inspection Rich Tree."""
    all_healthy = all(r.is_healthy for r in results)
    passed_count = sum(1 for r in results if r.is_healthy)
    total_count = len(results)

    if all_healthy:
        status_tag = f"[bold green][{passed_count}/{total_count} healthy][/bold green]"
    else:
        status_tag = f"[bold yellow][{passed_count}/{total_count} healthy][/bold yellow]"

    root = Tree(
        f"[bold magenta]🔮 Homelab Services[/bold magenta] {status_tag} [dim]({total_elapsed:.2f}s)[/dim]",
        guide_style="dim",
    )

    for r in results:
        if r.status == HealthStatus.HEALTHY:
            icon = "🟢"
        elif r.status == HealthStatus.DEGRADED:
            icon = "🟡"
        else:
            icon = "🔴"

        if r.latency_ms < 100:
            lat_str = f"[green]{r.latency_ms:.0f}ms[/green]"
        elif r.latency_ms < 500:
            lat_str = f"[yellow]{r.latency_ms:.0f}ms[/yellow]"
        else:
            lat_str = f"[red]{r.latency_ms:.0f}ms[/red]"

        node_header = (
            f"{icon} [bold white]{r.name}[/bold white] "
            f"[dim cyan]{r.container}[/dim cyan] [dim]•[/dim] {lat_str}"
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
    target_host = resolve_target_host(lan_host)
    env = load_env(env_file, target_host)
    username = env.get("HOMELAB_USERNAME", "ehtesh")
    password = env.get("HOMELAB_PASSWORD", "")
    base_domain = env.get("HOSTNAME_BASE", "009973.xyz")

    if not password:
        console.print("[bold red]Error:[/bold red] HOMELAB_PASSWORD not found in .env or environment")
        sys.exit(1)

    docker_client = get_docker_client(docker_host, target_host, no_docker)

    ctx = StatusContext(
        env=env,
        username=username,
        password=password,
        base_domain=base_domain,
        lan_host=target_host,
        docker_client=docker_client,
        http_timeout=timeout,
        no_docker=no_docker,
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

    t_start = time.perf_counter()
    results = anyio.run(_run_all_checks, ctx, selected_checks)
    total_elapsed = time.perf_counter() - t_start

    # Preserve consistent ordering matching CHECK_REGISTRY
    order = list(CHECK_REGISTRY.keys())
    results.sort(key=lambda r: order.index(r.service_id) if r.service_id in order else 999)

    # JSON output mode
    if json_output:
        out_dict = {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "target_host": target_host,
            "base_domain": base_domain,
            "total_elapsed_seconds": round(total_elapsed, 3),
            "all_healthy": all(r.is_healthy for r in results),
            "services": [asdict(r) for r in results],
        }
        print(json.dumps(out_dict, indent=2))
        sys.exit(0 if all(r.is_healthy for r in results) else 1)

    # Terminal UI output mode (Rich Tree)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header_text = Text()
    header_text.append("🔮 Homelab Deep Health & Content Inspector\n", style="bold magenta")
    header_text.append(f"Target: {target_host} ({base_domain})  •  Time: {now_str}  •  Auth: {username}", style="dim")
    console.print(Panel(header_text, border_style="magenta", expand=False))

    render_tree(results, total_elapsed)

    # Summary footer
    passed_count = sum(1 for r in results if r.is_healthy)
    total_count = len(results)
    all_passed = all(r.is_healthy for r in results)

    console.print()
    if all_passed:
        console.print(
            f"[bold green]✔ All {passed_count}/{total_count} services healthy[/bold green] "
            f"• Verified logins, content availability & containers in [bold cyan]{total_elapsed:.2f}s[/bold cyan]\n"
        )
        sys.exit(0)
    else:
        failed_count = total_count - passed_count
        console.print(
            f"[bold red]✖ {failed_count}/{total_count} services unhealthy or degraded[/bold red] "
            f"• Elapsed: [bold yellow]{total_elapsed:.2f}s[/bold yellow]\n"
        )
        sys.exit(1)


if __name__ == "__main__":
    app()
