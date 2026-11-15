"""Unit tests for homelab status inspector."""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from config import (
    classify_route,
    format_speed,
    get_ssh_user,
    is_target_local,
    resolve_target_connection,
    resolve_target_host,
)
from main import app
from models import HealthStatus, HomelabConfig, ServiceResult
from services import CHECK_REGISTRY

runner = CliRunner()


def test_format_speed() -> None:
    assert format_speed(500) == "500 B/s"
    assert format_speed(1024) == "1.0 KB/s"
    assert format_speed(1024 * 50) == "50.0 KB/s"
    assert format_speed(1024 * 1024 * 2.5) == "2.50 MB/s"


def test_is_target_local() -> None:
    assert is_target_local("localhost") is True
    assert is_target_local("127.0.0.1") is True
    assert is_target_local("nonexistent-host-999.invalid") is False


def test_resolve_target_host(monkeypatch: pytest.MonkeyPatch) -> None:
    assert resolve_target_host("custom.host") == "custom.host"
    monkeypatch.setenv("HOMELAB_HOSTNAME", "mock-node.lan")
    assert resolve_target_host() == "mock-node.lan"
    monkeypatch.setenv("HOMELAB_HOSTNAME", "")
    monkeypatch.setenv("HOMELAB_HOST", "legacy-node.lan")
    assert resolve_target_host() == "legacy-node.lan"
    monkeypatch.setenv("HOMELAB_HOST", "")
    with pytest.raises(SystemExit) as exc_info:
        resolve_target_host()
    assert exc_info.value.code == 1


def test_get_ssh_user(monkeypatch: pytest.MonkeyPatch) -> None:
    assert get_ssh_user("custom_user") == "custom_user"

    env_mock = {"HOMELAB_SSH_USER": "ssh_admin", "HOMELAB_USERNAME": "generic_user"}
    monkeypatch.setattr("config.get_env_setting", lambda k, d="": env_mock.get(k, d))
    assert get_ssh_user() == "ssh_admin"

    env_mock.pop("HOMELAB_SSH_USER")
    assert get_ssh_user() == "generic_user"

    env_mock.pop("HOMELAB_USERNAME")
    assert get_ssh_user() == "homelab"


def test_classify_route() -> None:
    # Local host
    route, desc = classify_route("localhost", "127.0.0.1", is_local=True)
    assert route == "local"
    assert "Local Host" in desc

    # Tailscale IP (RFC 6598 CGNAT block 100.64.0.0/10)
    route, desc = classify_route("server", "100.64.0.1", is_local=False)
    assert route == "tailscale"
    assert desc == "Tailscale MagicDNS"

    # Tailscale MagicDNS FQDN
    route, desc = classify_route("server.example.ts.net", "100.64.0.1", is_local=False)
    assert route == "tailscale"
    assert desc == "Tailscale MagicDNS"

    # Direct LAN (RFC 1918)
    route, desc = classify_route("server.lan", "192.168.1.10", is_local=False)
    assert route == "lan"
    assert desc == "Direct LAN"

    # Public WAN
    route, desc = classify_route("example.com", "93.184.216.34", is_local=False)
    assert route == "wan"
    assert desc == "WAN / Remote"


def test_resolve_target_connection() -> None:
    conn = resolve_target_connection("server.example.ts.net")
    assert conn.host == "server.example.ts.net"
    if is_target_local("server.example.ts.net"):
        assert conn.route == "local"
        assert conn.is_local is True
    else:
        assert conn.route == "tailscale"
        assert conn.description == "Tailscale MagicDNS"
        assert conn.is_local is False


def test_registry_contains_all_services() -> None:
    expected = {
        "jellyfin",
        "bookorbit",
        "gluetun",
        "qbittorrent",
        "retroarch",
        "caddy",
        "samba",
        "arcane",
        "qui",
        "glance",
        "withings-sync",
        "postgres",
    }
    assert set(CHECK_REGISTRY.keys()) == expected


