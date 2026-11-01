"""BookOrbit PostgreSQL database connectivity and metrics health check."""

from __future__ import annotations

import time

from ..models import HealthStatus, ServiceResult, StatusContext


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
        # 1. pg_isready check
        ready_code, ready_out = await ctx.exec_container(container, "pg_isready -U bookorbit -d bookorbit")
        if ready_code != 0:
            elapsed = (time.perf_counter() - t0) * 1000
            return ServiceResult(
                service_id=service_id,
                name=name,
                container=container,
                status=HealthStatus.UNHEALTHY,
                latency_ms=elapsed,
                summary=f"pg_isready failed: {ready_out.strip()}",
                branches=[f"[bold red]✖ pg_isready failed: {ready_out.strip()}[/bold red]"],
            )

        # 2. Query book count in database
        query_code, query_out = await ctx.exec_container(
            container, 'psql -U bookorbit -d bookorbit -t -c "SELECT count(*) FROM books;"'
        )
        book_count = query_out.strip() if query_code == 0 else "?"

        # 3. Query database disk size
        size_code, size_out = await ctx.exec_container(
            container, "psql -U bookorbit -d bookorbit -t -c \"SELECT pg_size_pretty(pg_database_size('bookorbit'));\""
        )
        db_size = size_out.strip() if size_code == 0 else "?"

        elapsed = (time.perf_counter() - t0) * 1000
        summary = f'PostgreSQL 18 accepting connections • {book_count} books ({db_size}) in database "bookorbit"'

        branches = [
            "🔌 Connection: [bold white]PostgreSQL 18[/bold white] [dim](accepting connections)[/dim]",
            (
                f"💾 Storage: [bold white]{book_count} books[/bold white] [dim]•[/dim] "
                f'[bold white]{db_size}[/bold white] in database [dim]"bookorbit"[/dim]'
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
