#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "anyio>=4.7.0",
#   "docker>=7.1.0",
#   "httpx>=0.27.0",
#   "paramiko>=3.5.0",
#   "pytest>=8.0.0",
#   "python-dotenv>=1.0.0",
#   "rich>=13.0.0",
#   "typer>=0.16.0",
# ]
# ///
"""Unit tests for homelab status inspector."""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET

from status.config import format_speed, is_target_local, resolve_target_host
from status.main import app
from status.models import HealthStatus, ServiceResult
from status.services import CHECK_REGISTRY
from typer.testing import CliRunner

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


def test_resolve_target_host() -> None:
    assert resolve_target_host("custom.host") == "custom.host"
    resolved = resolve_target_host()
    assert resolved in ("m70q.lan", "m70q")


def test_registry_contains_all_services() -> None:
    expected = {
        "jellyfin",
        "bookorbit",
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
    ehtesh:1001:
    share:1000:
    """
    accounts = []
    for line in sample_pdbedit.splitlines():
        if ":" in line:
            accounts.append(line.split(":")[0].strip())

    assert accounts == ["ehtesh", "share"]


def test_caddy_autosave_routes_parsing() -> None:
    sample_caddy_json = """{
      "apps": {
        "http": {
          "servers": {
            "srv0": {
              "routes": [
                {"match": [{"host": ["qbittorrent.009973.xyz"]}]},
                {"match": [{"host": ["jellyfin.009973.xyz"]}]},
                {"match": [{"host": ["009973.xyz"]}]}
              ]
            }
          }
        }
      }
    }"""
    cfg = json.loads(sample_caddy_json)
    srv_routes = (
        cfg.get("apps", {})
        .get("http", {})
        .get("servers", {})
        .get("srv0", {})
        .get("routes", [])
    )
    hosts = {h for r in srv_routes for m in r.get("match", []) for h in m.get("host", [])}
    assert sorted(hosts) == ["009973.xyz", "jellyfin.009973.xyz", "qbittorrent.009973.xyz"]


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


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, *sys.argv[1:]]))

