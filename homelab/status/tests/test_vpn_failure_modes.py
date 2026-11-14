"""Unit tests simulating failure modes and edge cases for ProtonVPN + Gluetun status checks."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import StatusContext, TargetConnection
from services.gluetun import (
    IpDetails,
    _format_bytes,
    _parse_dns_whoami,
    _parse_ipinfo,
    _parse_tun_stats,
    format_connection_badge,
    run_vpn_deep_check,
)


def _make_mock_container(
    name: str,
    status: str = "running",
    health: str = "healthy",
    net_mode: str = "container:gluetun",
) -> MagicMock:
    c = MagicMock()
    c.name = name
    c.status = status
    c.attrs = {
        "State": {"Health": {"Status": health}},
        "HostConfig": {"NetworkMode": net_mode},
    }
    c.reload = MagicMock()
    return c


def _create_mock_context(
    exec_map: dict[str, tuple[int, str]] | None = None,
    gluetun_status: str = "running",
    gluetun_health: str = "healthy",
    qbt_status: str = "running",
    qbt_net_mode: str = "container:gluetun",
) -> StatusContext:
    ctx = MagicMock(spec=StatusContext)
    ctx.no_docker = False
    ctx.connection = TargetConnection("server.lan", "192.168.1.10", "lan", "Direct LAN")

    c_gluetun = _make_mock_container("homelab-gluetun-1", status=gluetun_status, health=gluetun_health)
    c_qbt = _make_mock_container(
        "homelab-qbittorrent-1", status=qbt_status, net_mode=qbt_net_mode
    )

    async def _get_container(name: str, full: bool = False) -> MagicMock | None:
        if "gluetun" in name:
            return c_gluetun
        if "qbittorrent" in name:
            return c_qbt
        return None

    ctx.get_container = AsyncMock(side_effect=_get_container)

    mapping = exec_map or {}

    async def _exec_container(container_name: str, cmd: str | list[str]) -> tuple[int, str]:
        cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)

        if "===TUN===" in cmd_str:
            tun_code, tun_out = mapping.get("ip -s link show dev tun0", (0, ""))
            res_code, res_out = mapping.get("cat /etc/resolv.conf", (0, ""))
            v6_code, v6_out = mapping.get("ip -6 route", (0, ""))
            port_code, port_out = mapping.get("forwarded_port", (0, ""))
            ipt_code, ipt_out = mapping.get("iptables -nL INPUT", (0, ""))
            net_code, net_out = mapping.get("netstat -tuln", (0, ""))
            batch_out = (
                f"===TUN===\n{tun_out}\n"
                f"===RESOLV===\n{res_out}\n"
                f"===V6===\n{v6_out}\n"
                f"===PORT===\n{port_out}\n"
                f"===IPTABLES===\n{ipt_out}\n"
                f"===NETSTAT===\n{net_out}\n"
                "===END==="
            )
            overall_code = tun_code or res_code or v6_code or port_code or ipt_code or net_code
            return (overall_code, batch_out)

        if "===PREFS===" in cmd_str:
            p_code, p_out = mapping.get("api/v2/app/preferences", (0, ""))
            m_code, m_out = mapping.get("api/v2/sync/maindata", (0, ""))
            t_code, t_out = mapping.get("api/v2/transfer/info", (0, ""))
            batch_out = (
                f"===PREFS===\n{p_out}\n"
                f"===MAINDATA===\n{m_out}\n"
                f"===TRANSFER===\n{t_out}\n"
                "===END==="
            )
            overall_code = p_code or m_code or t_code
            return (overall_code, batch_out)

        for pattern, res in mapping.items():
            if pattern in cmd_str:
                return res
        return (0, "")

    ctx.exec_container = AsyncMock(side_effect=_exec_container)
    return ctx


def _default_exec_map(
    forwarded_port: int = 54757,
    qbt_port: int = 54757,
    bound_interface: str = "tun0",
    upnp: bool = False,
    dht_nodes: int = 150,
    conn_status: str = "connected",
    ext_v4: str = "185.107.44.204",
    ext_v6: str = "",
) -> dict[str, tuple[int, str]]:
    sample_tun = (
        "3: tun0: <POINTOPOINT,UP> mtu 1320\n"
        "    RX:  bytes packets errors dropped\n"
        "        500000    1000      0       0\n"
        "    TX:  bytes packets errors dropped\n"
        "        250000     800      0       0\n"
    )
    iptables_rules = (
        "Chain INPUT (policy DROP)\n"
        f"ACCEPT     tcp  --  0.0.0.0/0            0.0.0.0/0            tcp dpt:{forwarded_port}\n"
        f"ACCEPT     udp  --  0.0.0.0/0            0.0.0.0/0            udp dpt:{forwarded_port}\n"
    )
    prefs_json = json.dumps({
        "listen_port": qbt_port,
        "current_network_interface": bound_interface,
        "upnp": upnp,
    })
    maindata_json = json.dumps({
        "server_state": {
            "connection_status": conn_status,
            "dl_info_speed": 10240,
            "up_info_speed": 5120,
        },
        "torrents": {"hash1": {}, "hash2": {}},
    })
    transfer_json = json.dumps({
        "connection_status": conn_status,
        "dht_nodes": dht_nodes,
        "last_external_address_v4": ext_v4,
        "last_external_address_v6": ext_v6,
    })

    return {
        "ip -s link show dev tun0": (0, sample_tun),
        "cat /etc/resolv.conf": (0, "nameserver 127.0.0.1\n"),
        "cdn-cgi/trace": (0, f"ip={ext_v4}\nloc=NL\n"),
        "whoami.akamai.net": (
            0,
            "Server:\t127.0.0.1\nAddress:\t127.0.0.1:53\nName:\twhoami.akamai.net\nAddress: 172.70.45.191\n",
        ),
        "ip -6 route": (0, "fe80::/64 dev tun0 proto kernel metric 256\n"),
        "forwarded_port": (0, str(forwarded_port)),
        "iptables -nL INPUT": (0, iptables_rules),
        "netstat -tuln": (0, f"tcp 10.2.0.2:{forwarded_port} LISTEN\nudp 10.2.0.2:{forwarded_port}\n"),
        "api/v2/app/preferences": (0, prefs_json),
        "api/v2/sync/maindata": (0, maindata_json),
        "api/v2/transfer/info": (0, transfer_json),
    }


def test_helper_parsers() -> None:
    # Test _parse_tun_stats
    sample_tun = (
        "3: tun0: <POINTOPOINT,UP>\n"
        "    RX:  bytes packets errors dropped\n"
        "        1048576    2000      0       0\n"
        "    TX:  bytes packets errors dropped\n"
        "         524288    1000      0       0\n"
    )
    rx_b, rx_p, tx_b, tx_p = _parse_tun_stats(sample_tun)
    assert rx_b == 1048576
    assert rx_p == 2000
    assert tx_b == 524288
    assert tx_p == 1000

    # Test _format_bytes
    assert _format_bytes(500) == "500 B"
    assert _format_bytes(1024 * 5) == "5.0 KB"
    assert _format_bytes(1024 * 1024 * 2) == "2.0 MB"
    assert _format_bytes(1024 * 1024 * 1024 * 3) == "3.00 GB"

    # Test _parse_ipinfo
    info = _parse_ipinfo({"ip": "1.2.3.4", "country": "NL", "org": "AS123 Test"})
    assert info.ip == "1.2.3.4"
    assert info.country == "NL"
    assert info.org == "AS123 Test"

    # Test _parse_dns_whoami
    sample_dns = (
        "Server:\t127.0.0.1\nAddress:\t127.0.0.1:53\n\n"
        "Non-authoritative answer:\nName:\twhoami.akamai.net\nAddress: 172.70.45.191\n"
    )
    assert _parse_dns_whoami(sample_dns) == "172.70.45.191"
    assert _parse_dns_whoami("no address here") == ""


@pytest.mark.anyio
async def test_vpn_healthy_all_checks_pass() -> None:
    ctx = _create_mock_context(exec_map=_default_exec_map())
    vpn_ip = IpDetails("185.107.44.204", "NL", "North Brabant", "Roosendaal", "AS43350 NForce")
    host_ip = IpDetails("198.51.100.1", "US", "WA", "Seattle", "AS6079 RCN")

    with (
        patch("services.gluetun._fetch_host_ip", AsyncMock(return_value=host_ip)),
        patch("services.gluetun._fetch_gluetun_ip", AsyncMock(return_value=vpn_ip)),
    ):
        report = await run_vpn_deep_check(ctx)

    assert report.all_passed is True
    assert report.connection == ctx.connection
    check_names = [c.name for c in report.checks]
    assert "Inspection Route" in check_names
    assert report.checks[0].name == "Inspection Route"
    assert "Direct LAN" in report.checks[0].details
    assert "Gluetun Container" in check_names
    assert "qBittorrent Container" in check_names
    assert "Network Namespace Isolation" in check_names
    assert "WireGuard Tunnel Interface (tun0)" in check_names
    assert "IP Leak Test" in check_names
    assert "DNS Leak & Resolver Security" in check_names
    assert "IPv6 Leak Prevention" in check_names
    assert "Gluetun Port Forwarding" in check_names
    assert "Firewall Inbound Policy" in check_names
    assert "qBittorrent Interface Binding" in check_names
    assert "qBittorrent Listening Port" in check_names
    assert "qBittorrent UPnP Disabled" in check_names
    assert "qBittorrent Peer External IP" in check_names
    assert "BitTorrent DHT Swarm" in check_names


@pytest.mark.anyio
async def test_failure_mode_killswitch_tunnel_down() -> None:
    """When VPN tunnel drops: tun0 is gone, Gluetun health is unhealthy, lookups fail."""
    exec_map = _default_exec_map()
    exec_map["ip -s link show dev tun0"] = (1, "Cannot find device 'tun0'")
    exec_map["cdn-cgi/trace"] = (4, "")
    exec_map["whoami.akamai.net"] = (1, "connection timed out")

    ctx = _create_mock_context(
        exec_map=exec_map,
        gluetun_health="unhealthy",
    )
    host_ip = IpDetails("198.51.100.1", "US", "WA", "Seattle", "AS6079 RCN")

    with (
        patch("services.gluetun._fetch_host_ip", AsyncMock(return_value=host_ip)),
        patch("services.gluetun._fetch_gluetun_ip", AsyncMock(return_value=None)),
    ):
        report = await run_vpn_deep_check(ctx)

    assert report.all_passed is False
    c_dict = {c.name: c for c in report.checks}
    assert c_dict["Gluetun Container"].passed is False
    assert c_dict["WireGuard Tunnel Interface (tun0)"].passed is False
    assert c_dict["VPN Public IP"].passed is False
    assert c_dict["DNS Leak & Resolver Security"].passed is False


@pytest.mark.anyio
async def test_failure_mode_ip_leak() -> None:
    """Critical leak: Gluetun's egress IP matches the host ISP IP."""
    ctx = _create_mock_context(exec_map=_default_exec_map())
    leaked_ip = IpDetails("198.51.100.1", "US", "WA", "Seattle", "AS6079 RCN")

    with (
        patch("services.gluetun._fetch_host_ip", AsyncMock(return_value=leaked_ip)),
        patch("services.gluetun._fetch_gluetun_ip", AsyncMock(return_value=leaked_ip)),
    ):
        report = await run_vpn_deep_check(ctx)

    assert report.all_passed is False
    c_dict = {c.name: c for c in report.checks}
    assert c_dict["IP Leak Test"].passed is False
    assert "Host ISP IP: 198.51.100.1" in c_dict["IP Leak Test"].details


