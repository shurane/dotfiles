"""Samba file shares, user accounts, and port 445 connectivity health check."""

from __future__ import annotations

import socket
import time

import anyio

from models import HealthStatus, ServiceResult, StatusContext


def _check_port_445_sync(lan_host: str, timeout: float) -> None:
    with socket.create_connection((lan_host, 445), timeout=timeout):
        pass


async def check_samba(ctx: StatusContext) -> ServiceResult:
    service_id = "samba"
    name = "Samba File Server"
    container = "homelab-samba-1"
    t0 = time.perf_counter()

    try:
        shares: list[str] = []
        accounts: list[str] = []
        port_open = False

        async def _check_port() -> None:
            nonlocal port_open
            await anyio.to_thread.run_sync(_check_port_445_sync, ctx.lan_host, ctx.http_timeout)
            port_open = True

        async def _inspect_metadata() -> None:
            nonlocal shares, accounts
            c = await ctx.get_container(container)
            if not c:
                return
            attrs = c.attrs or {}
            config = attrs.get("Config") or {}
            env = config.get("Env") or []
            for e in env:
                if isinstance(e, str) and "=" in e:
                    k, _ = e.split("=", 1)
                    if k.startswith("SAMBA_VOLUME_CONFIG_"):
                        sec = k.removeprefix("SAMBA_VOLUME_CONFIG_")
                        if sec:
                            shares.append(sec)
                    elif k.startswith("ACCOUNT_"):
                        acc = k.removeprefix("ACCOUNT_")
                        if acc:
                            accounts.append(acc)

        # Probe port 445 and inspect container metadata concurrently
        async with anyio.create_task_group() as tg:
            tg.start_soon(_check_port)
            tg.start_soon(_inspect_metadata)

        elapsed = (time.perf_counter() - t0) * 1000

        shares.sort()
        accounts.sort()

        styled_shares = [f"[bold magenta]{s}[/bold magenta]" for s in shares]
        styled_accounts = [f"[bold yellow]{a}[/bold yellow]" for a in accounts]

        shares_str = f"{len(shares)} shares ({', '.join(shares)})" if shares else "shares active"
        acc_str = f"accounts: {', '.join(accounts)}" if accounts else "auth ready"
        summary = f"{shares_str} • {acc_str} • port 445 open"

        branches = [
            f"📂 Shares: [bold cyan]{len(shares)}[/bold cyan] ({', '.join(styled_shares)})",
            (
                f"👤 Accounts: {', '.join(styled_accounts)} [dim]•[/dim] "
                f"[bold green]Port 445[/bold green] open [dim](accepting connections)[/dim]"
            ),
        ]

        version = await ctx.get_container_version(container)

        return ServiceResult(
            service_id=service_id,
            name=name,
            container=container,
            status=HealthStatus.HEALTHY,
            latency_ms=elapsed,
            summary=summary,
            version=version,
            branches=branches,
            raw_data={"shares": shares, "accounts": accounts, "port_open": port_open},
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
