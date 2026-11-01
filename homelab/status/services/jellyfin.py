"""Jellyfin content and session health check."""

from __future__ import annotations

import time

import httpx

from ..models import HealthStatus, ServiceResult, StatusContext


async def check_jellyfin(ctx: StatusContext) -> ServiceResult:
    service_id = "jellyfin"
    name = "Jellyfin"
    container = "homelab-jellyfin-1"
    t0 = time.perf_counter()

    try:
        async with httpx.AsyncClient(base_url=ctx.base_url("jellyfin"), timeout=ctx.http_timeout) as client:
            auth_header = (
                'MediaBrowser Client="StatusCheck", Device="m70q", '
                'DeviceId="homelab-status-check", Version="1.0.0"'
            )
            login_res = await client.post(
                "/Users/AuthenticateByName",
                json={"Username": ctx.username, "Pw": ctx.password},
                headers={
                    "Authorization": auth_header,
                    "X-Emby-Authorization": auth_header,
                },
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

            token = login_res.json().get("AccessToken")
            auth_with_tok = f'{auth_header}, Token="{token}"'
            counts_res = await client.get(
                "/Items/Counts",
                headers={
                    "Authorization": auth_with_tok,
                    "X-Emby-Authorization": auth_with_tok,
                    "X-Emby-Token": token,
                },
            )
            if counts_res.status_code != 200:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id=service_id,
                    name=name,
                    container=container,
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=elapsed,
                    summary=f"Failed to query counts: HTTP {counts_res.status_code}",
                    branches=[f"[bold red]✖ Query counts failed (HTTP {counts_res.status_code})[/bold red]"],
                    error=counts_res.text,
                )

            data = counts_res.json()

            # Active streaming playback sessions check
            active_streams: list[str] = []
            try:
                sess_res = await client.get(
                    "/Sessions",
                    headers={
                        "Authorization": auth_with_tok,
                        "X-Emby-Authorization": auth_with_tok,
                        "X-Emby-Token": token,
                    },
                )
                if sess_res.status_code == 200:
                    for s in sess_res.json():
                        now_playing = s.get("NowPlayingItem")
                        if now_playing:
                            active_streams.append(f"{s.get('UserName', 'user')}: {now_playing.get('Name')}")
            except Exception:
                pass

            elapsed = (time.perf_counter() - t0) * 1000

            movies = data.get("MovieCount", 0)
            series = data.get("SeriesCount", 0)
            episodes = data.get("EpisodeCount", 0)
            boxsets = data.get("BoxSetCount", 0)
            items = data.get("ItemCount", 0)

            summary = (
                f"{movies} movies, {series} series ({episodes:,} eps), "
                f"{boxsets} boxsets • {items:,} total items"
            )
            branches = [
                f"🎬 Movies: [bold white]{movies}[/bold white]",
                f"📺 TV Shows: [bold white]{series}[/bold white] series [dim]({episodes:,} episodes)[/dim]",
                (
                    f"📦 Collections: [bold white]{boxsets}[/bold white] boxsets "
                    f"[dim]•[/dim] [bold white]{items:,}[/bold white] total items"
                ),
            ]
            if active_streams:
                branches.append(f"▶️ Active Playback: [bold green]{', '.join(active_streams)}[/bold green]")

            return ServiceResult(
                service_id=service_id,
                name=name,
                container=container,
                status=HealthStatus.HEALTHY,
                latency_ms=elapsed,
                summary=summary,
                branches=branches,
                raw_data=data,
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
