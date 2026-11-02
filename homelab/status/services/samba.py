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
        active_sessions = 0
        port_open = False

        async def _check_port() -> None:
            nonlocal port_open
            await anyio.to_thread.run_sync(_check_port_445_sync, ctx.lan_host, ctx.http_timeout)
            port_open = True

        async def _check_container() -> None:
            nonlocal shares, accounts, active_sessions
            cmd = (
                "sh -c \"testparm -s 2>/dev/null; echo '===SMB_DELIM==='; "
                "pdbedit -L 2>/dev/null; echo '===SMB_DELIM==='; "
                'smbstatus -b 2>/dev/null"'
            )
            code, out = await ctx.exec_container(container, cmd)
            if code == 0:
                parts = out.split("===SMB_DELIM===")
                if len(parts) >= 1:
                    for line in parts[0].splitlines():
                        line = line.strip()
                        if line.startswith("[") and line.endswith("]"):
                            sec = line[1:-1]
                            if sec != "global":
                                shares.append(sec)
                if len(parts) >= 2:
                    for line in parts[1].splitlines():
                        if ":" in line:
                            accounts.append(line.split(":")[0])
                if len(parts) >= 3:
                    for line in parts[2].splitlines():
                        line = line.strip()
                        if line and line[0].isdigit():
                            active_sessions += 1

        # Probe port 445 and inspect container concurrently
        async with anyio.create_task_group() as tg:
            tg.start_soon(_check_port)
            tg.start_soon(_check_container)

        elapsed = (time.perf_counter() - t0) * 1000

        shares.sort()
        accounts.sort()
        session_str = (
            f"[bold cyan]{active_sessions}[/bold cyan] active client session(s)"
            if active_sessions > 0
            else "[dim]0 active client sessions[/dim]"
        )

        styled_shares = [f"[bold magenta]{s}[/bold magenta]" for s in shares]
        styled_accounts = [f"[bold yellow]{a}[/bold yellow]" for a in accounts]

        shares_str = f"{len(shares)} shares ({', '.join(shares)})" if shares else "shares active"
        acc_str = f"accounts: {', '.join(accounts)}" if accounts else "auth ready"
        summary = f"{shares_str} • {acc_str} • port 445 open ({active_sessions} sessions)"

        branches = [
            f"📂 Shares: [bold cyan]{len(shares)}[/bold cyan] ({', '.join(styled_shares)})",
            (
                f"👤 Accounts: {', '.join(styled_accounts)} [dim]•[/dim] "
                f"[bold green]Port 445[/bold green] open [dim]({session_str})[/dim]"
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