@pytest.mark.anyio
async def test_failure_mode_port_forwarding_desync() -> None:
    """Port desync: ProtonVPN forwards 54757, but qBittorrent is listening on 40000."""
    exec_map = _default_exec_map(forwarded_port=54757, qbt_port=40000)
    ctx = _create_mock_context(exec_map=exec_map)
    vpn_ip = IpDetails("185.107.44.204", "NL")
    host_ip = IpDetails("198.51.100.1", "US")

    with (
        patch("services.gluetun._fetch_host_ip", AsyncMock(return_value=host_ip)),
        patch("services.gluetun._fetch_gluetun_ip", AsyncMock(return_value=vpn_ip)),
    ):
        report = await run_vpn_deep_check(ctx)

    assert report.all_passed is False
    c_dict = {c.name: c for c in report.checks}
    assert c_dict["qBittorrent Listening Port"].passed is False
    assert "Mismatch with port 54757" in c_dict["qBittorrent Listening Port"].details


@pytest.mark.anyio
async def test_failure_mode_namespace_isolation_broken() -> None:
    """Misconfiguration: qBittorrent detached from Gluetun, running on standard bridge."""
    exec_map = _default_exec_map()
    ctx = _create_mock_context(exec_map=exec_map, qbt_net_mode="bridge")
    vpn_ip = IpDetails("185.107.44.204", "NL")
    host_ip = IpDetails("198.51.100.1", "US")

    with (
        patch("services.gluetun._fetch_host_ip", AsyncMock(return_value=host_ip)),
        patch("services.gluetun._fetch_gluetun_ip", AsyncMock(return_value=vpn_ip)),
    ):
        report = await run_vpn_deep_check(ctx)

    assert report.all_passed is False
    c_dict = {c.name: c for c in report.checks}
    assert c_dict["Network Namespace Isolation"].passed is False
    assert "bridge" in c_dict["Network Namespace Isolation"].details


