"""Unit tests simulating failure modes and edge cases for Jellyfin deep health inspection."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from models import StatusContext, TargetConnection
from services.jellyfin import (
    JellyfinRawData,
    _format_playback_time,
    _format_relative_time,
    _parse_qsv_speed,
    _parse_vainfo_driver,
    classify_client_route,
    decode_browser_user_agent,
    evaluate_jellyfin_report,
    load_device_cache,
    normalize_hostname,
    run_jellyfin_deep_check,
    save_device_cache,
)


def _make_mock_raw(
    container_found: bool = True,
    container_status: str = "running",
    container_health: str = "healthy",
    restart_count: int = 0,
    oom_killed: bool = False,
    mem_limit_bytes: int = 536870912,  # 512MB
    mem_usage_bytes: int = 268435456,  # 256MB
    render_device_code: int = 0,
    render_device_out: str = "crw-rw---- 1 root video 226, 128 /dev/dri/renderD128",
    vainfo_code: int = 0,
    vainfo_out: str = "Trying to open /usr/lib/jellyfin-ffmpeg/lib/dri/iHD_drv_video.so\nva_openDriver() returns 0",
    qsv_test_code: int = 0,
    qsv_test_out: str = "frame=30 fps=0.0 speed=9.72x elapsed=0:00:00.09",
    media_check_code: int = 0,
    media_dirs: list[str] | None = None,
    api_auth_code: int = 200,
    api_auth_token: str | None = "mock_token_123",
    item_counts: dict[str, int] | None = None,
    sessions: list[dict] | None = None,
    devices: list[dict] | None = None,
    activity_entries: list[dict] | None = None,
) -> JellyfinRawData:
    raw = JellyfinRawData()
    raw.container_found = container_found
    raw.container_status = container_status
    raw.container_health = container_health
    raw.restart_count = restart_count
    raw.oom_killed = oom_killed
    raw.mem_limit_bytes = mem_limit_bytes
    raw.mem_usage_bytes = mem_usage_bytes
    raw.render_device_code = render_device_code
    raw.render_device_out = render_device_out
    raw.vainfo_code = vainfo_code
    raw.vainfo_out = vainfo_out
    raw.qsv_test_code = qsv_test_code
    raw.qsv_test_out = qsv_test_out
    raw.media_check_code = media_check_code
    raw.media_dirs = media_dirs if media_dirs is not None else ["movies", "tv", "audiobooks"]
    raw.api_auth_code = api_auth_code
    raw.api_auth_token = api_auth_token
    raw.item_counts = (
        item_counts if item_counts is not None else {"MovieCount": 150, "SeriesCount": 25, "ItemCount": 1500}
    )
    raw.sessions = sessions if sessions is not None else []
    raw.devices = devices if devices is not None else []
    raw.activity_entries = activity_entries if activity_entries is not None else []
    raw.version = "v10.10.6"
    return raw


def test_jellyfin_happy_path() -> None:
    conn = TargetConnection("server.lan", "192.168.1.10", "lan", "Direct LAN")
    raw = _make_mock_raw()
    report = evaluate_jellyfin_report(raw, conn)

    assert report.all_passed is True
    assert report.qsv_speed == "9.72x"
    assert report.memory is not None
    assert report.memory.usage_bytes == 268435456
    assert report.memory.limit_bytes == 536870912
    assert report.memory.usage_percent == pytest.approx(50.0)

    check_names = [c.name for c in report.checks]
    assert "Inspection Route" in check_names
    assert "Container Lifecycle" in check_names
    assert "Memory Cgroup & OOM Safety" in check_names
    assert "GPU Device Node" in check_names
    assert "VA-API Driver Pipeline" in check_names
    assert "Intel QuickSync (QSV)" in check_names
    assert "Media Storage Mount" in check_names
    assert "Jellyfin API Auth" in check_names
    assert "Media Catalog" in check_names
    assert "Playback Sessions" in check_names
    assert "Connected Clients (24h)" in check_names
    assert "Playback Activity (24h)" in check_names


def test_jellyfin_failure_container_stopped() -> None:
    raw = _make_mock_raw(container_found=False, container_status="exited")
    report = evaluate_jellyfin_report(raw)

    assert report.all_passed is False
    c_check = next(c for c in report.checks if c.name == "Container Lifecycle")
    assert c_check.passed is False
    assert "not found" in c_check.details


def test_jellyfin_failure_oom_killed() -> None:
    raw = _make_mock_raw(oom_killed=True)
    report = evaluate_jellyfin_report(raw)

    assert report.all_passed is False
    mem_check = next(c for c in report.checks if c.name == "Memory Cgroup & OOM Safety")
    assert mem_check.passed is False
    assert "OOM-KILLED" in mem_check.details


def test_jellyfin_warning_restart_count() -> None:
    raw = _make_mock_raw(restart_count=4)
    report = evaluate_jellyfin_report(raw)

    mem_check = next(c for c in report.checks if c.name == "Memory Cgroup & OOM Safety")
    assert mem_check.warning is True
    assert "4 container restarts" in mem_check.details
    assert report.all_passed is True


def test_jellyfin_warning_memory_threshold() -> None:
    # 500MB / 512MB = ~97.6% (above 90% threshold)
    raw = _make_mock_raw(mem_usage_bytes=524288000, mem_limit_bytes=536870912)
    report = evaluate_jellyfin_report(raw)

    mem_check = next(c for c in report.checks if c.name == "Memory Cgroup & OOM Safety")
    assert mem_check.warning is True
    assert "97.7%" in mem_check.details


def test_jellyfin_failure_gpu_device_missing() -> None:
    raw = _make_mock_raw(render_device_code=2, render_device_out="ls: /dev/dri/renderD128: No such file")
    report = evaluate_jellyfin_report(raw)

    assert report.all_passed is False
    gpu_check = next(c for c in report.checks if c.name == "GPU Device Node")
    assert gpu_check.passed is False
    assert "missing or inaccessible" in gpu_check.details


def test_jellyfin_failure_vainfo_driver_failed() -> None:
    raw = _make_mock_raw(
        vainfo_code=1,
        vainfo_out="vaInitialize failed with error code -1 (unknown libva error)",
    )
    report = evaluate_jellyfin_report(raw)

    assert report.all_passed is False
    va_check = next(c for c in report.checks if c.name == "VA-API Driver Pipeline")
    assert va_check.passed is False
    assert "driver init failed" in va_check.details


def test_jellyfin_failure_qsv_transcode_failed() -> None:
    raw = _make_mock_raw(
        qsv_test_code=1,
        qsv_test_out="Error initializing MFX session: device creation failed",
    )
    report = evaluate_jellyfin_report(raw)

    assert report.all_passed is False
    qsv_check = next(c for c in report.checks if c.name == "Intel QuickSync (QSV)")
    assert qsv_check.passed is False
    assert "transcode test failed" in qsv_check.details


def test_jellyfin_failure_media_mount_unreadable() -> None:
    raw = _make_mock_raw(
        media_check_code=1,
        media_dirs=[],
    )
    report = evaluate_jellyfin_report(raw)

    assert report.all_passed is False
    media_check = next(c for c in report.checks if c.name == "Media Storage Mount")
    assert media_check.passed is False
    assert "/mnt/mango/media missing or unreadable" in media_check.details


def test_jellyfin_failure_api_auth_failed() -> None:
    raw = _make_mock_raw(
        api_auth_code=401,
        api_auth_token=None,
    )
    report = evaluate_jellyfin_report(raw)

    assert report.all_passed is False
    auth_check = next(c for c in report.checks if c.name == "Jellyfin API Auth")
    assert auth_check.passed is False
    assert "HTTP 401" in auth_check.details


def test_jellyfin_playback_sessions_parsing() -> None:
    sample_sessions = [
        {
            "UserName": "username",
            "Client": "Jellyfin Web",
            "DeviceName": "Firefox on Linux",
            "NowPlayingItem": {
                "Name": "Episode 1",
                "SeriesName": "Severance",
            },
            "PlayState": {
                "PlayMethod": "Transcode",
            },
            "TranscodingInfo": {
                "TranscodeReasons": ["ContainerNotSupported", "AudioCodecNotSupported"],
                "Bitrate": 15000000,
            },
        }
    ]
    raw = _make_mock_raw(sessions=sample_sessions)
    report = evaluate_jellyfin_report(raw)

    assert len(report.active_sessions) == 1
    sess = report.active_sessions[0]
    assert sess.username == "username"
    assert sess.media_title == "Severance - Episode 1"
    assert sess.play_method == "Transcode"
    assert "ContainerNotSupported" in sess.transcode_reasons

    sess_check = next(c for c in report.checks if c.name == "Playback Sessions")
    assert sess_check.passed is True
    assert "Severance - Episode 1" in sess_check.details


def test_helper_parsers() -> None:
    assert _parse_qsv_speed("frame=30 fps=0.0 speed=8.5x elapsed=0:00:00.1") == "8.5x"
    assert _parse_qsv_speed("no speed metric found") == "active"

    assert "Intel iHD driver" in _parse_vainfo_driver("Trying to open iHD_drv_video.so")
    assert "Intel i965 driver" in _parse_vainfo_driver("Loaded i965 driver")


@pytest.mark.anyio
async def test_run_jellyfin_deep_check_with_mock_context() -> None:
    ctx = MagicMock(spec=StatusContext)
    ctx.no_docker = False
    ctx.username = "username"
    ctx.password = "secret"
    ctx.connection = TargetConnection("localhost", "127.0.0.1", "local", "On-Device")

    c_mock = MagicMock()
    c_mock.attrs = {
        "State": {"Status": "running", "Health": {"Status": "healthy"}, "RestartCount": 0, "OOMKilled": False},
        "HostConfig": {"Memory": 536870912},
    }

    async def _get_c(name: str, full: bool = False) -> MagicMock:
        return c_mock

    async def _exec_c(name: str, cmd: str | list[str]) -> tuple[int, str]:
        if "renderD128" in str(cmd) and "vainfo" not in str(cmd):
            return 0, "crw-rw---- 1 root video 226, 128 /dev/dri/renderD128"
        if "vainfo" in str(cmd):
            return 0, "va_openDriver() returns 0"
        if "ffmpeg" in str(cmd):
            return 0, "speed=9.0x elapsed=0:00:00.1"
        if "memory.current" in str(cmd):
            return 0, "200000000"
        if "/mnt/mango/media" in str(cmd):
            return 0, "movies\ntv"
        return 0, ""

    ctx.get_container = _get_c
    ctx.exec_container = _exec_c
    ctx.get_container_version = AsyncMock(return_value="v10.10.6")
    ctx.base_url = MagicMock(return_value="http://127.0.0.1:8096")
    ctx.http_timeout = 5.0

    # With mocked HTTP we verify raw gathering runs without errors
    report = await run_jellyfin_deep_check(ctx)
    assert report.connection == ctx.connection
    assert report.memory is not None
    assert report.memory.usage_bytes == 200000000


def test_jellyfin_connected_clients_parsing() -> None:
    from whenever import Instant, hours, minutes

    now = Instant.now()
    recent_iso = (now - minutes(10)).format_iso()
    old_iso = (now - hours(48)).format_iso()

    devices = [
        {
            "Name": "iPad",
            "AppName": "Infuse-Direct",
            "AppVersion": "8.5.9",
            "LastUserName": "alice",
            "DateLastActivity": recent_iso,
        },
        {
            "Name": "homelab-status",
            "AppName": "StatusCheck",
            "AppVersion": "1.0.0",
            "LastUserName": "bot",
            "DateLastActivity": recent_iso,
        },
        {
            "Name": "Firefox",
            "AppName": "Jellyfin Web",
            "AppVersion": "12.4.0",
            "LastUserName": "alice",
            "DateLastActivity": old_iso,
        },
    ]

    raw = _make_mock_raw(devices=devices)
    report = evaluate_jellyfin_report(raw)

    # StatusCheck should be filtered out, and old device (>24h) excluded from connected_clients_24h
    assert len(report.connected_clients_24h) == 1
    client = report.connected_clients_24h[0]
    assert client.app_name == "Infuse-Direct"
    assert client.device_name == "iPad"
    assert client.username == "alice"

    check = next(c for c in report.checks if c.name == "Connected Clients (24h)")
    assert check.passed is True
    assert "Infuse-Direct on iPad" in check.details


def test_jellyfin_playback_history_and_24h_activity() -> None:
    from whenever import Instant, hours, seconds

    now = Instant.now()
    d1 = (now - hours(1)).format_iso()
    d2 = (now - hours(1) - seconds(30)).format_iso()  # duplicate within 5m
    d3 = (now - hours(5)).format_iso()
    d4 = (now - hours(72)).format_iso()  # older than 24h

    devices = [
        {"Name": "iPad", "AppName": "Infuse-Direct", "DateLastActivity": d1},
        {"Name": "Living Room TV", "AppName": "Android TV", "DateLastActivity": d3},
    ]

    activity_entries = [
        {
            "Type": "VideoPlayback",
            "Name": "alice is playing Severance - Episode 1 on iPad",
            "Date": d1,
            "ItemId": "item_1",
        },
        {
            "Type": "VideoPlayback",
            "Name": "alice is playing Severance - Episode 1 on iPad",
            "Date": d2,
            "ItemId": "item_1",
        },
        {
            "Type": "VideoPlayback",
            "Name": "alice is playing Silo - Episode 2 on Living Room TV",
            "Date": d3,
            "ItemId": "item_2",
        },
        {
            "Type": "VideoPlayback",
            "Name": "alice is playing Ted Lasso - Episode 3 on iPad",
            "Date": d4,
            "ItemId": "item_3",
        },
    ]

    raw = _make_mock_raw(devices=devices, activity_entries=activity_entries)
    report = evaluate_jellyfin_report(raw)

    # d2 should be deduplicated with d1
    assert len(report.recent_playback) == 3
    assert report.recent_playback[0].media_title == "Severance - Episode 1"
    assert report.recent_playback[0].client_name == "Infuse-Direct"
    assert report.recent_playback[1].media_title == "Silo - Episode 2"
    assert report.recent_playback[1].client_name == "Android TV"
    assert report.recent_playback[2].media_title == "Ted Lasso - Episode 3"

    # Only d1 and d3 are within the last 24h
    assert report.plays_last_24h_count == 2
    assert "Infuse-Direct (iPad)" in report.plays_by_client_24h
    assert report.plays_by_client_24h["Infuse-Direct (iPad)"] == 1
    assert report.plays_by_client_24h["Android TV (Living Room TV)"] == 1

    check = next(c for c in report.checks if c.name == "Playback Activity (24h)")
    assert check.passed is True
    assert "2 item(s) played" in check.details


def test_format_relative_time() -> None:
    from whenever import Instant, hours, minutes

    now = Instant.now()
    assert _format_relative_time(now, now) == "just now"
    assert _format_relative_time(now - minutes(5), now) == "5m ago"
    assert _format_relative_time(now - hours(2) - minutes(10), now) == "2h 10m ago"
    assert _format_relative_time(now - hours(77), now) == "3d 5h ago"
    assert _format_relative_time(now - hours(14 * 24), now) == "14d ago"


def test_format_playback_time() -> None:
    from whenever import SYSTEM_TZ, Instant, hours, minutes

    now = Instant.now()
    local_now = now.to_tz(SYSTEM_TZ)
    expected_hm = local_now.format("ii:mm aa").lower()

    # Same timestamp -> "HH:mm (am/pm) • now"
    assert _format_playback_time(now, now) == f"{expected_hm} • now"

    # 5 minutes ago
    five_min_ago = now - minutes(5)
    local_five = five_min_ago.to_tz(SYSTEM_TZ)
    expected_five = local_five.format("ii:mm aa").lower()
    assert _format_playback_time(five_min_ago, now) == f"{expected_five} • 5 minutes ago"

    # 2 hours ago
    two_hours_ago = now - hours(2)
    local_two = two_hours_ago.to_tz(SYSTEM_TZ)
    expected_two = local_two.format("ii:mm aa").lower()
    assert _format_playback_time(two_hours_ago, now) == f"{expected_two} • 2 hours ago"


def test_classify_client_route() -> None:
    assert classify_client_route("100.123.98.28") == ("Tailscale", "🔒 Tailscale")
    assert classify_client_route("100.64.0.1") == ("Tailscale", "🔒 Tailscale")
    assert classify_client_route("192.168.8.144") == ("LAN", "🟢 LAN")
    assert classify_client_route("10.0.0.5") == ("LAN", "🟢 LAN")
    assert classify_client_route("172.20.0.5") == ("LAN", "🟢 LAN")
    assert classify_client_route("127.0.0.1") == ("Local", "🏠 Local")
    assert classify_client_route("::1") == ("Local", "🏠 Local")
    assert classify_client_route("8.8.8.8") == ("WAN", "🌐 WAN")
    assert classify_client_route(None) == ("Unknown", "")
    assert classify_client_route("not_an_ip") == ("Unknown", "")


def test_decode_browser_user_agent() -> None:
    import base64

    # Windows 11 Firefox
    ua_ff = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:157.0) Gecko/20100101 Firefox/157.0|12345"
    id_ff = base64.b64encode(ua_ff.encode()).decode()
    assert decode_browser_user_agent(id_ff) == "Firefox (Windows 11)"

    # macOS Safari
    ua_safari = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15"
    id_safari = base64.b64encode(ua_safari.encode()).decode()
    assert decode_browser_user_agent(id_safari) == "Safari (macOS)"

    # Linux Chrome
    ua_chrome = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"
    id_chrome = base64.b64encode(ua_chrome.encode()).decode()
    assert decode_browser_user_agent(id_chrome) == "Chrome (Linux)"

    # Native App UUID
    assert decode_browser_user_agent("B04DB671-261A-41A5-B87B-1FEB3534047F") is None
    assert decode_browser_user_agent(None) is None
    assert decode_browser_user_agent("short") is None


def test_normalize_hostname() -> None:
    assert normalize_hostname("sp11.lan") == "sp11"
    assert normalize_hostname("sp11.tail4f594f.ts.net") == "sp11"
    assert normalize_hostname("Keifukus-iPad-Pro-11.local") == "Keifukus-iPad-Pro-11"
    assert normalize_hostname("m70q.localdomain") == "m70q"
    assert normalize_hostname("myhost") == "myhost"
    assert normalize_hostname(None) is None
    assert normalize_hostname("") is None


def test_custom_playback_history_limit() -> None:
    from whenever import Instant

    now = Instant.now()
    activity_entries = [
        {
            "Type": "VideoPlayback",
            "Name": f"user is playing Episode {i} on TV",
            "Date": now.format_iso(),
            "ItemId": f"item_{i}",
        }
        for i in range(15)
    ]
    raw = _make_mock_raw(activity_entries=activity_entries)

    # Test default limit (10)
    report_default = evaluate_jellyfin_report(raw)
    assert len(report_default.recent_playback) == 10

    # Test custom limit (5)
    report_5 = evaluate_jellyfin_report(raw, history_limit=5)
    assert len(report_5.recent_playback) == 5

    # Test custom limit (15)
    report_15 = evaluate_jellyfin_report(raw, history_limit=15)
    assert len(report_15.recent_playback) == 15


def test_connected_clients_route_and_platform_enrichment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from whenever import Instant

    # Mock device cache to tmp_path
    monkeypatch.setattr(
        "services.jellyfin._get_device_cache_path",
        lambda: tmp_path / "jellyfin_device_routes.json",
    )

    # Test explicit save_device_cache and load_device_cache
    save_device_cache({"initial": {"endpoint": "100.1.2.3", "hostname": "initial-host"}})
    assert load_device_cache()["initial"]["hostname"] == "initial-host"

    now = Instant.now()
    import base64

    ua_ff = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:157.0) Gecko/20100101 Firefox/157.0"
    dev_id_ff = base64.b64encode(ua_ff.encode()).decode()

    devices = [
        {
            "Name": "Firefox",
            "Id": dev_id_ff,
            "AppName": "Jellyfin Web",
            "DateLastActivity": now.format_iso(),
            "LastUserName": "ehtesh",
        },
        {
            "Name": "iPad",
            "Id": "B04DB671-261A-41A5-B87B-1FEB3534047F",
            "AppName": "VidHub",
            "DateLastActivity": now.format_iso(),
            "LastUserName": "ehtesh",
            "AppVersion": "3.1.0",
        },
    ]

    sessions = [
        {
            "DeviceId": dev_id_ff,
            "RemoteEndPoint": "100.123.98.28",
        },
        {
            "DeviceId": "B04DB671-261A-41A5-B87B-1FEB3534047F",
            "RemoteEndPoint": "192.168.8.135",
        },
    ]

    # Mock hostname lookup so tests don't rely on live DNS
    def mock_resolve(ip: str) -> str | None:
        if ip == "100.123.98.28":
            return "sp11"
        if ip == "192.168.8.135":
            return "Keifukus-iPad-Pro-11"
        return None

    monkeypatch.setattr("services.jellyfin._resolve_ip_hostname", mock_resolve)

    raw = _make_mock_raw(devices=devices, sessions=sessions)
    report = evaluate_jellyfin_report(raw)

    assert len(report.connected_clients_24h) == 2
    c_web = next(c for c in report.connected_clients_24h if c.app_name == "Jellyfin Web")
    assert c_web.device_name == "sp11"
    assert c_web.platform == "Firefox (Windows 11)"
    assert c_web.route == "Tailscale"
    assert c_web.route_badge == "🔒 Tailscale"
    assert c_web.endpoint == "100.123.98.28"

    c_vid = next(c for c in report.connected_clients_24h if c.app_name == "VidHub")
    assert c_vid.device_name == "Keifukus-iPad-Pro-11"
    assert c_vid.route == "LAN"
    assert c_vid.route_badge == "🟢 LAN"
    assert c_vid.endpoint == "192.168.8.135"

    # Verify cache was written
    cache = load_device_cache()
    assert dev_id_ff in cache
    assert cache[dev_id_ff]["hostname"] == "sp11"
    assert cache[dev_id_ff]["route"] == "Tailscale"
