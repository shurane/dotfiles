"""Unit tests simulating failure modes and edge cases for qBittorrent deep health inspection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homelab_status.main import app
from homelab_status.models import StatusContext, TargetConnection
from homelab_status.services.qbittorrent import (
    QbittorrentRawData,
    evaluate_qbittorrent_report,
    run_qbittorrent_deep_check,
    summarize_torrent_catalog,
)
from typer.testing import CliRunner

runner = CliRunner()


def _make_mock_raw(
    container_found: bool = True,
    container_status: str = "running",
    container_health: str = "healthy",
    restart_count: int = 0,
    api_auth_code: int = 200,
    api_auth_error: str = "",
    current_network_interface: str = "tun0",
    listen_port: int = 54757,
    upnp: bool = False,
    status_bar_external_ip: bool = True,
    gluetun_forwarded_port: int = 54757,
    last_external_ip: str = "185.107.44.204",
    vpn_public_ip: str = "185.107.44.204",
    host_public_ip: str = "73.15.20.100",
    torrents_rw_code: int = 0,
    torrents_rw_out: str = "",
    free_space_bytes: int = 700 * 1024 * 1024 * 1024,  # 700 GB
    use_alt_speed_limits: bool = False,
    torrents: dict | None = None,
    qui_found: bool = True,
    qui_status: str = "running",
    qui_health: str = "healthy",
) -> QbittorrentRawData:
    raw = QbittorrentRawData()
    raw.container_found = container_found
    raw.container_status = container_status
    raw.container_health = container_health
    raw.restart_count = restart_count
    raw.api_auth_code = api_auth_code
    raw.api_auth_error = api_auth_error
    raw.torrents_rw_code = torrents_rw_code
    raw.torrents_rw_out = torrents_rw_out
    raw.gluetun_forwarded_port = gluetun_forwarded_port
    raw.vpn_public_ip = vpn_public_ip
    raw.host_public_ip = host_public_ip
    raw.qui_found = qui_found
    raw.qui_status = qui_status
    raw.qui_health = qui_health

    raw.preferences = {
        "current_network_interface": current_network_interface,
        "listen_port": listen_port,
        "upnp": upnp,
        "status_bar_external_ip": status_bar_external_ip,
    }

    raw.server_state = {
        "dl_info_speed": 1048576,  # 1 MB/s
        "up_info_speed": 524288,  # 512 KB/s
        "alltime_dl": 500 * 1024 * 1024 * 1024,
        "alltime_ul": 400 * 1024 * 1024 * 1024,
        "global_ratio": "0.80",
        "dht_nodes": 350,
        "total_peer_connections": 10,
        "free_space_on_disk": free_space_bytes,
        "last_external_address_v4": last_external_ip,
        "connection_status": "connected",
        "use_alt_speed_limits": use_alt_speed_limits,
    }

    raw.torrents = (
        torrents
        if torrents is not None
        else {
            "hash1": {"name": "Ubuntu Linux ISO", "state": "uploading", "progress": 1.0},
            "hash2": {"name": "Debian Linux ISO", "state": "downloading", "progress": 0.5},
            "hash3": {"name": "Arch Linux ISO", "state": "stalledUP", "progress": 1.0},
        }
    )
    return raw


def test_evaluate_qbittorrent_report_healthy() -> None:
    raw = _make_mock_raw()
    conn = TargetConnection(host="server.lan", ip="192.168.1.10", route="lan", description="Direct LAN")
    report = evaluate_qbittorrent_report(raw, connection=conn)

    assert report.all_passed is True
    assert report.catalog.total == 3
    assert report.catalog.completed == 2
    assert report.catalog.downloading == 1
    assert report.catalog.errored == 0

    checks = {c.name: c for c in report.checks}
    assert checks["Container Lifecycle"].passed is True
    assert checks["WebUI API Authentication"].passed is True
    assert checks["VPN Interface Binding"].passed is True
    assert checks["UPnP / NAT-PMP Safety"].passed is True
    assert checks["Listen Port Alignment"].passed is True
    assert checks["External IP & Leak Guard"].passed is True
    assert checks["Storage Mount & Free Space"].passed is True
    assert checks["Torrent Catalog Health"].passed is True
    assert checks["Bandwidth Throttling"].passed is True


def test_container_missing_or_stopped() -> None:
    raw_missing = _make_mock_raw(container_found=False)
    report_missing = evaluate_qbittorrent_report(raw_missing)
    assert report_missing.all_passed is False
    check_m = next(c for c in report_missing.checks if c.name == "Container Lifecycle")
    assert check_m.passed is False
    assert "not found" in check_m.details

    raw_stopped = _make_mock_raw(container_status="exited")
    report_stopped = evaluate_qbittorrent_report(raw_stopped)
    assert report_stopped.all_passed is False
    check_s = next(c for c in report_stopped.checks if c.name == "Container Lifecycle")
    assert check_s.passed is False
    assert "exited" in check_s.details


def test_auth_failure() -> None:
    raw = _make_mock_raw(api_auth_code=403, api_auth_error="Fails")
    report = evaluate_qbittorrent_report(raw)
    assert report.all_passed is False
    check = next(c for c in report.checks if c.name == "WebUI API Authentication")
    assert check.passed is False
    assert "Authentication failed" in check.details


def test_vpn_interface_unbound() -> None:
    raw = _make_mock_raw(current_network_interface="")
    report = evaluate_qbittorrent_report(raw)
    assert report.all_passed is False
    check = next(c for c in report.checks if c.name == "VPN Interface Binding")
    assert check.passed is False
    assert "Critical leak hazard" in check.details


def test_upnp_enabled_warning() -> None:
    raw = _make_mock_raw(upnp=True)
    report = evaluate_qbittorrent_report(raw)
    assert report.all_passed is True  # Warning does not fail overall report
    check = next(c for c in report.checks if c.name == "UPnP / NAT-PMP Safety")
    assert check.warning is True
    assert "ENABLED" in check.details


def test_port_forwarding_mismatch() -> None:
    raw = _make_mock_raw(listen_port=50000, gluetun_forwarded_port=54757)
    report = evaluate_qbittorrent_report(raw)
    assert report.all_passed is False
    check = next(c for c in report.checks if c.name == "Listen Port Alignment")
    assert check.passed is False
    assert "Port mismatch" in check.details


def test_external_ip_leak_to_host() -> None:
    raw = _make_mock_raw(last_external_ip="73.15.20.100", host_public_ip="73.15.20.100")
    report = evaluate_qbittorrent_report(raw)
    assert report.all_passed is False
    check = next(c for c in report.checks if c.name == "External IP & Leak Guard")
    assert check.passed is False
    assert "CRITICAL LEAK" in check.details


def test_storage_rw_failure() -> None:
    raw = _make_mock_raw(torrents_rw_code=1, torrents_rw_out="Read-only file system")
    report = evaluate_qbittorrent_report(raw)
    assert report.all_passed is False
    check = next(c for c in report.checks if c.name == "Storage Mount & Free Space")
    assert check.passed is False
    assert "unwritable or failed" in check.details


def test_low_disk_space_warning() -> None:
    raw = _make_mock_raw(free_space_bytes=5 * 1024 * 1024 * 1024)  # 5 GB free
    report = evaluate_qbittorrent_report(raw)
    check = next(c for c in report.checks if c.name == "Storage Mount & Free Space")
    assert check.warning is True
    assert "LOW DISK SPACE WARNING" in check.details


def test_errored_torrents_detection() -> None:
    bad_torrents = {
        "hash1": {"name": "Corrupted Download", "state": "error", "progress": 0.2},
        "hash2": {"name": "Deleted File", "state": "missingFiles", "progress": 1.0},
        "hash3": {"name": "Healthy Seeder", "state": "uploading", "progress": 1.0},
    }
    raw = _make_mock_raw(torrents=bad_torrents)
    report = evaluate_qbittorrent_report(raw)
    assert report.catalog.errored == 2
    assert "Corrupted Download" in report.catalog.errored_names
    assert "Deleted File" in report.catalog.errored_names

    check = next(c for c in report.checks if c.name == "Torrent Catalog Health")
    assert check.warning is True
    assert "2 errored" in check.details


def test_turtle_mode_active() -> None:
    raw = _make_mock_raw(use_alt_speed_limits=True)
    report = evaluate_qbittorrent_report(raw)
    check = next(c for c in report.checks if c.name == "Bandwidth Throttling")
    assert check.warning is True
    assert "Turtle Mode 🐢" in check.details


def test_qui_container_stopped() -> None:
    raw = _make_mock_raw(qui_status="exited")
    report = evaluate_qbittorrent_report(raw)
    assert report.all_passed is False
    check = next(c for c in report.checks if c.name == "Qui Web Companion")
    assert check.passed is False
    assert "exited" in check.details


def test_summarize_torrent_catalog_empty() -> None:
    cat = summarize_torrent_catalog({})
    assert cat.total == 0
    assert cat.completed == 0
    assert cat.errored == 0


@pytest.mark.anyio
async def test_run_qbittorrent_deep_check_with_mock_context() -> None:
    ctx = MagicMock(spec=StatusContext)
    ctx.username = "username"
    ctx.password = "secret"
    ctx.base_domain = "example.com"
    ctx.no_docker = False
    ctx.connection = None
    ctx.base_url = MagicMock(return_value="http://localhost:8080")
    ctx.http_timeout = 2.0

    c_mock = MagicMock()
    c_mock.status = "running"
    c_mock.health = "healthy"
    c_mock.restart_count = 0

    async def _get_c(name: str, full: bool = False) -> MagicMock:
        return c_mock

    async def _exec_c(name: str, cmd: str | list[str]) -> tuple[int, str]:
        cmd_str = str(cmd)
        if "forwarded_port" in cmd_str:
            return 0, "54757"
        if "status_check" in cmd_str:
            return 0, ""
        if "ipinfo.io" in cmd_str:
            return 0, "185.107.44.204"
        return 0, ""

    ctx.get_container = _get_c
    ctx.exec_container = _exec_c
    ctx.get_container_version = AsyncMock(return_value="v5.0.0")

    report = await run_qbittorrent_deep_check(ctx)
    assert report.version == "v5.0.0"


def test_cli_qbittorrent_json_invocation() -> None:
    result = runner.invoke(app, ["qbittorrent", "--help"])
    assert result.exit_code == 0
    assert "Deep inspection of qBittorrent container" in result.output