@pytest.mark.anyio
async def test_failure_mode_qbittorrent_api_down() -> None:
    """Daemon crash: qBittorrent Web API is unresponsive or connection refused."""
    exec_map = _default_exec_map()
    exec_map["api/v2/app/preferences"] = (7, "Failed to connect to 127.0.0.1 port 8080")
    ctx = _create_mock_context(exec_map=exec_map)
    vpn_ip = IpDetails("185.107.44.204", "NL")
    host_ip = IpDetails("198.51.100.1", "US")

    with (
        patch("services.gluetun._fetch_host_ip", AsyncMock(return_value=host_ip)),
        patch("services.gluetun._fetch_gluetun_ip", AsyncMock(return_value=vpn_ip)),
    ):
        report = await run_vpn_deep_check(ctx)

    assert report.all_passed is False
    c_dict = {c.name: c for c in report.checks}
    assert c_dict["qBittorrent Web API"].passed is False
    assert "exit code 7" in c_dict["qBittorrent Web API"].details


@pytest.mark.anyio
async def test_failure_mode_interface_unbound_warning() -> None:
    """Defense-in-depth weakened: qBittorrent is listening on all interfaces instead of tun0."""
    exec_map = _default_exec_map(bound_interface="")
    ctx = _create_mock_context(exec_map=exec_map)
    vpn_ip = IpDetails("185.107.44.204", "NL")
    host_ip = IpDetails("198.51.100.1", "US")

    with (
        patch("services.gluetun._fetch_host_ip", AsyncMock(return_value=host_ip)),
        patch("services.gluetun._fetch_gluetun_ip", AsyncMock(return_value=vpn_ip)),
    ):
        report = await run_vpn_deep_check(ctx)

    c_dict = {c.name: c for c in report.checks}
    assert c_dict["qBittorrent Interface Binding"].warning is True
    assert "not bound to tun0" in c_dict["qBittorrent Interface Binding"].details


