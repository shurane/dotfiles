"""Withings Health Sync supercronic cron scheduler and execution health check."""

from __future__ import annotations

import re
import time

from ..models import HealthStatus, ServiceResult, StatusContext


async def check_withings_sync(ctx: StatusContext) -> ServiceResult:
    service_id = "withings-sync"
    name = "Withings Health Sync"
    container = "homelab-withings-sync-1"
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
                summary="Container running (Docker inspection skipped via --no-docker)",
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
        status_val = c.status
        health_val = c.attrs.get("State", {}).get("Health", {}).get("Status", "none")

        code, _ = await ctx.exec_container(container, "pgrep -f supercronic")
        has_proc = code == 0

        elapsed = (time.perf_counter() - t0) * 1000
        if not has_proc or status_val != "running":
            return ServiceResult(
                service_id=service_id,
                name=name,
                container=container,
                status=HealthStatus.UNHEALTHY,
                latency_ms=elapsed,
                summary=f"Scheduler process inactive (status={status_val}, health={health_val})",
                branches=[f"[bold red]✖ Scheduler process inactive ({status_val}, {health_val})[/bold red]"],
            )

        # Inspect recent logs for latest job execution and schedule
        logs = await ctx.get_container_logs(container, tail=30)
        last_sync_time = "Unknown"
        last_status = "active"
        schedule = "/home/withings-sync/cronjob"

        matches = re.findall(
            r'time="([^"]+)".*msg="job (succeeded|failed)".*job\.schedule="([^"]+)"',
            logs,
        )
        if matches:
            raw_ts, status_word, sched_val = matches[-1]
            last_status = status_word
            schedule = sched_val
            try:
                # e.g. 2026-10-31T13:52:03-07:00 -> 2026-10-31 13:52
                parts = raw_ts.split("T")
                time_part = parts[1].split("-")[0].split("+")[0][:5]
                last_sync_time = f"{parts[0]} {time_part}"
            except Exception:
                last_sync_time = raw_ts

        status = HealthStatus.DEGRADED if last_status == "failed" else HealthStatus.HEALTHY
        summary = f"Supercronic active ({health_val}) • last sync: {last_sync_time} ({last_status})"

        branches = [
            f"⏱️ Scheduler: [bold green]Supercronic active[/bold green] [dim]({health_val})[/dim]",
        ]
        if last_sync_time != "Unknown":
            status_style = "bold green" if last_status == "succeeded" else "bold yellow"
            branches.append(
                f"🔄 Last Sync: [{status_style}]{last_sync_time}[/{status_style}] "
                f"[dim]({last_status} • schedule: [bold cyan]{schedule}[/bold cyan])[/dim]"
            )
        else:
            branches.append(f"🔄 Cronjob: [dim]{schedule}[/dim]")

        return ServiceResult(
            service_id=service_id,
            name=name,
            container=container,
            status=status,
            latency_ms=elapsed,
            summary=summary,
            branches=branches,
            raw_data={
                "status": status_val,
                "health": health_val,
                "last_sync": last_sync_time,
                "last_status": last_status,
            },
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
