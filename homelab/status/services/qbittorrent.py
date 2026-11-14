"""qBittorrent completed torrents, active counts, VPN binding, and deep health check."""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import anyio
import httpx
from rich.panel import Panel
from rich.table import Table

from common import format_bytes, format_connection_badge, format_route_line, render_command_header
from config import format_speed
from models import HealthStatus, ServiceResult, StatusContext, TargetConnection

if TYPE_CHECKING:
    from rich.console import Console


@dataclass(slots=True)
class QbittorrentCheckItem:
    name: str
    passed: bool
    details: str
    warning: bool = False


@dataclass(slots=True)
class TorrentCatalogSummary:
    total: int = 0
    completed: int = 0
    downloading: int = 0
    stalled: int = 0
    paused: int = 0
    errored: int = 0
    errored_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class QbittorrentServerState:
    dl_speed: int = 0
    up_speed: int = 0
    alltime_dl: int = 0
    alltime_ul: int = 0
    global_ratio: str = "0.0"
    dht_nodes: int = 0
    total_peers: int = 0
    free_space_bytes: int = 0
    last_external_ip: str = ""
    connection_status: str = "unknown"
    use_alt_speed_limits: bool = False
    queued_io_jobs: int = 0
    write_cache_overload: str = "0"


@dataclass(slots=True)
class QbittorrentPreferences:
    current_network_interface: str = ""
    listen_port: int = 0
    upnp: bool = False
    status_bar_external_ip: bool = False


@dataclass(slots=True)
class QbittorrentRawData:
    username: str = "username"
    container_found: bool = False
    container_status: str = "unknown"
    container_health: str = "unknown"
    restart_count: int = 0
    version: str | None = None
    api_auth_code: int = 0
    api_auth_error: str = ""
    preferences: dict[str, Any] = field(default_factory=dict)
    server_state: dict[str, Any] = field(default_factory=dict)
    torrents: dict[str, Any] = field(default_factory=dict)
    torrents_rw_code: int = -1
    torrents_rw_out: str = ""
    gluetun_forwarded_port: int = 0
    vpn_public_ip: str = ""
    host_public_ip: str = ""
    qui_found: bool = False
    qui_status: str = "unknown"
    qui_health: str = "unknown"
    base_domain: str = ""


@dataclass(slots=True)
class QbittorrentDeepReport:
    connection: TargetConnection | None = None
    version: str | None = None
    all_passed: bool = True
    checks: list[QbittorrentCheckItem] = field(default_factory=list)
    catalog: TorrentCatalogSummary = field(default_factory=TorrentCatalogSummary)
    server_state: QbittorrentServerState = field(default_factory=QbittorrentServerState)
    preferences: QbittorrentPreferences = field(default_factory=QbittorrentPreferences)
    raw_data: dict[str, Any] = field(default_factory=dict)


def summarize_torrent_catalog(torrents: dict[str, Any]) -> TorrentCatalogSummary:
    """Summarize torrent collection states and isolate errored items."""
    total = len(torrents)
    completed = 0
    downloading = 0
    stalled = 0
    paused = 0
    errored_names: list[str] = []

    for t in torrents.values():
        state = str(t.get("state", ""))
        progress = float(t.get("progress", 0.0))

        if state in ("error", "missingFiles"):
            errored_names.append(str(t.get("name", "Unknown")))

        if progress >= 1.0 or state in (
            "uploading",
            "stalledUP",
            "pausedUP",
            "queuedUP",
            "checkingUP",
            "forcedUP",
            "stoppedUP",
        ):
            completed += 1

        if state in ("downloading", "metaDL", "forcedDL", "queuedDL", "allocating", "checkingDL"):
            downloading += 1

        if state in ("stalledDL", "stalledUP"):
            stalled += 1

        if state in ("pausedDL", "pausedUP", "stoppedDL", "stoppedUP"):
            paused += 1

    return TorrentCatalogSummary(
        total=total,
        completed=completed,
        downloading=downloading,
        stalled=stalled,
        paused=paused,
        errored=len(errored_names),
        errored_names=errored_names,
    )


