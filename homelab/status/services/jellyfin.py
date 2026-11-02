"""Jellyfin content and session health check."""

from __future__ import annotations

import time
from typing import Any

import anyio
import httpx

from models import HealthStatus, ServiceResult, StatusContext


async def check_jellyfin(ctx: StatusContext) -> ServiceResult:
    service_id = "jellyfin"
    name = "Jellyfin"
    container = "homelab-jellyfin-1"
    t0 = time.perf_counter()

    try:
        async with httpx.AsyncClient(base_url=ctx.base_url("jellyfin"), timeout=ctx.http_timeout) as client:
            auth_header = (
                'MediaBrowser Client="StatusCheck", Device="m70q", DeviceId="homelab-status-check", Version="1.0.0"'
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
            headers = {
                "Authorization": auth_with_tok,
                "X-Emby-Authorization": auth_with_tok,
                "X-Emby-Token": token,
            }

            counts_data: dict[str, Any] = {}
            active_streams: list[str] = []
            version: str | None = None

            async def _fetch_version() -> None:
                nonlocal version
                try:
                    info_res = await client.get("/System/Info/Public")
                    if info_res.status_code == 200:
                        v = info_res.json().get("Version")
                        if v:
                            version = f"v{v}"
                except Exception:
                    pass
                if not version:
                    version = await ctx.get_container_version(container)

            async def _fetch_counts() -> None:
                nonlocal counts_data
                counts_res = await client.get("/Items/Counts", headers=headers)
                if counts_res.status_code == 200:
                    counts_data = counts_res.json()

            async def _fetch_sessions() -> None:
                nonlocal active_streams
                try:
                    sess_res = await client.get("/Sessions", headers=headers)
                    if sess_res.status_code == 200:
                        for s in sess_res.json():
                            now_playing = s.get("NowPlayingItem")
                            if now_playing:
                                user_name = s.get("UserName", "user")
                                media_name = now_playing.get("Name", "media")
                                active_streams.append(
                                    f'[bold yellow]{user_name}[/bold yellow]: "[bold green]{media_name}[/bold green]"'
                                )
                except Exception:
                    pass

            async with anyio.create_task_group() as tg:
                tg.start_soon(_fetch_counts)
                tg.start_soon(_fetch_sessions)
                tg.start_soon(_fetch_version)

            elapsed = (time.perf_counter() - t0) * 1000

            if not counts_data:
                return ServiceResult(
                    service_id=service_id,
                    name=name,
                    container=container,
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=elapsed,
                    summary="Failed to query item counts",
                    branches=["[bold red]✖ Query counts returned empty or failed[/bold red]"],
                )

            movies = counts_data.get("MovieCount", 0)
            series = counts_data.get("SeriesCount", 0)
            episodes = counts_data.get("EpisodeCount", 0)
            boxsets = counts_data.get("BoxSetCount", 0)
            items = counts_data.get("ItemCount", 0)

            summary = f"{movies} movies, {series} series ({episodes:,} eps), {boxsets} boxsets • {items:,} total items"
            branches = [
                f"🎬 Movies: [bold cyan]{movies:,}[/bold cyan]",
                (
                    f"📺 TV Shows: [bold cyan]{series:,}[/bold cyan] series "
                    f"[dim]([bold cyan]{episodes:,}[/bold cyan] episodes)[/dim]"
                ),
                (
                    f"📦 Collections: [bold cyan]{boxsets:,}[/bold cyan] boxsets "
                    f"[dim]•[/dim] [bold cyan]{items:,}[/bold cyan] total items"
                ),
            ]
            if active_streams:
                branches.append(f"▶️ Active Playback: {', '.join(active_streams)}")

            return ServiceResult(
                service_id=service_id,
                name=name,
                container=container,
                status=HealthStatus.HEALTHY,
                latency_ms=elapsed,
                summary=summary,
                version=version,
                branches=branches,
                raw_data=counts_data,
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
