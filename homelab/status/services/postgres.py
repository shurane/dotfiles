"""BookOrbit PostgreSQL database connectivity and metrics health check."""

from __future__ import annotations

import time

from models import HealthStatus, ServiceResult, StatusContext


async def check_postgres(ctx: StatusContext) -> ServiceResult:
    service_id = "postgres"
    name = "BookOrbit Database"
    container = "homelab-bookorbit-postgres-1"
    t0 = time.perf_counter()

    c = await ctx.get_container(container)
    if not c:
        elapsed = (time.perf_counter() - t0) * 1000
        if ctx.no_docker:
            return ServiceResult(
                service_id=service_id,
                name=name,
                container=container,
                status=HealthStatus.HEALTHY,
                latency_ms=elapsed,
                summary="Database running (Docker inspection skipped via --no-docker)",
                branches=["[dim]Docker inspection skipped (--no-docker)[/dim]"],
            )
        return ServiceResult(
            service_id=service_id,
            name=name,
            container=container,
            status=HealthStatus.UNHEALTHY,
            latency_ms=elapsed,
            summary="Container not found or Docker unreachable",
            branches=["[bold red]✖ Container not found or Docker unreachable[/bold red]"],
        )

    try:
        cmd = (
            'sh -c "pg_isready -U bookorbit -d bookorbit && '
            "psql -U bookorbit -d bookorbit -t -A -F '|' -c "
            '\\"SELECT count(*), pg_size_pretty(pg_database_size(current_database())) FROM books;\\""'
        )
        code, out = await ctx.exec_container(container, cmd)
        elapsed = (time.perf_counter() - t0) * 1000

        if code != 0:
            return ServiceResult(
                service_id=service_id,
                name=name,
                container=container,
                status=HealthStatus.UNHEALTHY,
                latency_ms=elapsed,
                summary=f"Database probe failed: {out.strip()}",
                branches=[f"[bold red]✖ Database probe failed: {out.strip()}[/bold red]"],
            )

        book_count = "?"
        db_size = "?"
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        if lines:
            last_line = lines[-1]
            if "|" in last_line:
                parts = last_line.split("|", 1)
                book_count = parts[0].strip()
                db_size = parts[1].strip()

        summary = f'PostgreSQL 18 accepting connections • {book_count} books ({db_size}) in database "bookorbit"'

        branches = [
            "🔌 Connection: [bold green]PostgreSQL 18[/bold green] [dim](accepting connections)[/dim]",
            (
                f"💾 Storage: [bold cyan]{book_count}[/bold cyan] books [dim]•[/dim] "
                f'[bold cyan]{db_size}[/bold cyan] in database [bold yellow]"bookorbit"[/bold yellow]'
            ),
        ]

        return ServiceResult(
            service_id=service_id,
            name=name,
            container=container,
            status=HealthStatus.HEALTHY,
            latency_ms=elapsed,
            summary=summary,
            branches=branches,
            raw_data={"books_count": book_count, "db_size": db_size},
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ServiceResult(
            service_id=service_id,
            name=name,
            container=container,
            status=HealthStatus.UNHEALTHY,
            latency_ms=elapsed,
            summary=f"Error: {exc}",
            branches=[f"[bold red]✖ Error: {exc}[/bold red]"],
            error=str(exc),
        )
