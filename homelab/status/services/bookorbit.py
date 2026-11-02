"""BookOrbit library content health check."""

from __future__ import annotations

import time

import httpx

from models import HealthStatus, ServiceResult, StatusContext


async def check_bookorbit(ctx: StatusContext) -> ServiceResult:
    service_id = "bookorbit"
    name = "BookOrbit"
    container = "homelab-bookorbit-1"
    t0 = time.perf_counter()

    try:
        async with httpx.AsyncClient(base_url=ctx.base_url("bookorbit"), timeout=ctx.http_timeout) as client:
            login_res = await client.post(
                "/api/v1/auth/login",
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

            token = login_res.json().get("accessToken")
            libs_res = await client.get(
                "/api/v1/libraries",
                headers={"Authorization": f"Bearer {token}"},
            )
            if libs_res.status_code != 200:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id=service_id,
                    name=name,
                    container=container,
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=elapsed,
                    summary=f"Failed to query libraries: HTTP {libs_res.status_code}",
                    branches=[f"[bold red]✖ Query libraries failed (HTTP {libs_res.status_code})[/bold red]"],
                    error=libs_res.text,
                )

            libraries = libs_res.json()
            elapsed = (time.perf_counter() - t0) * 1000

            total_books = sum(lib.get("bookCount", 0) for lib in libraries)
            branches = []
            lib_summaries = []

            for lib in libraries:
                lname = lib.get("name", "Unknown")
                bcount = lib.get("bookCount", 0)
                folders = lib.get("folders", [])
                fpath = folders[0].get("path", "") if folders else ""
                if fpath:
                    branches.append(
                        f'📚 Library "[bold yellow]{lname}[/bold yellow]": '
                        f"[bold cyan]{bcount:,}[/bold cyan] books "
                        f"[dim](in [bold magenta]{fpath}[/bold magenta])[/dim]"
                    )
                    lib_summaries.append(f'"{lname}": {bcount} in {fpath}')
                else:
                    branches.append(
                        f'📚 Library "[bold yellow]{lname}[/bold yellow]": [bold cyan]{bcount:,}[/bold cyan] books'
                    )
                    lib_summaries.append(f'"{lname}": {bcount}')

            branches.append(f"📖 Total Books: [bold cyan]{total_books:,}[/bold cyan]")

            count_noun = "library" if len(libraries) == 1 else "libraries"
            summary = f"{total_books} books in {len(libraries)} {count_noun} ({', '.join(lib_summaries)})"

            return ServiceResult(
                service_id=service_id,
                name=name,
                container=container,
                status=HealthStatus.HEALTHY,
                latency_ms=elapsed,
                summary=summary,
                branches=branches,
                raw_data={"libraries": libraries, "total_books": total_books},
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
