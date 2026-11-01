"""Arcane management API, version, and project health check."""

from __future__ import annotations

import time

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

            ver_res = await client.get("/api/version")
            version = ver_res.json().get("currentVersion", "v2") if ver_res.status_code == 200 else "v2"

            cnt_res = await client.get("/api/environments/0/containers")
            containers_count = len(cnt_res.json().get("data", [])) if cnt_res.status_code == 200 else 0

            proj_res = await client.get("/api/environments/0/projects")
            projects_count = len(proj_res.json().get("data", [])) if proj_res.status_code == 200 else 0

            elapsed = (time.perf_counter() - t0) * 1000
            summary = f"{version} • {containers_count} containers, {projects_count} projects on 'm70q'"

            branches = [
                f"🏷️ Version: [bold white]{version}[/bold white]",
                (
                    f"📦 Managed: [bold white]{containers_count} containers[/bold white], "
                    f"[bold white]{projects_count} projects[/bold white] on [dim]'m70q'[/dim]"
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
