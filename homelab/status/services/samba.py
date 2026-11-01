"""Samba file shares, user accounts, and port 445 connectivity health check."""

from __future__ import annotations

import socket
import time

import anyio

from ..models import HealthStatus, ServiceResult, StatusContext


def _check_port_445_sync(lan_host: str, timeout: float) -> None:
    with socket.create_connection((lan_host, 445), timeout=timeout):
        pass


async def check_samba(ctx: StatusContext) -> ServiceResult:
    service_id = "samba"
    name = "Samba File Server"
    container = "homelab-samba-1"
    t0 = time.perf_counter()

    try:
        # 1. TCP connection probe to port 445 (host network)
        await anyio.to_thread.run_sync(_check_port_445_sync, ctx.lan_host, ctx.http_timeout)

        # 2. Docker container inspection for shares, accounts, and sessions
        shares: list[str] = []
        accounts: list[str] = []
        active_sessions = 0

        code, out = await ctx.exec_container(container, "testparm -s")
        if code == 0:
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    sec = line[1:-1]
                    if sec != "global":
                        shares.append(sec)

        code, out = await ctx.exec_container(container, "pdbedit -L")
        if code == 0:
            for line in out.splitlines():
                if ":" in line:
                    accounts.append(line.split(":")[0])

        code, out = await ctx.exec_container(container, "smbstatus -b")
        if code == 0:
            for line in out.splitlines():
                line = line.strip()
                # Lines with PID numbers in the session table
                if line and line[0].isdigit():
                    active_sessions += 1

        elapsed = (time.perf_counter() - t0) * 1000

        shares.sort()
        accounts.sort()
        if active_sessions > 0:
            session_str = f"{active_sessions} active client session(s)"
        else:
            session_str = "0 active client sessions"

        shares_str = f"{len(shares)} shares ({', '.join(shares)})" if shares else "shares active"
        acc_str = f"accounts: {', '.join(accounts)}" if accounts else "auth ready"
        summary = f"{shares_str} • {acc_str} • port 445 open ({session_str})"

        branches = [
            f"📂 Shares: [dim]{', '.join(shares)}[/dim]",
            (
                f"👤 Accounts: [dim]{', '.join(accounts)}[/dim] [dim]•[/dim] "
                f"[bold white]Port 445[/bold white] open [dim]({session_str})[/dim]"
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
            raw_data={"shares": shares, "accounts": accounts, "active_sessions": active_sessions},
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