async def _fetch_host_public_ip(ctx: StatusContext) -> str:
    """Fetch the host egress IP (non-VPN) to verify zero IP leakage."""
    if not ctx.no_docker:
        for cname in ("homelab-caddy-1", "homelab-jellyfin-1"):
            code, out = await ctx.exec_container(cname, "wget -qO- -T 3 https://ipinfo.io/ip")
            if code == 0 and out.strip():
                return out.strip()

    with contextlib.suppress(httpx.HTTPError):
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.get("https://ipinfo.io/ip")
            if res.status_code == 200:
                return res.text.strip()
    return ""


async def _gather_qbittorrent_raw_data(ctx: StatusContext) -> QbittorrentRawData:
    """Collect Docker state, WebUI API data, storage rw status, and network endpoints."""
    base_domain = ctx.base_domain if hasattr(ctx, "base_domain") else ""
    raw = QbittorrentRawData(username=ctx.username, base_domain=base_domain)

    async def fetch_docker_state() -> None:
        c = await ctx.get_container("homelab-qbittorrent-1", full=True)
        if c:
            raw.container_found = True
            raw.container_status = getattr(c, "status", "unknown")
            health = getattr(c, "health", "none")
            raw.container_health = health or "none"
            raw.restart_count = getattr(c, "restart_count", 0)

        qui_c = await ctx.get_container("homelab-qui-1", full=True)
        if qui_c:
            raw.qui_found = True
            raw.qui_status = getattr(qui_c, "status", "unknown")
            qui_health = getattr(qui_c, "health", "none")
            raw.qui_health = qui_health or "none"

        raw.version = await ctx.get_container_version("homelab-qbittorrent-1")

    async def fetch_api_data() -> None:
        try:
            async with httpx.AsyncClient(base_url=ctx.base_url("qbittorrent"), timeout=ctx.http_timeout) as client:
                login_res = await client.post(
                    "/api/v2/auth/login",
                    data={"username": ctx.username, "password": ctx.password},
                )
                raw.api_auth_code = login_res.status_code
                if login_res.status_code not in (200, 204) or "Fails" in login_res.text:
                    raw.api_auth_error = login_res.text.strip()
                    return

                p_res = await client.get("/api/v2/app/preferences")
                if p_res.status_code == 200:
                    raw.preferences = p_res.json()

                m_res = await client.get("/api/v2/sync/maindata")
                if m_res.status_code == 200:
                    data = m_res.json()
                    raw.server_state = data.get("server_state", {})
                    raw.torrents = data.get("torrents", {})
        except Exception as exc:
            raw.api_auth_error = str(exc)

    async def fetch_storage_check() -> None:
        if not ctx.no_docker:
            code, out = await ctx.exec_container(
                "homelab-qbittorrent-1",
                "sh -c 'touch /mnt/mango/torrents/.status_check && rm -f /mnt/mango/torrents/.status_check'",
            )
            raw.torrents_rw_code = code
            raw.torrents_rw_out = out

    async def fetch_gluetun_details() -> None:
        if not ctx.no_docker:
            code, out = await ctx.exec_container("homelab-gluetun-1", "cat /tmp/gluetun/forwarded_port")
            if code == 0 and out.strip().isdigit():
                raw.gluetun_forwarded_port = int(out.strip())

            v_code, v_out = await ctx.exec_container("homelab-gluetun-1", "wget -qO- -T 3 https://ipinfo.io/ip")
            if v_code == 0 and v_out.strip():
                raw.vpn_public_ip = v_out.strip()

    async def fetch_host_ip() -> None:
        raw.host_public_ip = await _fetch_host_public_ip(ctx)

    async with anyio.create_task_group() as tg:
        tg.start_soon(fetch_docker_state)
        tg.start_soon(fetch_api_data)
        tg.start_soon(fetch_storage_check)
        tg.start_soon(fetch_gluetun_details)
        tg.start_soon(fetch_host_ip)

    return raw


