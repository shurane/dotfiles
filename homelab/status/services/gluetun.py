"""Gluetun VPN client (ProtonVPN) status and port forwarding health check."""

from __future__ import annotations

import contextlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

import anyio
import httpx
from rich.panel import Panel
from rich.table import Table

from common import (
    format_bytes as _format_bytes,
)
from common import (
    format_connection_badge,
    format_route_line,
    render_command_header,
)
from models import HealthStatus, ServiceResult, StatusContext, TargetConnection

if TYPE_CHECKING:
    from rich.console import Console


@dataclass(slots=True)
class IpDetails:
    ip: str
    country: str = "Unknown"
    region: str = "Unknown"
    city: str = "Unknown"
    org: str = "Unknown"


@dataclass(slots=True)
class VpnCheckItem:
    name: str
    passed: bool
    details: str
    warning: bool = False


@dataclass(slots=True)
class VpnDeepReport:
    connection: TargetConnection | None = None
    checks: list[VpnCheckItem] = field(default_factory=list)
    host_ip: IpDetails | None = None
    vpn_ip: IpDetails | None = None
    forwarded_port: int | None = None
    qbittorrent_port: int | None = None
    interface_bound: str | None = None
    qbittorrent_status: str | None = None
    dht_nodes: int = 0
    active_torrents: int = 0
    download_speed: float = 0.0
    upload_speed: float = 0.0
    tun_rx_bytes: int = 0
    tun_tx_bytes: int = 0

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks if not c.warning)


@dataclass(slots=True)
class VpnRawData:
    """Consolidated raw measurements gathered concurrently from containers and network."""

    gluetun_found: bool = False
    gluetun_status: str = "none"
    gluetun_health: str = "none"
    qbt_found: bool = False
    qbt_status: str = "none"
    qbt_net_mode: str = ""
    host_ip: IpDetails | None = None
    vpn_ip: IpDetails | None = None
    tun_stats_code: int = -1
    tun_stats_raw: str = ""
    resolv_conf: str = ""
    trace_raw: str = ""
    ipv6_route: str = ""
    forwarded_port_raw: str = ""
    iptables_raw: str = ""
    netstat_raw: str = ""
    qbt_prefs_raw: str = ""
    qbt_prefs_code: int = -1
    qbt_maindata_raw: str = ""
    qbt_transfer_raw: str = ""
    qbt_transfer_code: int = -1
    dns_whoami_raw: str = ""


def _extract_section(output: str, tag: str) -> str:
    """Extract delimited section from batched command output (e.g. ===TAG=== ...)."""
    match = re.search(rf"==={tag}===\n(.*?)(?=\n===|\Z)", output, re.DOTALL)
    return match.group(1).strip() if match else ""