def test_retroarch_webdav_xml_parsing() -> None:
    sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <D:multistatus xmlns:D="DAV:">
      <D:response>
        <D:href>/</D:href>
        <D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop></D:propstat>
      </D:response>
      <D:response>
        <D:href>/saves/</D:href>
        <D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop></D:propstat>
      </D:response>
      <D:response>
        <D:href>/manifest.server</D:href>
        <D:propstat><D:prop><D:resourcetype></D:resourcetype></D:prop></D:propstat>
      </D:response>
    </D:multistatus>"""

    root = ET.fromstring(sample_xml)
    entries = []
    for resp in root.findall("{DAV:}response"):
        href_elem = resp.find("{DAV:}href")
        if href_elem is None or not href_elem.text:
            continue
        href = href_elem.text
        if href in ("/", ""):
            continue
        resourcetype = resp.find(".//{DAV:}resourcetype")
        is_dir = resourcetype is not None and resourcetype.find("{DAV:}collection") is not None
        clean_name = href.strip("/")
        entries.append(f"{clean_name}/" if is_dir else clean_name)

    entries.sort()
    assert entries == ["manifest.server", "saves/"]


def test_samba_output_parsing() -> None:
    sample_testparm = """
    [global]
        dns proxy = No
    [mango]
        path = /shares/mango
    [media]
        path = /shares/media
    """
    shares = []
    for line in sample_testparm.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            sec = line[1:-1]
            if sec != "global":
                shares.append(sec)

    assert shares == ["mango", "media"]

    sample_pdbedit = """
    username:1001:
    share:1000:
    """
    accounts = [line.split(":")[0].strip() for line in sample_pdbedit.splitlines() if ":" in line]

    assert accounts == ["username", "share"]


def test_caddy_autosave_routes_parsing() -> None:
    sample_caddy_json = """{
      "apps": {
        "http": {
          "servers": {
            "srv0": {
              "routes": [
                {"match": [{"host": ["qbittorrent.example.com"]}]},
                {"match": [{"host": ["jellyfin.example.com"]}]},
                {"match": [{"host": ["example.com"]}]}
              ]
            }
          }
        }
      }
    }"""
    cfg = json.loads(sample_caddy_json)
    srv_routes = cfg.get("apps", {}).get("http", {}).get("servers", {}).get("srv0", {}).get("routes", [])
    hosts = {h for r in srv_routes for m in r.get("match", []) for h in m.get("host", [])}
    assert sorted(hosts) == ["example.com", "jellyfin.example.com", "qbittorrent.example.com"]


def test_service_result_health() -> None:
    res_ok = ServiceResult("test", "Test", "container-1", HealthStatus.HEALTHY, 12.0, "OK", branches=["branch 1"])
    assert res_ok.is_healthy is True

    res_fail = ServiceResult("test", "Test", "container-1", HealthStatus.UNHEALTHY, 12.0, "Err")
    assert res_fail.is_healthy is False

    res_deg = ServiceResult("test", "Test", "container-1", HealthStatus.DEGRADED, 12.0, "Degraded")
    assert res_deg.is_healthy is False


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Run deep health & content availability checks" in result.stdout
    assert "--service" in result.stdout
    assert "--host" in result.stdout
    assert "--json" in result.stdout
    assert "vpn" in result.stdout
    assert "jellyfin" in result.stdout
    assert "samba" in result.stdout


def test_cli_vpn_help() -> None:
    result = runner.invoke(app, ["vpn", "--help"])
    assert result.exit_code == 0
    assert "Deep inspection of ProtonVPN tunnel" in result.stdout
    assert "--json" in result.stdout


def test_cli_jellyfin_help() -> None:
    result = runner.invoke(app, ["jellyfin", "--help"])
    assert result.exit_code == 0
    assert "Deep inspection of Jellyfin container" in result.stdout
    assert "--json" in result.stdout


def test_cli_samba_help() -> None:
    result = runner.invoke(app, ["samba", "--help"])
    assert result.exit_code == 0
    assert "Deep inspection of Samba container" in result.stdout
    assert "--json" in result.stdout


@pytest.mark.anyio
async def test_check_qbittorrent_interface_binding() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from models import StatusContext
    from services.qbittorrent import check_qbittorrent

    ctx = MagicMock(spec=StatusContext)
    ctx.base_url = MagicMock(return_value="http://127.0.0.1:8080")
    ctx.http_timeout = 5.0
    ctx.username = "username"
    ctx.password = "secret"
    ctx.get_container_version = AsyncMock(return_value="v5.0.0")

    def make_mock_client(iface: str, upnp: bool) -> MagicMock:
        mock_c = AsyncMock()
        mock_c.__aenter__.return_value = mock_c

        async def _post(url: str, **kwargs: object) -> MagicMock:
            res = MagicMock()
            res.status_code = 200
            res.text = "Ok."
            return res

        async def _get(url: str, **kwargs: object) -> MagicMock:
            res = MagicMock()
            res.status_code = 200
            if "maindata" in url:
                res.json.return_value = {"torrents": {}, "server_state": {}}
            elif "preferences" in url:
                res.json.return_value = {
                    "current_network_interface": iface,
                    "listen_port": 54757,
                    "upnp": upnp,
                }
            return res

        mock_c.post = AsyncMock(side_effect=_post)
        mock_c.get = AsyncMock(side_effect=_get)
        return mock_c

    # 1. Healthy: bound to tun0, UPnP disabled
    with patch("httpx.AsyncClient", return_value=make_mock_client("tun0", False)):
        res_ok = await check_qbittorrent(ctx)
    assert res_ok.status == HealthStatus.HEALTHY
    assert any("tun0" in b for b in res_ok.branches)

    # 2. Unhealthy: unbound interface
    with patch("httpx.AsyncClient", return_value=make_mock_client("", False)):
        res_unbound = await check_qbittorrent(ctx)
    assert res_unbound.status == HealthStatus.UNHEALTHY
    assert any("UNBOUND" in b for b in res_unbound.branches)

    # 3. Degraded: UPnP enabled
    with patch("httpx.AsyncClient", return_value=make_mock_client("tun0", True)):
        res_upnp = await check_qbittorrent(ctx)
    assert res_upnp.status == HealthStatus.DEGRADED
    assert any("UPnP" in b for b in res_upnp.branches)


def test_homelab_config_validation() -> None:
    # 1. Valid configuration with default ssh_user
    cfg = HomelabConfig.model_validate({
        "HOMELAB_PASSWORD": "secret_password",
        "HOSTNAME_BASE": "example.com",
        "HOMELAB_LAN_SUBNET": "192.168.1.0/24",
    })
    assert cfg.password == "secret_password"
    assert cfg.base_domain == "example.com"
    assert cfg.lan_subnet == "192.168.1.0/24"
    assert cfg.username == "username"
    assert cfg.effective_ssh_user == "username"

    # 2. SSH user override
    cfg_ssh = HomelabConfig.model_validate({
        "HOMELAB_PASSWORD": "secret_password",
        "HOSTNAME_BASE": "example.com",
        "HOMELAB_LAN_SUBNET": "192.168.1.0/24",
        "HOMELAB_USERNAME": "alice",
        "HOMELAB_SSH_USER": "admin",
    })
    assert cfg_ssh.username == "alice"
    assert cfg_ssh.ssh_user == "admin"
    assert cfg_ssh.effective_ssh_user == "admin"

    # 3. Missing password
    with pytest.raises(ValidationError):
        HomelabConfig.model_validate({"HOSTNAME_BASE": "example.com", "HOMELAB_LAN_SUBNET": "192.168.1.0/24"})

    # 4. Missing base domain
    with pytest.raises(ValidationError):
        HomelabConfig.model_validate({"HOMELAB_PASSWORD": "secret_password", "HOMELAB_LAN_SUBNET": "192.168.1.0/24"})

    # 5. Missing LAN subnet
    with pytest.raises(ValidationError):
        HomelabConfig.model_validate({"HOMELAB_PASSWORD": "secret_password", "HOSTNAME_BASE": "example.com"})

    # 6. Empty values
    with pytest.raises(ValidationError):
        HomelabConfig.model_validate({
            "HOMELAB_PASSWORD": "",
            "HOSTNAME_BASE": "example.com",
            "HOMELAB_LAN_SUBNET": "192.168.1.0/24",
        })
    with pytest.raises(ValidationError):
        HomelabConfig.model_validate({
            "HOMELAB_PASSWORD": "secret_password",
            "HOSTNAME_BASE": "",
            "HOMELAB_LAN_SUBNET": "192.168.1.0/24",
        })
    with pytest.raises(ValidationError):
        HomelabConfig.model_validate({
            "HOMELAB_PASSWORD": "secret_password",
            "HOSTNAME_BASE": "example.com",
            "HOMELAB_LAN_SUBNET": "",
        })


def test_container_name_enum() -> None:
    from models import ContainerName

    assert len(ContainerName) == 12
    for member in ContainerName:
        assert member.value.startswith("homelab-")
        assert member.value.endswith("-1")
        assert isinstance(member, str)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, *sys.argv[1:]]))