def evaluate_qbittorrent_report(
    raw: QbittorrentRawData,
    connection: TargetConnection | None = None,
) -> QbittorrentDeepReport:
    """Evaluate raw qBittorrent telemetry into a structured diagnostic report."""
    report = QbittorrentDeepReport(
        connection=connection,
        version=raw.version,
    )

    # Parse preferences
    prefs = QbittorrentPreferences(
        current_network_interface=str(raw.preferences.get("current_network_interface", "")).strip(),
        listen_port=int(raw.preferences.get("listen_port", 0)),
        upnp=bool(raw.preferences.get("upnp", False)),
        status_bar_external_ip=bool(raw.preferences.get("status_bar_external_ip", False)),
    )
    report.preferences = prefs

    # Parse server state
    srv = raw.server_state
    state = QbittorrentServerState(
        dl_speed=int(srv.get("dl_info_speed", 0)),
        up_speed=int(srv.get("up_info_speed", 0)),
        alltime_dl=int(srv.get("alltime_dl", 0)),
        alltime_ul=int(srv.get("alltime_ul", 0)),
        global_ratio=str(srv.get("global_ratio", "0.0")),
        dht_nodes=int(srv.get("dht_nodes", 0)),
        total_peers=int(srv.get("total_peer_connections", 0)),
        free_space_bytes=int(srv.get("free_space_on_disk", 0)),
        last_external_ip=str(srv.get("last_external_address_v4", "")).strip(),
        connection_status=str(srv.get("connection_status", "unknown")),
        use_alt_speed_limits=bool(srv.get("use_alt_speed_limits", False)),
        queued_io_jobs=int(srv.get("queued_io_jobs", 0)),
        write_cache_overload=str(srv.get("write_cache_overload", "0")),
    )
    report.server_state = state

    # Parse catalog
    catalog = summarize_torrent_catalog(raw.torrents)
    report.catalog = catalog

    # 1. Inspection Route
    badge, endpoint, _ = format_connection_badge(connection)
    report.checks.append(
        QbittorrentCheckItem(
            name="Inspection Route",
            passed=True,
            details=f"Connected via {badge} [dim]({endpoint})[/dim]",
        )
    )

    # 2. Container Lifecycle
    if raw.container_found:
        is_running = raw.container_status == "running"
        h_str = f" • Health: '{raw.container_health}'" if raw.container_health != "none" else ""
        r_str = f" • {raw.restart_count} restarts" if raw.restart_count > 0 else ""
        report.checks.append(
            QbittorrentCheckItem(
                name="Container Lifecycle",
                passed=is_running,
                details=f"State: '{raw.container_status}'{h_str}{r_str}",
            )
        )
    else:
        report.checks.append(
            QbittorrentCheckItem(
                name="Container Lifecycle",
                passed=False,
                details="Container 'homelab-qbittorrent-1' not found",
            )
        )

    # 3. WebUI API Authentication
    if raw.api_auth_code in (200, 204) and "Fails" not in raw.api_auth_error:
        report.checks.append(
            QbittorrentCheckItem(
                name="WebUI API Authentication",
                passed=True,
                details=f"Authenticated as '{raw.username}' on WebUI port 8080",
            )
        )
    else:
        err = raw.api_auth_error or f"HTTP {raw.api_auth_code}"
        report.checks.append(
            QbittorrentCheckItem(
                name="WebUI API Authentication",
                passed=False,
                details=f"Authentication failed: {err}",
            )
        )

    # 4. VPN Interface Binding (Leak Guard)
    iface = prefs.current_network_interface
    is_tun = iface in ("tun0", "wg0")
    if is_tun:
        report.checks.append(
            QbittorrentCheckItem(
                name="VPN Interface Binding",
                passed=True,
                details=f"Strictly bound to '{iface}' (WireGuard VPN tunnel)",
            )
        )
    else:
        report.checks.append(
            QbittorrentCheckItem(
                name="VPN Interface Binding",
                passed=False,
                details=f"Unbound or wrong interface '{iface or 'ALL'}' (Critical leak hazard!)",
            )
        )

    # 5. UPnP Port Forwarding Safety
    if not prefs.upnp:
        report.checks.append(
            QbittorrentCheckItem(
                name="UPnP / NAT-PMP Safety",
                passed=True,
                details="Disabled (preventing local NAT traversal leaks outside tunnel)",
            )
        )
    else:
        report.checks.append(
            QbittorrentCheckItem(
                name="UPnP / NAT-PMP Safety",
                passed=False,
                warning=True,
                details="ENABLED (Should be disabled behind VPN to avoid port conflicts & leaks)",
            )
        )

    # 6. Listen Port & Port Forwarding Alignment
    listen_port = prefs.listen_port
    fwd_port = raw.gluetun_forwarded_port
    if fwd_port > 0:
        matches = listen_port == fwd_port
        report.checks.append(
            QbittorrentCheckItem(
                name="Listen Port Alignment",
                passed=matches,
                details=(
                    f"Port {listen_port} matches ProtonVPN forwarded port"
                    if matches
                    else f"Port mismatch: qBittorrent listening on {listen_port}, but Gluetun forwarded {fwd_port}"
                ),
            )
        )
    elif listen_port > 0:
        report.checks.append(
            QbittorrentCheckItem(
                name="Listen Port Alignment",
                passed=True,
                details=f"Listening on port {listen_port} (No active forwarded port file detected)",
            )
        )
    else:
        report.checks.append(
            QbittorrentCheckItem(
                name="Listen Port Alignment",
                passed=False,
                details="No listen port configured or API unavailable",
            )
        )

    # 7. External IP & Leak Verification
    qbt_ip = state.last_external_ip
    host_ip = raw.host_public_ip
    vpn_ip = raw.vpn_public_ip
    status_bar_desc = " • WebUI status bar display enabled" if prefs.status_bar_external_ip else ""

    if host_ip and qbt_ip and qbt_ip == host_ip:
        report.checks.append(
            QbittorrentCheckItem(
                name="External IP & Leak Guard",
                passed=False,
                details=f"CRITICAL LEAK: qBittorrent IP ({qbt_ip}) matches Host ISP IP!",
            )
        )
    elif vpn_ip and qbt_ip and qbt_ip != vpn_ip:
        report.checks.append(
            QbittorrentCheckItem(
                name="External IP & Leak Guard",
                passed=False,
                warning=True,
                details=f"External IP mismatch: qBittorrent sees {qbt_ip}, VPN gateway is {vpn_ip}",
            )
        )
    elif qbt_ip:
        report.checks.append(
            QbittorrentCheckItem(
                name="External IP & Leak Guard",
                passed=True,
                details=f"Egress verified: {qbt_ip} (ProtonVPN tunnel){status_bar_desc}",
            )
        )
    else:
        report.checks.append(
            QbittorrentCheckItem(
                name="External IP & Leak Guard",
                passed=True,
                warning=True,
                details="External IP not yet discovered by libtorrent DHT/STUN",
            )
        )

    # 8. Storage Mount & Free Disk Space
    if raw.torrents_rw_code == 0:
        free_bytes = state.free_space_bytes
        # 15 GB warning threshold
        is_low_space = 0 < free_bytes < (15 * 1024 * 1024 * 1024)
        space_str = f" • {format_bytes(free_bytes)} free on /dev/sda1" if free_bytes > 0 else ""
        report.checks.append(
            QbittorrentCheckItem(
                name="Storage Mount & Free Space",
                passed=not is_low_space,
                warning=is_low_space,
                details=(
                    f"/mnt/mango/torrents verified read-write (rw){space_str}"
                    if not is_low_space
                    else f"/mnt/mango/torrents rw • LOW DISK SPACE WARNING ({format_bytes(free_bytes)} remaining!)"
                ),
            )
        )
    elif raw.torrents_rw_code == -1:
        # Docker checks skipped (e.g. no-docker mode)
        space_str = f"Free space: {format_bytes(state.free_space_bytes)}" if state.free_space_bytes > 0 else "N/A"
        report.checks.append(
            QbittorrentCheckItem(
                name="Storage Mount & Free Space",
                passed=True,
                details=f"/mnt/mango/torrents (Docker exec skipped) • {space_str}",
            )
        )
    else:
        report.checks.append(
            QbittorrentCheckItem(
                name="Storage Mount & Free Space",
                passed=False,
                details=f"/mnt/mango/torrents mount unwritable or failed (exit code {raw.torrents_rw_code})",
            )
        )

    # 9. Torrent Catalog & Health
    if catalog.errored > 0:
        err_str = ", ".join(catalog.errored_names[:2])
        if len(catalog.errored_names) > 2:
            err_str += f" (+{len(catalog.errored_names) - 2} more)"
        report.checks.append(
            QbittorrentCheckItem(
                name="Torrent Catalog Health",
                passed=False,
                warning=True,
                details=f"{catalog.errored} errored / missing files torrents: {err_str}",
            )
        )
    elif catalog.total > 0:
        report.checks.append(
            QbittorrentCheckItem(
                name="Torrent Catalog Health",
                passed=True,
                details=(
                    f"{catalog.completed:,}/{catalog.total:,} completed "
                    f"({catalog.downloading} downloading, {catalog.stalled} stalled) • 0 errors"
                ),
            )
        )
    else:
        report.checks.append(
            QbittorrentCheckItem(
                name="Torrent Catalog Health",
                passed=True,
                details="Torrent catalog is empty (0 torrents loaded)",
            )
        )

    # 10. Swarm Connectivity & Speeds
    dl_s = format_speed(state.dl_speed)
    up_s = format_speed(state.up_speed)
    ratio = state.global_ratio
    swarm_details = (
        f"Speeds: {dl_s} ↓, {up_s} ↑ • Swarm: {state.dht_nodes} DHT nodes, "
        f"{state.total_peers} peers • Ratio: {ratio}"
    )
    report.checks.append(
        QbittorrentCheckItem(
            name="Swarm Speeds & Ratio",
            passed=True,
            details=swarm_details,
        )
    )

    # 11. Bandwidth Throttling / Turtle Mode
    if state.use_alt_speed_limits:
        report.checks.append(
            QbittorrentCheckItem(
                name="Bandwidth Throttling",
                passed=True,
                warning=True,
                details="Alternative speed limits (Turtle Mode 🐢) ACTIVE",
            )
        )
    else:
        report.checks.append(
            QbittorrentCheckItem(
                name="Bandwidth Throttling",
                passed=True,
                details="Turtle Mode inactive • Rate limits: Unlimited",
            )
        )

    # 12. Qui Companion Frontend
    if raw.qui_found:
        is_qui_ok = raw.qui_status == "running"
        h_str = f" ({raw.qui_health})" if raw.qui_health != "none" else ""
        qui_endpoint = f" (qui.{raw.base_domain})" if raw.base_domain else ""
        report.checks.append(
            QbittorrentCheckItem(
                name="Qui Web Companion",
                passed=is_qui_ok,
                details=f"Container 'homelab-qui-1' is {raw.qui_status}{h_str} on port 7476{qui_endpoint}",
            )
        )
    else:
        report.checks.append(
            QbittorrentCheckItem(
                name="Qui Web Companion",
                passed=True,
                warning=True,
                details="Container 'homelab-qui-1' not detected",
            )
        )

    report.all_passed = all(c.passed for c in report.checks if not c.warning)
    report.raw_data = {
        "catalog": {
            "total": catalog.total,
            "completed": catalog.completed,
            "downloading": catalog.downloading,
            "stalled": catalog.stalled,
            "paused": catalog.paused,
            "errored": catalog.errored,
            "errored_names": catalog.errored_names,
        },
        "server_state": {
            "dl_speed": state.dl_speed,
            "up_speed": state.up_speed,
            "alltime_dl": state.alltime_dl,
            "alltime_ul": state.alltime_ul,
            "global_ratio": state.global_ratio,
            "dht_nodes": state.dht_nodes,
            "total_peers": state.total_peers,
            "free_space_bytes": state.free_space_bytes,
            "last_external_ip": state.last_external_ip,
            "use_alt_speed_limits": state.use_alt_speed_limits,
        },
        "preferences": {
            "current_network_interface": prefs.current_network_interface,
            "listen_port": prefs.listen_port,
            "upnp": prefs.upnp,
            "status_bar_external_ip": prefs.status_bar_external_ip,
        },
    }
    return report


