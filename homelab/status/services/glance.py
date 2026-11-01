"""Glance home dashboard availability health check."""

from __future__ import annotations

import re
import time

import httpx

from ..models import HealthStatus, ServiceResult, StatusContext


async def check_glance(ctx: StatusContext) -> ServiceResult:
    service_id = "glance"
    name = "Glance Dashboard"
    container = "homelab-glance-1"
    t0 = time.perf_counter()

    try:
        async with httpx.AsyncClient(base_url=f"https://{ctx.base_domain}", timeout=ctx.http_timeout) as client:
            res = await client.get("/")
            elapsed = (time.perf_counter() - t0) * 1000

            if res.status_code != 200:
                return ServiceResult(
                    service_id=service_id,
                    name=name,
                    container=container,
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=elapsed,
                    summary=f"Dashboard returned HTTP {res.status_code}",
                    branches=[f"[bold red]✖ Dashboard returned HTTP {res.status_code}[/bold red]"],
                )

            title_match = re.search(r"<title>(.*?)</title>", res.text, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else "Dashboard"
            summary = f'Dashboard online (HTTP {res.status_code}, title: "{title}")'
            branches = [f'🖥️ Route: [bold green]HTTP {res.status_code}[/bold green] [dim](title: "[bold yellow]{title}[/bold yellow]")[/dim]']

            return ServiceResult(
                service_id=service_id,
                name=name,
                container=container,
                status=HealthStatus.HEALTHY,
                latency_ms=elapsed,
                summary=summary,
                branches=branches,
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