@pytest.mark.anyio
async def test_failure_mode_upnp_enabled() -> None:
    """UPnP enabled: should fail because UPnP leaks outside of NAT-PMP tunnels."""
    exec_map = _default_exec_map(upnp=True)
    ctx = _create_mock_context(exec_map=exec_map)
    vpn_ip = IpDetails("185.107.44.204", "NL")
    host_ip = IpDetails("198.51.100.1", "US")

    with (
        patch("services.gluetun._fetch_host_ip", AsyncMock(return_value=host_ip)),
        patch("services.gluetun._fetch_gluetun_ip", AsyncMock(return_value=vpn_ip)),
    ):
        report = await run_vpn_deep_check(ctx)

    assert report.all_passed is False
    c_dict = {c.name: c for c in report.checks}
    assert c_dict["qBittorrent UPnP Disabled"].passed is False
    assert "Enabled" in c_dict["qBittorrent UPnP Disabled"].details


@pytest.mark.anyio
async def test_adversarial_ghost_port_forward() -> None:
    """Adversarial check: Gluetun claims port 54757 is forwarded, but no socket is listening."""
    exec_map = _default_exec_map(forwarded_port=54757)
    # Netstat output has random other ports, but NOT 54757
    exec_map["netstat -tuln"] = (0, "tcp 127.0.0.1:9999 LISTEN\ntcp :::8080 LISTEN\n")

    ctx = _create_mock_context(exec_map=exec_map)
    vpn_ip = IpDetails("185.107.44.204", "NL")
    host_ip = IpDetails("198.51.100.1", "US")

    with (
        patch("services.gluetun._fetch_host_ip", AsyncMock(return_value=host_ip)),
        patch("services.gluetun._fetch_gluetun_ip", AsyncMock(return_value=vpn_ip)),
    ):
        report = await run_vpn_deep_check(ctx)

    c_dict = {c.name: c for c in report.checks}
    assert "Inbound Port Listener" in c_dict
    assert c_dict["Inbound Port Listener"].warning is True
    assert "Ghost port" in c_dict["Inbound Port Listener"].details


