"""Arcane management API, version, and project health check."""

from __future__ import annotations

import time

import anyio
import httpx

from ..models import HealthStatus, ServiceResult, StatusContext


async def check_arcane(ctx: StatusContext) -> ServiceResult:
    service_id = "arcane"
    name = "Arcane Management"
    container = "homelab-arcane-1"
    t0 = time.perf_counter()

    try:
        async with httpx.AsyncClient(base_url=ctx.base_url("arcane"), timeout=ctx.http_timeout) as client:
            login_res = await client.post(
                "/api/auth/login",
                json={"username": ctx.username, "password": ctx.password},
            )
            if login_res.status_code != 200:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id=service_id,
                    name=name,
                    container=container,
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=elapsed,
                    summary=f"Authentication failed: HTTP {login_res.status_code}",
                    branches=[f"[bold red]✖ Authentication failed (HTTP {login_res.status_code})[/bold red]"],
                    error=login_res.text,
                )

            version = "v2"
            containers_count = 0
            projects_count = 0

            async def _fetch_version() -> None:
                nonlocal version
                ver_res = await client.get("/api/version")
                if ver_res.status_code == 200:
                    version = ver_res.json().get("currentVersion", "v2")

            async def _fetch_containers() -> None:
                nonlocal containers_count
                cnt_res = await client.get("/api/environments/0/containers")
                if cnt_res.status_code == 200:
                    containers_count = len(cnt_res.json().get("data", []))

            async def _fetch_projects() -> None:
                nonlocal projects_count
                proj_res = await client.get("/api/environments/0/projects")
                if proj_res.status_code == 200:
                    projects_count = len(proj_res.json().get("data", []))

            # Query version, containers, and projects concurrently
            async with anyio.create_task_group() as tg:
                tg.start_soon(_fetch_version)
                tg.start_soon(_fetch_containers)
                tg.start_soon(_fetch_projects)

            elapsed = (time.perf_counter() - t0) * 1000
            target_name = ctx.lan_host.split(".")[0]
            summary = f'{version} • {containers_count} containers, {projects_count} projects on "{target_name}"'

            branches = [
                f"🏷️ Version: [bold cyan]{version}[/bold cyan]",
                (
                    f"📦 Managed: [bold cyan]{containers_count}[/bold cyan] containers, "
                    f'[bold cyan]{projects_count}[/bold cyan] projects on [bold yellow]"{target_name}"[/bold yellow]'
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
                raw_data={"version": version, "containers": containers_count, "projects": projects_count},
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
