"""Qui WebUI and connected download client instances health check."""

from __future__ import annotations

import time

import httpx

from ..models import HealthStatus, ServiceResult, StatusContext


async def check_qui(ctx: StatusContext) -> ServiceResult:
    service_id = "qui"
    name = "Qui WebUI"
    container = "homelab-qui-1"
    t0 = time.perf_counter()

    try:
        async with httpx.AsyncClient(base_url=ctx.base_url("qui"), timeout=ctx.http_timeout) as client:
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

            inst_res = await client.get("/api/instances")
            if inst_res.status_code != 200:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id=service_id,
                    name=name,
                    container=container,
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=elapsed,
                    summary=f"Failed to query instances: HTTP {inst_res.status_code}",
                    branches=[f"[bold red]✖ Query instances failed (HTTP {inst_res.status_code})[/bold red]"],
                    error=inst_res.text,
                )

            instances = inst_res.json()
            elapsed = (time.perf_counter() - t0) * 1000

            connected_count = sum(1 for i in instances if i.get("connected") is True)
            inst_desc = [
                f'"{i.get("name")}" ({i.get("host")})'
                for i in instances
            ]
            desc_str = ", ".join(inst_desc) if inst_desc else "no instances configured"
            summary = f"{connected_count}/{len(instances)} instance connected: {desc_str}"

            status = HealthStatus.HEALTHY
            if connected_count < len(instances) or not instances:
                status = HealthStatus.DEGRADED

            branches = [
                (
                    f"🔗 Connected Instances: [bold white]{connected_count}/{len(instances)}[/bold white] "
                    f"[dim]({desc_str})[/dim]"
                )
            ]

            return ServiceResult(
                service_id=service_id,
                name=name,
                container=container,
                status=status,
                latency_ms=elapsed,
                summary=summary,
                branches=branches,
                raw_data={"instances": instances},
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