async def run_qbittorrent_deep_check(ctx: StatusContext) -> QbittorrentDeepReport:
    """Execute the full qBittorrent deep verification suite with concurrent I/O."""
    raw = await _gather_qbittorrent_raw_data(ctx)
    return evaluate_qbittorrent_report(raw, connection=ctx.connection)


def render_qbittorrent_deep_report(report: QbittorrentDeepReport, console: Console) -> None:
    """Render structured qBittorrent inspection results with Rich panels and table."""
    if report.connection:
        render_command_header(
            "📥 qBittorrent Client Deep Health Inspector",
            report.connection,
            console,
            border_style="magenta",
        )

    table = Table(title="📥 qBittorrent Health & Swarm Status", show_header=True, header_style="bold magenta")
    table.add_column("Check", style="bold", width=30)
    table.add_column("Status", width=10, justify="center")
    table.add_column("Details", style="dim")

    for check in report.checks:
        if check.passed:
            badge = "[bold green]PASS ✔[/bold green]"
        elif check.warning:
            badge = "[bold yellow]WARN ⚠[/bold yellow]"
        else:
            badge = "[bold red]FAIL ✖[/bold red]"
        table.add_row(check.name, badge, check.details)

    console.print()
    console.print(table)
    console.print()

    route_line = format_route_line(report.connection)
    cat = report.catalog
    srv = report.server_state
    pref = report.preferences

    dl_s = format_speed(srv.dl_speed)
    up_s = format_speed(srv.up_speed)
    free_str = format_bytes(srv.free_space_bytes) if srv.free_space_bytes > 0 else "N/A"
    alltime_dl = format_bytes(srv.alltime_dl) if srv.alltime_dl > 0 else "0 B"
    alltime_ul = format_bytes(srv.alltime_ul) if srv.alltime_ul > 0 else "0 B"

    if report.all_passed:
        egress_val = srv.last_external_ip or "Active"
        iface_val = pref.current_network_interface or "tun0"
        vpn_line = (
            f"• [bold]VPN Tunnel & Egress:[/bold] [bold cyan]{egress_val}[/bold cyan] "
            f"[dim](Bound to [bold cyan]{iface_val}[/bold cyan] • "
            f"Port [bold cyan]{pref.listen_port}[/bold cyan])[/dim]\n"
        )
        catalog_line = (
            f"• [bold]Torrents Active:[/bold] [bold cyan]{cat.completed:,}[/bold cyan] / "
            f"[bold cyan]{cat.total:,}[/bold cyan] completed "
            f"[dim]([bold cyan]{cat.downloading}[/bold cyan] dl, [bold cyan]{cat.stalled}[/bold cyan] stalled, "
            f"[bold cyan]{cat.errored}[/bold cyan] errored)[/dim]\n"
        )
        swarm_line = (
            f"• [bold]Swarm & Speeds:[/bold] "
            f"[bold green]{dl_s} ↓[/bold green] [dim]•[/dim] [bold blue]{up_s} ↑[/bold blue] "
            f"[dim]([bold cyan]{srv.dht_nodes}[/bold cyan] DHT, [bold cyan]{srv.total_peers}[/bold cyan] peers)[/dim]\n"
        )
        storage_line = (
            f"• [bold]Storage & Disk:[/bold] [bold cyan]{free_str}[/bold cyan] available on /dev/sda1 "
            f"[dim](Verified read-write rw)[/dim]\n"
        )
        ratio_line = (
            f"• [bold]All-Time Ratio:[/bold] [bold cyan]{srv.global_ratio}[/bold cyan] "
            f"[dim]({alltime_dl} downloaded, {alltime_ul} uploaded)[/dim]"
        )

        verdict = Panel(
            "[bold green]✔ ALL QBITTORRENT CHECKS PASSED & TUNNEL VERIFIED[/bold green]\n\n"
            f"{route_line}"
            f"{vpn_line}"
            f"{catalog_line}"
            f"{swarm_line}"
            f"{storage_line}"
            f"{ratio_line}",
            title="[bold green]Status: HEALTHY & BOUND[/bold green]",
            border_style="green",
        )
    else:
        failed = sum(1 for c in report.checks if not c.passed and not c.warning)
        verdict = Panel(
            f"[bold red]✖ {failed} CRITICAL CHECK(S) FAILED[/bold red]\n\n"
            f"{route_line}"
            "Review the table above for VPN interface binding, port alignment, or storage rw permissions.",
            title="[bold red]Status: DEGRADED / UNHEALTHY[/bold red]",
            border_style="red",
        )

    console.print(verdict)

    if cat.errored_names:
        err_list = "\n".join(f"• [bold red]{name}[/bold red]" for name in cat.errored_names)
        err_panel = Panel(
            err_list,
            title=f"[bold red]⚠️ {len(cat.errored_names)} Errored / Missing Files Torrent(s)[/bold red]",
            border_style="red",
        )
        console.print(err_panel)


async def check_qbittorrent(ctx: StatusContext) -> ServiceResult:
    """Standard service tree check for qBittorrent."""
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

            catalog = summarize_torrent_catalog(torrents)
            total = catalog.total
            completed = catalog.completed
            active = catalog.downloading
            errored = catalog.errored

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
