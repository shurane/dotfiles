"""Caddy reverse proxy routes and TLS certificate health check."""

from __future__ import annotations

import datetime
import json
import socket
import ssl
import time
from typing import Any

import anyio
import httpx

from ..models import HealthStatus, ServiceResult, StatusContext


def _check_tls_sync(base_domain: str, timeout: float) -> tuple[dict[str, str], int]:
    """Perform synchronous TLS handshake to inspect peer certificate."""
    ssl_ctx = ssl.create_default_context()
    with (
        socket.create_connection((base_domain, 443), timeout=timeout) as sock,
        ssl_ctx.wrap_socket(sock, server_hostname=base_domain) as ssock,
    ):
        cert = ssock.getpeercert()
        issuer = dict(x[0] for x in cert.get("issuer", []))
        issuer_org = issuer.get("organizationName") or issuer.get("commonName") or "Valid TLS"
        not_after = cert.get("notAfter", "")
        days_left = 999
        try:
            dt = datetime.datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=datetime.UTC)
            expires_str = dt.strftime("%b %d %Y")
            days_left = (dt - datetime.datetime.now(datetime.UTC)).days
        except Exception:
            expires_str = not_after

        return {"issuer": issuer_org, "expires": expires_str}, days_left


async def check_caddy(ctx: StatusContext) -> ServiceResult:
    service_id = "caddy"
    name = "Caddy Ingress"
    container = "homelab-caddy-1"
    t0 = time.perf_counter()

    try:
        cert_info: dict[str, str] = {}
        days_left = 999
        probe_code = 200
        routes_list: list[str] = []

        async def _check_tls() -> None:
            nonlocal cert_info, days_left
            cert_info, days_left = await anyio.to_thread.run_sync(_check_tls_sync, ctx.base_domain, ctx.http_timeout)

        async def _probe_http() -> None:
            nonlocal probe_code
            try:
                async with httpx.AsyncClient(base_url=f"https://{ctx.base_domain}", timeout=ctx.http_timeout) as client:
                    probe = await client.get("/")
                    probe_code = probe.status_code
            except Exception:
                probe_code = 502

        async def _read_routes() -> None:
            nonlocal routes_list
            code, out = await ctx.exec_container(container, "cat /config/caddy/autosave.json")
            if code == 0:
                try:
                    cfg: dict[str, Any] = json.loads(out)
                    srv_routes = (
                        cfg.get("apps", {}).get("http", {}).get("servers", {}).get("srv0", {}).get("routes", [])
                    )
                    hosts = {h for r in srv_routes for m in r.get("match", []) for h in m.get("host", [])}
                    routes_list = sorted(hosts)
                except Exception:
                    pass

        # Execute TLS, HTTP probe, and autosave read concurrently
        async with anyio.create_task_group() as tg:
            tg.start_soon(_check_tls)
            tg.start_soon(_probe_http)
            tg.start_soon(_read_routes)

        elapsed = (time.perf_counter() - t0) * 1000

        if probe_code >= 500:
            return ServiceResult(
                service_id=service_id,
                name=name,
                container=container,
                status=HealthStatus.UNHEALTHY,
                latency_ms=elapsed,
                summary=f"Root ingress route returned HTTP {probe_code}",
                branches=[f"[bold red]✖ Root ingress returned HTTP {probe_code}[/bold red]"],
            )

        short_routes = [h.replace(f".{ctx.base_domain}", "") if h != ctx.base_domain else h for h in routes_list]
        routes_str = f"{len(routes_list)} routes ({', '.join(short_routes)})" if routes_list else "Ingress active"
        tls_summary = f"TLS: {cert_info.get('issuer')} (valid to {cert_info.get('expires')})"
        summary = f"{routes_str} • {tls_summary}"

        status = HealthStatus.HEALTHY
        if days_left <= 0:
            status = HealthStatus.UNHEALTHY
            days_style = "bold red"
        elif days_left <= 14:
            status = HealthStatus.DEGRADED
            days_style = "bold red"
        elif days_left <= 30:
            status = HealthStatus.HEALTHY
            days_style = "bold yellow"
        else:
            status = HealthStatus.HEALTHY
            days_style = "bold green"

        styled_routes = [f"[bold cyan]{r}[/bold cyan]" for r in short_routes]
        branches = [
            (f"🌐 Reverse Proxy: [bold cyan]{len(routes_list)}[/bold cyan] routes ({', '.join(styled_routes)})"),
            (
                f"🔒 TLS Certificate: [bold yellow]{cert_info.get('issuer')}[/bold yellow] "
                f"[dim]•[/dim] valid to [bold white]{cert_info.get('expires')}[/bold white] "
                f"[dim]([{days_style}]{days_left}d remaining[/{days_style}])[/dim]"
            ),
        ]

        return ServiceResult(
            service_id=service_id,
            name=name,
            container=container,
            status=status,
            latency_ms=elapsed,
            summary=summary,
            branches=branches,
            raw_data={"routes": routes_list, "cert": cert_info, "days_left": days_left},
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