@pytest.mark.anyio
async def test_adversarial_stale_cache_bypass() -> None:
    """Adversarial check: /tmp/gluetun/ip has a cached VPN IP, but live egress leaked."""
    from services.gluetun import _fetch_gluetun_ip

    ctx = MagicMock()
    # If container tries to query live ipinfo.io, it returns the LEAKED host IP!
    leaked_json = json.dumps({"ip": "198.51.100.1", "country": "US", "org": "AS6079 RCN"})

    async def _mock_exec(c_name: str, cmd: str | list[str]) -> tuple[int, str]:
        cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)
        if "ipinfo.io/json" in cmd_str:
            return (0, leaked_json)
        if "cat /tmp/gluetun/ip" in cmd_str:
            # Stale cached file with ProtonVPN IP!
            return (0, "185.107.44.204")
        return (0, "")

    ctx.exec_container = AsyncMock(side_effect=_mock_exec)

    # When querying gluetun ip, it MUST prioritize live egress over stale /tmp/gluetun/ip
    result = await _fetch_gluetun_ip(ctx, "homelab-gluetun-1")
    assert result is not None
    assert result.ip == "198.51.100.1"  # Detected the live leak, rejected stale cache!

    # When live queries fail, it strictly returns None (never falls back to stale disk files)
    ctx.exec_container = AsyncMock(return_value=(1, "Connection refused"))
    result_failed = await _fetch_gluetun_ip(ctx, "homelab-gluetun-1")
    assert result_failed is None


@pytest.mark.anyio
async def test_vpn_inspection_routes() -> None:
    """Verify that On-Device, Direct LAN, and Tailscale connection routes are correctly captured."""
    # 1. On-Device (local UNIX socket)
    local_conn = TargetConnection("server", "127.0.0.1", "local", "Local Host (UNIX socket)", is_local=True)
    badge, endpoint, full = format_connection_badge(local_conn)
    assert "On-Device" in badge
    assert endpoint == "server • Local UNIX socket"
    assert full == "On-Device (server • Local UNIX socket)"

    ctx_local = _create_mock_context(exec_map=_default_exec_map())
    ctx_local.connection = local_conn
    with (
        patch("services.gluetun._fetch_host_ip", AsyncMock(return_value=IpDetails("198.51.100.1"))),
        patch("services.gluetun._fetch_gluetun_ip", AsyncMock(return_value=IpDetails("185.107.44.204"))),
    ):
        report_local = await run_vpn_deep_check(ctx_local)
    assert report_local.checks[0].name == "Inspection Route"
    assert report_local.checks[0].details == "On-Device (server • Local UNIX socket)"
    assert report_local.checks[0].passed is True

    # 2. Remote via Direct LAN
    lan_conn = TargetConnection("server.lan", "192.168.1.10", "lan", "Direct LAN", is_local=False)
    badge_lan, endpoint_lan, full_lan = format_connection_badge(lan_conn)
    assert "Direct LAN" in badge_lan
    assert endpoint_lan == "server.lan • 192.168.1.10"
    assert full_lan == "Remote via Direct LAN (server.lan • 192.168.1.10)"

    ctx_lan = _create_mock_context(exec_map=_default_exec_map())
    ctx_lan.connection = lan_conn
    with (
        patch("services.gluetun._fetch_host_ip", AsyncMock(return_value=IpDetails("198.51.100.1"))),
        patch("services.gluetun._fetch_gluetun_ip", AsyncMock(return_value=IpDetails("185.107.44.204"))),
    ):
        report_lan = await run_vpn_deep_check(ctx_lan)
    assert report_lan.checks[0].name == "Inspection Route"
    assert report_lan.checks[0].details == "Remote via Direct LAN (server.lan • 192.168.1.10)"

    # 3. Remote via Tailscale
    ts_conn = TargetConnection("server", "100.64.0.1", "tailscale", "Tailscale MagicDNS", is_local=False)
    badge_ts, endpoint_ts, full_ts = format_connection_badge(ts_conn)
    assert "Tailscale" in badge_ts
    assert endpoint_ts == "server • 100.64.0.1"
    assert full_ts == "Remote via Tailscale (server • 100.64.0.1)"

    ctx_ts = _create_mock_context(exec_map=_default_exec_map())
    ctx_ts.connection = ts_conn
    with (
        patch("services.gluetun._fetch_host_ip", AsyncMock(return_value=IpDetails("198.51.100.1"))),
        patch("services.gluetun._fetch_gluetun_ip", AsyncMock(return_value=IpDetails("185.107.44.204"))),
    ):
        report_ts = await run_vpn_deep_check(ctx_ts)
    assert report_ts.checks[0].name == "Inspection Route"
    assert report_ts.checks[0].details == "Remote via Tailscale (server • 100.64.0.1)"


