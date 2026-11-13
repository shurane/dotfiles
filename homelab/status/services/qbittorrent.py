"""qBittorrent completed torrents, active counts, and speed health check."""

from __future__ import annotations

import time

import httpx

from config import format_speed
from models import HealthStatus, ServiceResult, StatusContext


async def check_qbittorrent(ctx: StatusContext) -> ServiceResult:
    service_id = "qbittorrent"
    name = "qBittorrent"
    container = "homelab-qbittorrent-1"
    t0 = time.perf_counter()

    try:
        async with httpx.AsyncClient(base_url=ctx.base_url("qbittorrent"), timeout=ctx.http_timeout) as client:
            login_res = await client.post(
                "/api/v2/auth/login",
                data={"username": ctx.username, "password": ctx.password},
            )
            if login_res.status_code not in (200, 204) or "Fails" in login_res.text:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id=service_id,
                    name=name,
                    container=container,
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=elapsed,
                    summary=f"Authentication failed: HTTP {login_res.status_code} ({login_res.text.strip()})",
                    branches=[f"[bold red]✖ Authentication failed (HTTP {login_res.status_code})[/bold red]"],
                    error=login_res.text,
                )

            data_res = await client.get("/api/v2/sync/maindata")
            if data_res.status_code != 200:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id=service_id,
                    name=name,
                    container=container,
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=elapsed,
                    summary=f"Failed to fetch torrent state: HTTP {data_res.status_code}",
                    branches=[f"[bold red]✖ Fetch torrents failed (HTTP {data_res.status_code})[/bold red]"],
                    error=data_res.text,
                )

            maindata = data_res.json()
            elapsed = (time.perf_counter() - t0) * 1000

            torrents = maindata.get("torrents", {})
            server_state = maindata.get("server_state", {})

            total = len(torrents)
            completed = sum(1 for t in torrents.values() if t.get("progress", 0) >= 1.0)
            active = sum(
                1 for t in torrents.values() if t.get("state") in ("downloading", "uploading", "stalledUP", "stalledDL")
            )
            errored = sum(1 for t in torrents.values() if t.get("state") in ("error", "missingFiles"))

            dl_speed = format_speed(server_state.get("dl_info_speed", 0))
            up_speed = format_speed(server_state.get("up_info_speed", 0))

            status = HealthStatus.DEGRADED if errored > 0 else HealthStatus.HEALTHY
            summary = f"{completed}/{total} completed ({active} active) • {dl_speed} ↓, {up_speed} ↑"

            branches = [
                (
                    f"📥 Torrents: [bold cyan]{completed:,}[/bold cyan]/[bold cyan]{total:,}[/bold cyan] completed "
                    f"[dim]([bold cyan]{active:,}[/bold cyan] active)[/dim]"
                ),
                f"⚡ Speeds: [bold green]{dl_speed} ↓[/bold green] [dim]•[/dim] [bold blue]{up_speed} ↑[/bold blue]",
            ]

            pref_res = await client.get("/api/v2/app/preferences")
            if pref_res.status_code == 200:
                prefs = pref_res.json()
                iface = str(prefs.get("current_network_interface", "")).strip()
                listen_port = prefs.get("listen_port", 0)
                upnp_enabled = bool(prefs.get("upnp", False))

                if iface in ("tun0", "wg0"):
                    branches.append(
                        f"🔒 Interface: [bold green]{iface}[/bold green] [dim]• Port: {listen_port}[/dim]"
                    )
                else:
                    status = HealthStatus.UNHEALTHY
                    branches.append(
                        f"⚠️ Interface: [bold red]{iface or 'ALL (UNBOUND)'}[/bold red] "
                        f"[dim](Critical: traffic not bound to VPN)[/dim]"
                    )

                if upnp_enabled:
                    if status == HealthStatus.HEALTHY:
                        status = HealthStatus.DEGRADED
                    branches.append(
                        "⚠️ UPnP: [bold yellow]ENABLED[/bold yellow] [dim](Should be disabled behind VPN)[/dim]"
                    )

            if errored > 0:
                branches.append(f"⚠️ Errored: [bold red]{errored}[/bold red] torrents")

            version = await ctx.get_container_version(container)

            return ServiceResult(
                service_id=service_id,
                name=name,
                container=container,
                status=status,
                latency_ms=elapsed,
                summary=summary,
                version=version,
                branches=branches,
                raw_data={"total": total, "completed": completed, "active": active, "errored": errored},
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