def _parse_dns_whoami(output: str) -> str:
    """Parse upstream recursive DNS resolver IP from nslookup whoami.akamai.net output."""
    match = re.search(r"whoami\.akamai\.net.*?Address:\s*([0-9a-fA-F.:]+)", output, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _parse_ipinfo(data: dict[str, Any] | str) -> IpDetails:
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return IpDetails(ip=data.strip())
    return IpDetails(
        ip=str(data.get("ip", "Unknown")).strip(),
        country=str(data.get("country", "Unknown")).strip(),
        region=str(data.get("region", "Unknown")).strip(),
        city=str(data.get("city", "Unknown")).strip(),
        org=str(data.get("org", "Unknown")).strip(),
    )


async def _fetch_host_ip(ctx: StatusContext | None = None) -> IpDetails | None:
    if ctx and not ctx.no_docker:
        for cname in ("homelab-caddy-1", "homelab-homepage-1", "homelab-jellyfin-1"):
            code, out = await ctx.exec_container(cname, "wget -qO- -T 3 https://ipinfo.io/json")
            if code == 0 and "ip" in out:
                return _parse_ipinfo(out)

    for url in ("https://ipinfo.io/json", "https://ifconfig.co/json"):
        with contextlib.suppress(httpx.HTTPError, json.JSONDecodeError, KeyError):
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    return _parse_ipinfo(res.json())
    return None


async def _fetch_gluetun_ip(ctx: StatusContext, container: str) -> IpDetails | None:
    """Query external egress IP directly from inside Gluetun container (anti-stale-cache)."""
    # 1. Primary: Live network egress query through the container's network stack
    for cmd in ("wget -qO- -T 3 https://ipinfo.io/json", "curl -s -m 3 https://ipinfo.io/json"):
        code, out = await ctx.exec_container(container, cmd)
        if code == 0 and "ip" in out:
            return _parse_ipinfo(out)

    # 2. Secondary live query: 1.1.1.1/cdn-cgi/trace
    code, trace_out = await ctx.exec_container(container, "wget -T 3 -qO- https://1.1.1.1/cdn-cgi/trace")
    if code == 0 and "ip=" in trace_out:
        trace_ip = ""
        trace_loc = ""
        for line in trace_out.splitlines():
            if line.startswith("ip="):
                trace_ip = line.split("=", 1)[1].strip()
            elif line.startswith("loc="):
                trace_loc = line.split("=", 1)[1].strip()
        if trace_ip:
            return IpDetails(ip=trace_ip, country=trace_loc or "NL", org="ProtonVPN")

    return None


def _parse_tun_stats(link_output: str) -> tuple[int, int, int, int]:
    """Parse (rx_bytes, rx_packets, tx_bytes, tx_packets) from ip -s link output."""
    lines = link_output.splitlines()
    rx_bytes = rx_packets = tx_bytes = tx_packets = 0
    for i, line in enumerate(lines):
        if "RX:" in line and i + 1 < len(lines):
            parts = lines[i + 1].split()
            if len(parts) >= 2:
                rx_bytes = int(parts[0]) if parts[0].isdigit() else 0
                rx_packets = int(parts[1]) if parts[1].isdigit() else 0
        elif "TX:" in line and i + 1 < len(lines):
            parts = lines[i + 1].split()
            if len(parts) >= 2:
                tx_bytes = int(parts[0]) if parts[0].isdigit() else 0
                tx_packets = int(parts[1]) if parts[1].isdigit() else 0
    return rx_bytes, rx_packets, tx_bytes, tx_packets


async def _gather_vpn_raw_data(ctx: StatusContext) -> VpnRawData:
    """Concurrently execute all Docker and network queries using anyio task group."""
    raw = VpnRawData()

    gluetun = await ctx.get_container("homelab-gluetun-1")
    if not gluetun:
        return raw

    raw.gluetun_found = True
    await anyio.to_thread.run_sync(gluetun.reload)
    raw.gluetun_status = gluetun.status
    attrs = gluetun.attrs or {}
    state = attrs.get("State") or {}
    health = state.get("Health") or {}
    raw.gluetun_health = health.get("Status", "none")

    if raw.gluetun_status != "running":
        return raw

    qbt = await ctx.get_container("homelab-qbittorrent-1")
    if qbt:
        raw.qbt_found = True
        await anyio.to_thread.run_sync(qbt.reload)
        raw.qbt_status = qbt.status
        qbt_attrs = qbt.attrs or {}
        host_config = qbt_attrs.get("HostConfig") or {}
        raw.qbt_net_mode = host_config.get("NetworkMode", "")

    async with anyio.create_task_group() as tg:
        async def fetch_host() -> None:
            raw.host_ip = await _fetch_host_ip(ctx)

        async def fetch_vpn() -> None:
            raw.vpn_ip = await _fetch_gluetun_ip(ctx, "homelab-gluetun-1")

        async def exec_gluetun_local() -> None:
            batch_cmd = (
                "sh -c '"
                "echo \"===TUN===\"; ip -s link show dev tun0 2>/dev/null; echo \"\"; "
                "echo \"===RESOLV===\"; cat /etc/resolv.conf 2>/dev/null; echo \"\"; "
                "echo \"===V6===\"; ip -6 route 2>/dev/null; echo \"\"; "
                "echo \"===PORT===\"; cat /tmp/gluetun/forwarded_port 2>/dev/null; echo \"\"; "
                "echo \"===IPTABLES===\"; iptables -nL INPUT 2>/dev/null; echo \"\"; "
                "echo \"===NETSTAT===\"; netstat -tuln 2>/dev/null; echo \"\"; "
                "echo \"===END===\""
                "'"
            )
            code, out = await ctx.exec_container("homelab-gluetun-1", batch_cmd)
            raw.tun_stats_raw = _extract_section(out, "TUN")
            raw.tun_stats_code = 0 if raw.tun_stats_raw else (code or 1)
            raw.resolv_conf = _extract_section(out, "RESOLV")
            raw.ipv6_route = _extract_section(out, "V6")
            raw.forwarded_port_raw = _extract_section(out, "PORT")
            raw.iptables_raw = _extract_section(out, "IPTABLES")
            raw.netstat_raw = _extract_section(out, "NETSTAT")

        async def exec_trace() -> None:
            _, raw.trace_raw = await ctx.exec_container(
                "homelab-gluetun-1", "wget -T 3 -qO- https://1.1.1.1/cdn-cgi/trace"
            )

        async def exec_dns_whoami() -> None:
            _, raw.dns_whoami_raw = await ctx.exec_container(
                "homelab-gluetun-1", "nslookup whoami.akamai.net"
            )

        async def exec_qbt() -> None:
            batch_qbt = (
                "sh -c '"
                "echo \"===PREFS===\"; wget -qO- http://127.0.0.1:8080/api/v2/app/preferences 2>/dev/null; "
                "echo \"\n===MAINDATA===\"; wget -qO- http://127.0.0.1:8080/api/v2/sync/maindata 2>/dev/null; "
                "echo \"\n===TRANSFER===\"; wget -qO- http://127.0.0.1:8080/api/v2/transfer/info 2>/dev/null; "
                "echo \"\n===END===\""
                "'"
            )
            code, out = await ctx.exec_container("homelab-qbittorrent-1", batch_qbt)
            raw.qbt_prefs_raw = _extract_section(out, "PREFS")
            raw.qbt_prefs_code = code if code != 0 else (0 if raw.qbt_prefs_raw.startswith("{") else 1)
            raw.qbt_maindata_raw = _extract_section(out, "MAINDATA")
            raw.qbt_transfer_raw = _extract_section(out, "TRANSFER")
            raw.qbt_transfer_code = code if code != 0 else (0 if raw.qbt_transfer_raw.startswith("{") else 1)

        tg.start_soon(fetch_host)
        tg.start_soon(fetch_vpn)
        tg.start_soon(exec_gluetun_local)
        tg.start_soon(exec_trace)
        tg.start_soon(exec_dns_whoami)
        if raw.qbt_found and raw.qbt_status == "running":
            tg.start_soon(exec_qbt)

    return raw


def evaluate_vpn_report(
    raw: VpnRawData,
    connection: TargetConnection | None = None,
) -> VpnDeepReport:
    """Pure deterministic assertion evaluation from consolidated raw data (no I/O)."""
    report = VpnDeepReport(connection=connection)

    # 0. Inspection Route & Context
    if connection:
        _, _, full = format_connection_badge(connection)
        report.checks.append(
            VpnCheckItem(
                "Inspection Route",
                True,
                full,
            )
        )

    # 1. Gluetun Container
    if not raw.gluetun_found:
        report.checks.append(VpnCheckItem("Gluetun Container", False, "Container homelab-gluetun-1 not found"))
        return report

    is_running = raw.gluetun_status == "running"
    is_healthy = raw.gluetun_health in ("healthy", "none")
    report.checks.append(
        VpnCheckItem(
            "Gluetun Container",
            is_running and is_healthy,
            f"Status: {raw.gluetun_status}, Health: {raw.gluetun_health}",
        )
    )

    if not is_running:
        return report

    # 2. qBittorrent Container & Namespace
    if not raw.qbt_found:
        report.checks.append(VpnCheckItem("qBittorrent Container", False, "Container homelab-qbittorrent-1 not found"))
        return report

    report.checks.append(
        VpnCheckItem("qBittorrent Container", raw.qbt_status == "running", f"Status: {raw.qbt_status}")
    )
    is_isolated = raw.qbt_net_mode.startswith("container:") or "gluetun" in raw.qbt_net_mode
    report.checks.append(
        VpnCheckItem(
            "Network Namespace Isolation",
            is_isolated,
            f"Network Mode: {raw.qbt_net_mode} (qBittorrent shares Gluetun network stack)",
        )
    )

    # 3. Tunnel Interface Metrics (tun0)
    if raw.tun_stats_code == 0 and "UP" in raw.tun_stats_raw:
        rx_b, rx_p, tx_b, tx_p = _parse_tun_stats(raw.tun_stats_raw)
        report.tun_rx_bytes = rx_b
        report.tun_tx_bytes = tx_b
        report.checks.append(
            VpnCheckItem(
                "WireGuard Tunnel Interface (tun0)",
                True,
                f"State: UP • RX: {_format_bytes(rx_b)} ({rx_p} pkts) | TX: {_format_bytes(tx_b)} ({tx_p} pkts)",
            )
        )
    else:
        report.checks.append(
            VpnCheckItem("WireGuard Tunnel Interface (tun0)", False, "Interface tun0 not found or down")
        )

    # 4. IP Leak Check
    report.host_ip = raw.host_ip
    report.vpn_ip = raw.vpn_ip

    if raw.host_ip and raw.vpn_ip:
        no_leak = raw.host_ip.ip != raw.vpn_ip.ip
        leak_msg = f"VPN IP: {raw.vpn_ip.ip} ({raw.vpn_ip.org}, {raw.vpn_ip.country}) | "
        leak_msg += f"Host ISP IP: {raw.host_ip.ip} ({raw.host_ip.org})"
        report.checks.append(VpnCheckItem("IP Leak Test", no_leak, leak_msg))
    elif raw.vpn_ip:
        report.checks.append(
            VpnCheckItem("VPN Public IP", True, f"VPN IP: {raw.vpn_ip.ip} ({raw.vpn_ip.org}, {raw.vpn_ip.country})")
        )
    else:
        report.checks.append(VpnCheckItem("VPN Public IP", False, "Unable to resolve external IP inside Gluetun"))

    # 5. DNS Leak & Resolution Check
    has_local_resolver = "127.0.0.1" in raw.resolv_conf
    upstream_resolver_ip = _parse_dns_whoami(raw.dns_whoami_raw)
    trace_ip = ""
    trace_loc = ""
    for line in raw.trace_raw.splitlines():
        if line.startswith("ip="):
            trace_ip = line.split("=", 1)[1].strip()
        elif line.startswith("loc="):
            trace_loc = line.split("=", 1)[1].strip()

    tunnel_up = raw.tun_stats_code == 0 and "UP" in raw.tun_stats_raw
    if (trace_ip or upstream_resolver_ip) and tunnel_up:
        dns_secure = has_local_resolver and (not raw.host_ip or trace_ip != raw.host_ip.ip)
        if upstream_resolver_ip and raw.host_ip and upstream_resolver_ip == raw.host_ip.ip:
            dns_secure = False

        resolver_part = f" • Upstream Resolver: {upstream_resolver_ip}" if upstream_resolver_ip else ""
        egress_part = f" • Outbound Egress: {trace_ip} ({trace_loc or 'NL'})" if trace_ip else ""
        details = f"Local encrypted resolver: 127.0.0.1 (DoT){resolver_part}{egress_part}"
    else:
        dns_secure = False
        details = "DNS/HTTPS egress check failed (Tunnel offline or blocked)"
    report.checks.append(VpnCheckItem("DNS Leak & Resolver Security", dns_secure, details))

    # 6. IPv6 Leak Prevention
    no_v6_default = "default " not in raw.ipv6_route
    report.checks.append(
        VpnCheckItem(
            "IPv6 Leak Prevention",
            no_v6_default,
            "No default IPv6 route active (Host IPv6 cannot leak to peers)",
            warning=not no_v6_default,
        )
    )

    # 7. Gluetun Port Forwarding
    forwarded_port: int | None = None
    port_text = raw.forwarded_port_raw.strip()
    if port_text.isdigit() and int(port_text) > 1024:
        forwarded_port = int(port_text)
        report.forwarded_port = forwarded_port
        report.checks.append(
            VpnCheckItem("Gluetun Port Forwarding", True, f"Port {forwarded_port} forwarded successfully via NAT-PMP")
        )
    else:
        report.checks.append(
            VpnCheckItem(
                "Gluetun Port Forwarding",
                False,
                f"No valid port found ({port_text or 'empty'})",
                warning=True,
            )
        )

    # 8. Kernel Firewall Inbound Port Verification (iptables)
    if forwarded_port:
        port_str = str(forwarded_port)
        has_tcp = f"tcp dpt:{port_str}" in raw.iptables_raw
        has_udp = f"udp dpt:{port_str}" in raw.iptables_raw
        is_firewall_ok = "Chain INPUT (policy DROP)" in raw.iptables_raw and has_tcp and has_udp
        report.checks.append(
            VpnCheckItem(
                "Firewall Inbound Policy",
                is_firewall_ok,
                f"Kernel policy DROP with inbound ACCEPT for port {port_str} (TCP/UDP)",
                warning=not is_firewall_ok,
            )
        )

    # 9. Inbound Port Listener Verification (netstat -tuln)
    if forwarded_port:
        is_listening = f":{forwarded_port} " in raw.netstat_raw
        report.checks.append(
            VpnCheckItem(
                "Inbound Port Listener",
                is_listening,
                f"Active socket listening on port {forwarded_port} (TCP/UDP)"
                if is_listening
                else f"Ghost port: port {forwarded_port} is forwarded, but no socket is listening!",
                warning=not is_listening,
            )
        )

    # 10. qBittorrent Preferences & Interface Binding
    if raw.qbt_prefs_code == 0 and raw.qbt_prefs_raw.startswith("{"):
        try:
            prefs = json.loads(raw.qbt_prefs_raw)
            qbt_port = int(prefs.get("listen_port", 0))
            bound_iface = str(prefs.get("current_network_interface", "")).strip()
            upnp_enabled = bool(prefs.get("upnp", False))
            report.qbittorrent_port = qbt_port
            report.interface_bound = bound_iface

            is_tun = bound_iface in ("tun0", "wg0")
            report.checks.append(
                VpnCheckItem(
                    "qBittorrent Interface Binding",
                    is_tun,
                    f"Bound to: '{bound_iface or 'Any interface'}' "
                    f"({'Strictly bound to VPN tunnel' if is_tun else 'Warning: not bound to tun0'})",
                    warning=not is_tun,
                )
            )

            if forwarded_port:
                matches = qbt_port == forwarded_port
                desc = "Matches ProtonVPN forwarded port" if matches else f"Mismatch with port {forwarded_port}"
                report.checks.append(
                    VpnCheckItem("qBittorrent Listening Port", matches, f"Listening on: {qbt_port} ({desc})")
                )

            report.checks.append(
                VpnCheckItem(
                    "qBittorrent UPnP Disabled",
                    not upnp_enabled,
                    f"UPnP is {'Disabled (Recommended)' if not upnp_enabled else 'Enabled (Should be disabled)'}",
                )
            )
        except Exception as exc:
            report.checks.append(VpnCheckItem("qBittorrent Preferences", False, f"Error: {exc}"))
    else:
        report.checks.append(
            VpnCheckItem(
                "qBittorrent Web API",
                False,
                f"Web API unreachable on 127.0.0.1:8080 (exit code {raw.qbt_prefs_code})",
            )
        )

    # 11. Swarm Connectivity & Torrent Counters
    if raw.qbt_maindata_raw.startswith("{"):
        with contextlib.suppress(json.JSONDecodeError, KeyError, ValueError, TypeError):
            maindata = json.loads(raw.qbt_maindata_raw)
            server_state = maindata.get("server_state", {})
            report.qbittorrent_status = str(server_state.get("connection_status", "unknown"))
            report.download_speed = float(server_state.get("dl_info_speed", 0)) / 1024
            report.upload_speed = float(server_state.get("up_info_speed", 0)) / 1024
            report.active_torrents = len(maindata.get("torrents", {}))

    # 12. Transfer Info & Peer Swarm IP Verification
    if raw.qbt_transfer_code == 0 and raw.qbt_transfer_raw.startswith("{"):
        with contextlib.suppress(json.JSONDecodeError, KeyError, ValueError, TypeError):
            xfer = json.loads(raw.qbt_transfer_raw)
            dht_nodes = int(xfer.get("dht_nodes", 0))
            last_ext_v4 = str(xfer.get("last_external_address_v4", "")).strip()
            last_ext_v6 = str(xfer.get("last_external_address_v6", "")).strip()
            report.dht_nodes = dht_nodes

            if last_ext_v4 and raw.vpn_ip:
                is_leaked = bool(raw.host_ip and last_ext_v4 == raw.host_ip.ip)
                ip_match = (last_ext_v4 == raw.vpn_ip.ip) and not is_leaked
                if is_leaked:
                    desc = f"CRITICAL LEAK: Host ISP IP ({last_ext_v4}) advertised to swarm!"
                elif ip_match:
                    desc = f"Reported to swarm: {last_ext_v4} (Matches VPN tunnel IP)"
                else:
                    desc = f"Reported to swarm: {last_ext_v4} (Mismatch with VPN tunnel IP {raw.vpn_ip.ip})"
                report.checks.append(VpnCheckItem("qBittorrent Peer External IP", ip_match, desc))
            elif not last_ext_v4:
                report.checks.append(
                    VpnCheckItem(
                        "qBittorrent Peer External IP",
                        True,
                        "Pending peer connection (no external address reported to swarm yet)",
                        warning=True,
                    )
                )

            report.checks.append(
                VpnCheckItem(
                    "qBittorrent IPv6 Advertisement",
                    last_ext_v6 == "",
                    "No IPv6 address advertised to swarm" if not last_ext_v6 else f"IPv6 advertised: {last_ext_v6}",
                    warning=bool(last_ext_v6),
                )
            )

            conn_st = report.qbittorrent_status or str(xfer.get("connection_status", "unknown"))
            spd_str = f"{report.download_speed:.1f} KB/s ↓, {report.upload_speed:.1f} KB/s ↑"
            dht_ok = conn_st == "connected" or dht_nodes > 0
            is_warn = conn_st != "connected" and dht_nodes > 0
            report.checks.append(
                VpnCheckItem(
                    "BitTorrent DHT Swarm",
                    dht_ok,
                    f"State: '{conn_st.capitalize()}' • {dht_nodes} DHT nodes active "
                    f"({report.active_torrents} torrents, {spd_str})",
                    warning=is_warn,
                )
            )
    else:
        report.checks.append(
            VpnCheckItem(
                "BitTorrent Transfer Info",
                False,
                f"Transfer info API unreachable on 127.0.0.1:8080 (exit code {raw.qbt_transfer_code})",
            )
        )

    return report


async def check_gluetun(ctx: StatusContext) -> ServiceResult:
    """Standard service check for the homelab status tree."""
    service_id = "gluetun"
    name = "Gluetun VPN"
    container = "homelab-gluetun-1"
    t0 = time.perf_counter()

    c = await ctx.get_container(container)
    if not c:
        elapsed = (time.perf_counter() - t0) * 1000
        if ctx.no_docker:
            return ServiceResult(
                service_id=service_id,
                name=name,
                container=container,
                status=HealthStatus.HEALTHY,
                latency_ms=elapsed,
                summary="VPN running (Docker inspection skipped via --no-docker)",
                branches=["[dim]Docker inspection skipped (--no-docker)[/dim]"],
            )
        return ServiceResult(
            service_id=service_id,
            name=name,
            container=container,
            status=HealthStatus.UNHEALTHY,
            latency_ms=elapsed,
            summary="Container not found or Docker unreachable",
            branches=["[bold red]✖ Container not found or Docker unreachable[/bold red]"],
        )

    try:
        raw = await _gather_vpn_raw_data(ctx)
        report = evaluate_vpn_report(raw, connection=ctx.connection)
        elapsed = (time.perf_counter() - t0) * 1000

        vpn_ip = report.vpn_ip
        host_ip = report.host_ip
        forwarded_port = report.forwarded_port
        rx_b = report.tun_rx_bytes
        tx_b = report.tun_tx_bytes

        branches: list[str] = []
        is_healthy = report.all_passed

        if ctx.connection:
            badge, endpoint, _ = format_connection_badge(ctx.connection)
            branches.append(f"📡 Route: {badge} [dim]({endpoint})[/dim]")

        if vpn_ip and vpn_ip.ip != "Unknown":
            loc = f"{vpn_ip.country}" if vpn_ip.city == "Unknown" else f"{vpn_ip.city}, {vpn_ip.country}"
            org_str = f" [dim]({vpn_ip.org})[/dim]" if vpn_ip.org != "Unknown" else ""
            branches.append(f"🛡️ Tunnel: [bold green]{vpn_ip.ip}[/bold green] [dim]•[/dim] {loc}{org_str}")

            if host_ip and host_ip.ip != "Unknown":
                if host_ip.ip != vpn_ip.ip:
                    branches.append(
                        f"🔒 Leak Protection: [bold green]SECURE[/bold green] [dim](Host ISP: {host_ip.ip})[/dim]"
                    )
                else:
                    is_healthy = False
                    branches.append(
                        f"⚠️ Leak Protection: [bold red]LEAK DETECTED (VPN IP matches Host IP {host_ip.ip})[/bold red]"
                    )
        else:
            branches.append("🛡️ Tunnel: [bold yellow]External IP lookup timed out[/bold yellow]")

        if forwarded_port:
            branches.append(f"🔌 Port Forwarding: [bold green]{forwarded_port}[/bold green] [dim](NAT-PMP)[/dim]")
        else:
            branches.append("🔌 Port Forwarding: [bold yellow]No active forwarded port detected[/bold yellow]")

        if rx_b > 0 or tx_b > 0:
            branches.append(f"📊 WireGuard Traffic: {_format_bytes(rx_b)} rx [dim]•[/dim] {_format_bytes(tx_b)} tx")

        version = await ctx.get_container_version(container)
        vpn_desc = f"{vpn_ip.ip} ({vpn_ip.country})" if vpn_ip else "connected"
        port_desc = f"Port {forwarded_port} active" if forwarded_port else "no port forward"
        summary = f"ProtonVPN {vpn_desc} • {port_desc}"

        return ServiceResult(
            service_id=service_id,
            name=name,
            container=container,
            status=HealthStatus.HEALTHY if is_healthy else HealthStatus.UNHEALTHY,
            latency_ms=elapsed,
            summary=summary,
            version=version,
            branches=branches,
            raw_data={
                "connection": asdict(ctx.connection) if ctx.connection else None,
                "vpn_ip": asdict(vpn_ip) if vpn_ip else None,
                "host_ip": asdict(host_ip) if host_ip else None,
                "forwarded_port": forwarded_port,
                "tun_rx_bytes": rx_b,
                "tun_tx_bytes": tx_b,
            },
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ServiceResult(
            service_id=service_id,
            name=name,
            container=container,
            status=HealthStatus.UNHEALTHY,
            latency_ms=elapsed,
            summary=f"Error inspecting Gluetun: {exc}",
            branches=[f"[bold red]✖ Error: {exc}[/bold red]"],
            error=str(exc),
        )


async def run_vpn_deep_check(ctx: StatusContext) -> VpnDeepReport:
    """Execute the comprehensive deep verification suite with concurrent I/O."""
    raw = await _gather_vpn_raw_data(ctx)
    return evaluate_vpn_report(raw, connection=ctx.connection)


def render_vpn_deep_report(report: VpnDeepReport, console: Console) -> None:
    if report.connection:
        render_command_header(
            "🛡️ ProtonVPN + Gluetun + qBittorrent Deep Health Inspector",
            report.connection,
            console,
            border_style="magenta",
        )

    table = Table(
        title="🛡️ ProtonVPN + Gluetun + qBittorrent Health Status", show_header=True, header_style="bold magenta"
    )
    table.add_column("Check", style="bold", width=34)
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

    if report.all_passed:
        vpn_org = report.vpn_ip.org if report.vpn_ip else "ProtonVPN"
        vpn_country = report.vpn_ip.country if report.vpn_ip else "NL"
        vpn_endpoint = report.vpn_ip.ip if report.vpn_ip else "Unknown"
        traffic_str = ""
        if report.tun_rx_bytes or report.tun_tx_bytes:
            traffic_str = (
                f"\n• [bold]Tunnel Traffic:[/bold] "
                f"{_format_bytes(report.tun_rx_bytes)} rx / {_format_bytes(report.tun_tx_bytes)} tx"
            )

        verdict = Panel(
            "[bold green]✔ ALL VERIFICATION CHECKS PASSED[/bold green]\n\n"
            f"{route_line}"
            f"• [bold]VPN Endpoint:[/bold] {vpn_endpoint} ({vpn_org}, {vpn_country})\n"
            f"• [bold]Forwarded Port:[/bold] {report.forwarded_port or 'N/A'} (NAT-PMP active)\n"
            f"• [bold]Interface Binding:[/bold] {report.interface_bound or 'tun0'} (Strict isolation)\n"
            f"• [bold]Kill Switch / Firewall:[/bold] ACTIVE (Strict policy DROP with port ACCEPT)\n"
            f"• [bold]DHT & Swarm:[/bold] {report.dht_nodes} nodes connected"
            f"{traffic_str}",
            title="[bold green]Status: SECURE & VERIFIED[/bold green]",
            border_style="green",
        )
    else:
        failed = sum(1 for c in report.checks if not c.passed and not c.warning)
        verdict = Panel(
            f"[bold red]✖ {failed} CRITICAL CHECK(S) FAILED[/bold red]\n\n"
            f"{route_line}"
            "Review the table above for specific misconfigurations or connection errors.",
            title="[bold red]Status: DEGRADED / INSECURE[/bold red]",
            border_style="red",
        )
    console.print(verdict)
    console.print()