@pytest.mark.anyio
async def test_failure_mode_dns_resolver_leak() -> None:
    """DNS leak: recursive DNS resolver matches host ISP IP."""
    exec_map = _default_exec_map()
    # Leaked resolver IP matching host ISP
    exec_map["whoami.akamai.net"] = (
        0,
        "Server:\t127.0.0.1\nAddress:\t127.0.0.1:53\nName:\twhoami.akamai.net\nAddress: 198.51.100.1\n",
    )
    ctx = _create_mock_context(exec_map=exec_map)
    host_ip = IpDetails("198.51.100.1", "US", "WA", "Seattle", "AS6079 RCN")
    vpn_ip = IpDetails("185.107.44.204", "NL", "North Brabant", "Roosendaal", "AS43350 NForce")

    with (
        patch("services.gluetun._fetch_host_ip", AsyncMock(return_value=host_ip)),
        patch("services.gluetun._fetch_gluetun_ip", AsyncMock(return_value=vpn_ip)),
    ):
        report = await run_vpn_deep_check(ctx)

    assert report.all_passed is False
    c_dict = {c.name: c for c in report.checks}
    assert c_dict["DNS Leak & Resolver Security"].passed is False


@pytest.mark.anyio
async def test_failure_mode_peer_swarm_ip_leak() -> None:
    """Swarm leak: qBittorrent advertises the host ISP IP to the BitTorrent DHT swarm."""
    exec_map = _default_exec_map(ext_v4="198.51.100.1")
    ctx = _create_mock_context(exec_map=exec_map)
    host_ip = IpDetails("198.51.100.1", "US", "WA", "Seattle", "AS6079 RCN")
    vpn_ip = IpDetails("185.107.44.204", "NL", "North Brabant", "Roosendaal", "AS43350 NForce")

    with (
        patch("services.gluetun._fetch_host_ip", AsyncMock(return_value=host_ip)),
        patch("services.gluetun._fetch_gluetun_ip", AsyncMock(return_value=vpn_ip)),
    ):
        report = await run_vpn_deep_check(ctx)

    assert report.all_passed is False
    c_dict = {c.name: c for c in report.checks}
    assert c_dict["qBittorrent Peer External IP"].passed is False
    assert "CRITICAL LEAK" in c_dict["qBittorrent Peer External IP"].details


@pytest.mark.anyio
async def test_peer_swarm_ip_pending() -> None:
    """When newly started, qBittorrent has no reported external address yet."""
    exec_map = _default_exec_map(ext_v4="")
    ctx = _create_mock_context(exec_map=exec_map)
    host_ip = IpDetails("198.51.100.1", "US", "WA", "Seattle", "AS6079 RCN")
    vpn_ip = IpDetails("185.107.44.204", "NL", "North Brabant", "Roosendaal", "AS43350 NForce")

    with (
        patch("services.gluetun._fetch_host_ip", AsyncMock(return_value=host_ip)),
        patch("services.gluetun._fetch_gluetun_ip", AsyncMock(return_value=vpn_ip)),
    ):
        report = await run_vpn_deep_check(ctx)

    c_dict = {c.name: c for c in report.checks}
    assert "qBittorrent Peer External IP" in c_dict
    assert c_dict["qBittorrent Peer External IP"].warning is True
    assert "Pending peer connection" in c_dict["qBittorrent Peer External IP"].details

