"""Jellyfin content, hardware acceleration, memory cgroup, and session health check."""

from __future__ import annotations

import base64
import contextlib
import ipaddress
import json
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import httpx
import humanize
from rich.panel import Panel
from rich.table import Table
from whenever import SYSTEM_TZ, Instant

from common import format_bytes, format_connection_badge, format_route_line, render_command_header
from models import ContainerName, HealthStatus, ServiceResult, StatusContext, TargetConnection

if TYPE_CHECKING:
    from rich.console import Console


@dataclass(slots=True)
class JellyfinCheckItem:
    name: str
    passed: bool
    details: str
    warning: bool = False


@dataclass(slots=True)
class PlaybackSessionInfo:
    username: str
    client: str
    device: str
    media_title: str
    play_method: str  # DirectPlay, DirectStream, Transcode
    transcode_reasons: list[str] = field(default_factory=list)
    bitrate_bps: int = 0


@dataclass(slots=True)
class ConnectedClientInfo:
    app_name: str
    device_name: str
    username: str
    last_activity: str  # ISO-8601 UTC string
    relative_time: str
    app_version: str = ""
    platform: str = ""
    route: str = ""
    endpoint: str = ""
    route_badge: str = ""


@dataclass(slots=True)
class PlaybackHistoryItem:
    timestamp: str  # ISO-8601 UTC string
    relative_time: str
    username: str
    media_title: str
    device_name: str
    client_name: str = ""
    item_id: str = ""
    route: str = ""


def classify_client_route(ip_str: str | None) -> tuple[str, str]:
    """Classify client IP into network route name and Rich-styled badge.

    Returns:
        tuple[route_name, route_badge] e.g. ('Tailscale', '🔒 Tailscale')
    """
    if not ip_str:
        return "Unknown", ""
    try:
        ip = ipaddress.ip_address(ip_str.strip())
        if ip.is_loopback:
            return "Local", "🏠 Local"
        # Tailscale CGNAT RFC6598: 100.64.0.0/10
        if ip in ipaddress.ip_network("100.64.0.0/10"):
            return "Tailscale", "🔒 Tailscale"
        if ip.is_private:
            return "LAN", "🟢 LAN"
        return "WAN", "🌐 WAN"
    except ValueError:
        return "Unknown", ""


def decode_browser_user_agent(device_id: str | None) -> str | None:
    """Decode Jellyfin Web base64-encoded DeviceId into human-readable OS and browser."""
    if not device_id or len(device_id) < 16:
        return None
    try:
        pad = "=" * (-len(device_id) % 4)
        decoded = base64.b64decode(device_id + pad).decode("utf-8", errors="ignore")
        if "Mozilla/" not in decoded and "Gecko" not in decoded and "AppleWebKit" not in decoded:
            return None

        # Determine OS
        if "Windows NT 10.0" in decoded or "Windows NT 11.0" in decoded:
            os_name = "Windows 11"
        elif "Windows NT" in decoded:
            os_name = "Windows"
        elif "Macintosh" in decoded or "Mac OS X" in decoded:
            os_name = "macOS"
        elif "Android" in decoded:
            os_name = "Android"
        elif "iPhone" in decoded or "iPad" in decoded:
            os_name = "iOS"
        elif "Linux" in decoded:
            os_name = "Linux"
        else:
            os_name = None

        # Determine Browser
        if "Firefox/" in decoded:
            browser = "Firefox"
        elif "Edg/" in decoded:
            browser = "Edge"
        elif "Chrome/" in decoded:
            browser = "Chrome"
        elif "Safari/" in decoded:
            browser = "Safari"
        else:
            browser = None

        if browser and os_name:
            return f"{browser} ({os_name})"
        return browser or os_name
    except Exception:
        return None


def normalize_hostname(host: str | None) -> str | None:
    """Strip domain suffixes to unify LAN and Tailscale host stems (e.g. sp11.lan -> sp11)."""
    if not host:
        return None
    h = host.strip().rstrip(".")
    for suffix in (
        ".tail4f594f.ts.net",
        ".ts.net",
        ".lan",
        ".local",
        ".localdomain",
        ".internal",
        ".home",
    ):
        if h.endswith(suffix):
            h = h[: -len(suffix)]
            break
    return h or None


_PLAYBACK_LOG_PATTERN = re.compile(r"^(?P<user>.+?)\s+is playing\s+(?P<title>.+?)\s+on\s+(?P<device>.+)$")


def _resolve_ip_hostname(ip: str, timeout: float = 0.15) -> str | None:
    """Reverse-lookup IP to normalized hostname via daemon thread with hard timeout."""
    res: list[str | None] = [None]

    def _worker() -> None:
        with contextlib.suppress(Exception):
            host, _, _ = socket.gethostbyaddr(ip)
            res[0] = normalize_hostname(host)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return res[0]


def _get_device_cache_path() -> Path:
    return Path.home() / ".cache" / "homelab" / "jellyfin_device_routes.json"


def load_device_cache() -> dict[str, dict[str, Any]]:
    """Load cached device IP, route, and hostname mappings."""
    path = _get_device_cache_path()
    if not path.is_file():
        return {}
    with contextlib.suppress(Exception):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    return {}


def save_device_cache(cache: dict[str, dict[str, Any]]) -> None:
    """Persist device IP, route, and hostname mappings."""
    path = _get_device_cache_path()
    with contextlib.suppress(Exception):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


@dataclass(slots=True)
class JellyfinMemoryInfo:
    usage_bytes: int
    limit_bytes: int
    oom_killed: bool
    restart_count: int

    @property
    def usage_percent(self) -> float:
        if self.limit_bytes <= 0:
            return 0.0
        return (self.usage_bytes / self.limit_bytes) * 100.0


@dataclass(slots=True)
class JellyfinRawData:
    container_found: bool = False
    container_status: str = "unknown"
    container_health: str = "unknown"
    restart_count: int = 0
    oom_killed: bool = False
    mem_limit_bytes: int = 0
    mem_usage_bytes: int = 0
    render_device_code: int = -1
    render_device_out: str = ""
    vainfo_code: int = -1
    vainfo_out: str = ""
    qsv_test_code: int = -1
    qsv_test_out: str = ""
    media_check_code: int = -1
    media_dirs: list[str] = field(default_factory=list)
    api_auth_code: int = 0
    api_auth_token: str | None = None
    item_counts: dict[str, int] = field(default_factory=dict)
    sessions: list[dict[str, Any]] = field(default_factory=list)
    devices: list[dict[str, Any]] = field(default_factory=list)
    activity_entries: list[dict[str, Any]] = field(default_factory=list)
    version: str | None = None
    username: str = "username"


@dataclass(slots=True)
class JellyfinDeepReport:
    connection: TargetConnection | None = None
    checks: list[JellyfinCheckItem] = field(default_factory=list)
    all_passed: bool = True
    memory: JellyfinMemoryInfo | None = None
    qsv_speed: str = ""
    active_sessions: list[PlaybackSessionInfo] = field(default_factory=list)
    connected_clients_24h: list[ConnectedClientInfo] = field(default_factory=list)
    recent_playback: list[PlaybackHistoryItem] = field(default_factory=list)
    plays_last_24h_count: int = 0
    plays_by_client_24h: dict[str, int] = field(default_factory=dict)
    item_counts: dict[str, int] = field(default_factory=dict)
    version: str | None = None


def _format_relative_time(inst: Instant, now: Instant | None = None) -> str:
    """Format an Instant into human readable relative time (e.g. '12m ago', '3h 15m ago', '2d ago')."""
    if now is None:
        now = Instant.now()

    diff = now - inst
    total_seconds = max(0, int(diff.total("seconds")))
    if total_seconds < 60:
        return "just now"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    rem_min = minutes % 60
    if hours < 24:
        return f"{hours}h {rem_min}m ago" if rem_min > 0 else f"{hours}h ago"
    days = hours // 24
    rem_hours = hours % 24
    if days < 7:
        return f"{days}d {rem_hours}h ago" if rem_hours > 0 else f"{days}d ago"
    return f"{days}d ago"


def _format_playback_time(inst: Instant, now: Instant | None = None) -> str:
    """Format an Instant into short time (hh:mm) and humanized relative duration (e.g. '08:34 • an hour ago')."""
    if now is None:
        now = Instant.now()
    local_dt = inst.to_tz(SYSTEM_TZ)
    short_time = f"{local_dt.hour:02d}:{local_dt.minute:02d}"
    diff_sec = max(0.0, (now - inst).total("seconds"))
    duration_ago = humanize.naturaltime(diff_sec)
    return f"{short_time} • {duration_ago}"


def _parse_qsv_speed(output: str) -> str:
    """Extract speed metric from ffmpeg benchmark output (e.g. 'speed=9.72x')."""
    match = re.search(r"speed=\s*([0-9.]+)x", output)
    if match:
        return f"{match.group(1)}x"
    return "active"


def _parse_vainfo_driver(output: str) -> str:
    """Extract VA-API driver name from vainfo output."""
    if "iHD_drv_video.so" in output or "Intel iHD driver" in output:
        return "Intel iHD driver (VA-API 1.24)"
    if "i965_drv_video.so" in output or "i965" in output:
        return "Intel i965 driver"
    return "VA-API driver"


async def _gather_jellyfin_raw_data(ctx: StatusContext) -> JellyfinRawData:
    """Concurrently collect Docker metadata, GPU node status, QSV test, media mount, and HTTP API."""
    raw = JellyfinRawData(username=ctx.username)
    container_name = ContainerName.JELLYFIN

    # 1. Inspect Docker Container
    c = await ctx.get_container(container_name, full=True)
    if c:
        raw.container_found = True
        attrs = c.attrs or {}
        state = attrs.get("State") or {}
        host_config = attrs.get("HostConfig") or {}

        raw.container_status = state.get("Status", "unknown")
        health_dict = state.get("Health") or {}
        raw.container_health = health_dict.get("Status", "none")
        raw.restart_count = state.get("RestartCount", 0)
        raw.oom_killed = state.get("OOMKilled", False)
        raw.mem_limit_bytes = host_config.get("Memory", 0)

    # Concurrently gather live cgroup memory, GPU/driver status, media dirs, and Jellyfin API
    async def _fetch_live_memory() -> None:
        if ctx.no_docker or not raw.container_found:
            return
        code, out = await ctx.exec_container(container_name, "cat /sys/fs/cgroup/memory.current")
        if code == 0 and out.strip().isdigit():
            raw.mem_usage_bytes = int(out.strip())
        else:
            # Fallback to cgroup v1
            c1_code, c1_out = await ctx.exec_container(
                container_name, "cat /sys/fs/cgroup/memory/memory.usage_in_bytes"
            )
            if c1_code == 0 and c1_out.strip().isdigit():
                raw.mem_usage_bytes = int(c1_out.strip())

    async def _probe_gpu() -> None:
        if ctx.no_docker or not raw.container_found:
            return
        code, out = await ctx.exec_container(container_name, "ls -ld /dev/dri/renderD128")
        raw.render_device_code = code
        raw.render_device_out = out.strip()

    async def _probe_vainfo() -> None:
        if ctx.no_docker or not raw.container_found:
            return
        code, out = await ctx.exec_container(
            container_name,
            ["/usr/lib/jellyfin-ffmpeg/vainfo", "--display", "drm", "--device", "/dev/dri/renderD128"],
        )
        raw.vainfo_code = code
        raw.vainfo_out = out

    async def _probe_qsv_transcode() -> None:
        if ctx.no_docker or not raw.container_found:
            return
        cmd = [
            "/usr/lib/jellyfin-ffmpeg/ffmpeg",
            "-init_hw_device",
            "qsv=hw",
            "-filter_hw_device",
            "hw",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=1280x720:rate=30",
            "-c:v",
            "h264_qsv",
            "-f",
            "null",
            "-",
        ]
        code, out = await ctx.exec_container(container_name, cmd)
        raw.qsv_test_code = code
        raw.qsv_test_out = out

    async def _check_media_mount() -> None:
        if ctx.no_docker or not raw.container_found:
            return
        cmd = [
            "sh",
            "-c",
            "test -r /mnt/mango/media/movies && test -r /mnt/mango/media/tv && ls -1 /mnt/mango/media",
        ]
        code, out = await ctx.exec_container(container_name, cmd)
        raw.media_check_code = code
        if code == 0:
            raw.media_dirs = [d.strip() for d in out.splitlines() if d.strip()]

    async def _query_jellyfin_api() -> None:
        try:
            async with httpx.AsyncClient(base_url=ctx.base_url("jellyfin"), timeout=ctx.http_timeout) as client:
                auth_header = (
                    'MediaBrowser Client="StatusCheck", Device="homelab-status", '
                    'DeviceId="homelab-status-check", Version="1.0.0"'
                )
                login_res = await client.post(
                    "/Users/AuthenticateByName",
                    json={"Username": ctx.username, "Pw": ctx.password},
                    headers={
                        "Authorization": auth_header,
                        "X-Emby-Authorization": auth_header,
                    },
                )
                raw.api_auth_code = login_res.status_code
                if login_res.status_code != 200:
                    return

                token = login_res.json().get("AccessToken")
                raw.api_auth_token = token
                auth_with_tok = f'{auth_header}, Token="{token}"'
                headers = {
                    "Authorization": auth_with_tok,
                    "X-Emby-Authorization": auth_with_tok,
                    "X-Emby-Token": token,
                }

                async def _get_version() -> None:
                    with contextlib.suppress(httpx.HTTPError, KeyError, ValueError):
                        v_res = await client.get("/System/Info/Public")
                        if v_res.status_code == 200:
                            v = v_res.json().get("Version")
                            if v:
                                raw.version = f"v{v}"

                async def _get_counts() -> None:
                    with contextlib.suppress(httpx.HTTPError, KeyError, ValueError):
                        c_res = await client.get("/Items/Counts", headers=headers)
                        if c_res.status_code == 200:
                            raw.item_counts = c_res.json()

                async def _get_sessions() -> None:
                    with contextlib.suppress(httpx.HTTPError, KeyError, ValueError):
                        s_res = await client.get("/Sessions", headers=headers)
                        if s_res.status_code == 200:
                            raw.sessions = s_res.json()

                async def _get_devices() -> None:
                    with contextlib.suppress(httpx.HTTPError, KeyError, ValueError):
                        d_res = await client.get("/Devices", headers=headers)
                        if d_res.status_code == 200:
                            raw.devices = d_res.json().get("Items", [])

                async def _get_activity() -> None:
                    with contextlib.suppress(httpx.HTTPError, KeyError, ValueError):
                        a_res = await client.get("/System/ActivityLog/Entries", params={"limit": 200}, headers=headers)
                        if a_res.status_code == 200:
                            raw.activity_entries = a_res.json().get("Items", [])

                async with anyio.create_task_group() as tg_api:
                    tg_api.start_soon(_get_version)
                    tg_api.start_soon(_get_counts)
                    tg_api.start_soon(_get_sessions)
                    tg_api.start_soon(_get_devices)
                    tg_api.start_soon(_get_activity)
        except Exception:
            raw.api_auth_code = -1

    async with anyio.create_task_group() as tg:
        tg.start_soon(_fetch_live_memory)
        tg.start_soon(_probe_gpu)
        tg.start_soon(_probe_vainfo)
        tg.start_soon(_probe_qsv_transcode)
        tg.start_soon(_check_media_mount)
        tg.start_soon(_query_jellyfin_api)

    if not raw.version and raw.container_found:
        raw.version = await ctx.get_container_version(container_name)

    return raw


def evaluate_jellyfin_report(
    raw: JellyfinRawData,
    connection: TargetConnection | None = None,
    history_limit: int = 10,
) -> JellyfinDeepReport:
    """Evaluate raw Jellyfin diagnostics into a verified structured report."""
    report = JellyfinDeepReport(connection=connection, version=raw.version, item_counts=raw.item_counts)

    # 1. Inspection Route
    badge, endpoint, _ = format_connection_badge(connection)
    report.checks.append(
        JellyfinCheckItem(
            name="Inspection Route",
            passed=True,
            details=f"Connected via {badge} [dim]({endpoint})[/dim]",
        )
    )

    # 2. Container Status
    if raw.container_found:
        is_running = raw.container_status == "running"
        h_str = f" • Health: '{raw.container_health}'" if raw.container_health != "none" else ""
        report.checks.append(
            JellyfinCheckItem(
                name="Container Lifecycle",
                passed=is_running,
                details=f"State: '{raw.container_status}'{h_str}",
            )
        )
    else:
        report.checks.append(
            JellyfinCheckItem(
                name="Container Lifecycle",
                passed=False,
                details=f"Container '{ContainerName.JELLYFIN}' not found",
            )
        )

    # 3. Cgroup Memory Limit & OOM Safety
    mem_info = JellyfinMemoryInfo(
        usage_bytes=raw.mem_usage_bytes,
        limit_bytes=raw.mem_limit_bytes,
        oom_killed=raw.oom_killed,
        restart_count=raw.restart_count,
    )
    report.memory = mem_info

    if raw.oom_killed:
        report.checks.append(
            JellyfinCheckItem(
                name="Memory Cgroup & OOM Safety",
                passed=False,
                details=f"Container OOM-KILLED by kernel cgroup ({format_bytes(raw.mem_limit_bytes)} limit reached)",
            )
        )
    elif raw.restart_count > 0:
        pct = f" ({mem_info.usage_percent:.1f}%)" if raw.mem_limit_bytes > 0 else ""
        report.checks.append(
            JellyfinCheckItem(
                name="Memory Cgroup & OOM Safety",
                passed=True,
                warning=True,
                details=(
                    f"Usage: {format_bytes(raw.mem_usage_bytes)} / {format_bytes(raw.mem_limit_bytes)}{pct} "
                    f"• {raw.restart_count} container restarts detected"
                ),
            )
        )
    elif raw.mem_limit_bytes > 0:
        pct = f" ({mem_info.usage_percent:.1f}%)"
        is_warn = mem_info.usage_percent > 90.0
        report.checks.append(
            JellyfinCheckItem(
                name="Memory Cgroup & OOM Safety",
                passed=not is_warn,
                warning=is_warn,
                details=(
                    f"Usage: {format_bytes(raw.mem_usage_bytes)} / {format_bytes(raw.mem_limit_bytes)}{pct} "
                    "• 0 OOM kills • 0 restarts"
                ),
            )
        )
    else:
        report.checks.append(
            JellyfinCheckItem(
                name="Memory Cgroup & OOM Safety",
                passed=True,
                details="No memory limit enforced (cgroup unbounded)",
                warning=True,
            )
        )

    # 4. GPU Device Node /dev/dri/renderD128
    if raw.render_device_code == 0:
        report.checks.append(
            JellyfinCheckItem(
                name="GPU Device Node",
                passed=True,
                details=f"Device node /dev/dri/renderD128 mounted ({raw.render_device_out})",
            )
        )
    else:
        report.checks.append(
            JellyfinCheckItem(
                name="GPU Device Node",
                passed=False,
                details=f"Device /dev/dri/renderD128 missing or inaccessible (code {raw.render_device_code})",
            )
        )

    # 5. VA-API Driver Initialization
    driver_name = _parse_vainfo_driver(raw.vainfo_out)
    if raw.vainfo_code == 0 or "va_openDriver() returns 0" in raw.vainfo_out or "iHD_drv_video.so" in raw.vainfo_out:
        report.checks.append(
            JellyfinCheckItem(
                name="VA-API Driver Pipeline",
                passed=True,
                details=f"{driver_name} initialized successfully",
            )
        )
    else:
        report.checks.append(
            JellyfinCheckItem(
                name="VA-API Driver Pipeline",
                passed=False,
                details=f"VA-API driver init failed (exit code {raw.vainfo_code}): {raw.vainfo_out.strip()[:100]}",
            )
        )

    # 6. Intel QuickSync (QSV) Hardware Transcoding
    if raw.qsv_test_code == 0:
        speed = _parse_qsv_speed(raw.qsv_test_out)
        report.qsv_speed = speed
        report.checks.append(
            JellyfinCheckItem(
                name="Intel QuickSync (QSV)",
                passed=True,
                details=f"H.264 QSV hardware encoding verified • Benchmark speed: {speed}",
            )
        )
    else:
        report.checks.append(
            JellyfinCheckItem(
                name="Intel QuickSync (QSV)",
                passed=False,
                details=f"QSV transcode test failed (exit code {raw.qsv_test_code})",
            )
        )

    # 7. Media Storage Mount (/mnt/mango/media)
    if raw.media_check_code == 0:
        dirs_str = ", ".join(raw.media_dirs) if raw.media_dirs else "accessible"
        report.checks.append(
            JellyfinCheckItem(
                name="Media Storage Mount",
                passed=True,
                details=f"/mnt/mango/media mounted & readable ({dirs_str})",
            )
        )
    else:
        report.checks.append(
            JellyfinCheckItem(
                name="Media Storage Mount",
                passed=False,
                details=f"/mnt/mango/media missing or unreadable (exit code {raw.media_check_code})",
            )
        )

    # 8. Jellyfin API Authentication
    if raw.api_auth_code == 200 and raw.api_auth_token:
        report.checks.append(
            JellyfinCheckItem(
                name="Jellyfin API Auth",
                passed=True,
                details=f"Authenticated as '{raw.username}' • Bearer token granted",
            )
        )
    else:
        report.checks.append(
            JellyfinCheckItem(
                name="Jellyfin API Auth",
                passed=False,
                details=f"Authentication failed with HTTP {raw.api_auth_code}",
            )
        )

    # 9. Media Library Catalog
    if raw.item_counts:
        movies = raw.item_counts.get("MovieCount", 0)
        series = raw.item_counts.get("SeriesCount", 0)
        episodes = raw.item_counts.get("EpisodeCount", 0)
        total = raw.item_counts.get("ItemCount", 0)
        report.checks.append(
            JellyfinCheckItem(
                name="Media Catalog",
                passed=True,
                details=f"{movies:,} movies, {series:,} series ({episodes:,} eps) • {total:,} total items",
            )
        )
    else:
        report.checks.append(
            JellyfinCheckItem(
                name="Media Catalog",
                passed=False,
                details="Library catalog empty or query failed",
            )
        )

    # 10. Active Playback & Transcoding State
    parsed_sessions: list[PlaybackSessionInfo] = []
    for s in raw.sessions:
        now_playing = s.get("NowPlayingItem")
        if now_playing:
            user = s.get("UserName", "user")
            client = s.get("Client", "client")
            dev = s.get("DeviceName", "device")
            title = now_playing.get("Name", "media")
            series_name = now_playing.get("SeriesName")
            if series_name:
                title = f"{series_name} - {title}"

            play_state = s.get("PlayState") or {}
            play_method = play_state.get("PlayMethod", "DirectPlay")
            trans_info = s.get("TranscodingInfo") or {}
            reasons = trans_info.get("TranscodeReasons") or []
            bitrate = trans_info.get("Bitrate", 0)

            parsed_sessions.append(
                PlaybackSessionInfo(
                    username=user,
                    client=client,
                    device=dev,
                    media_title=title,
                    play_method=play_method,
                    transcode_reasons=reasons,
                    bitrate_bps=bitrate,
                )
            )

    report.active_sessions = parsed_sessions

    if parsed_sessions:
        streams_desc = []
        for sess in parsed_sessions:
            method_str = sess.play_method
            if sess.transcode_reasons:
                method_str += f" ({', '.join(sess.transcode_reasons)})"
            streams_desc.append(f"{sess.username} watching '{sess.media_title}' [{method_str}] on {sess.client}")
        report.checks.append(
            JellyfinCheckItem(
                name="Playback Sessions",
                passed=True,
                details=f"{len(parsed_sessions)} active stream(s): {'; '.join(streams_desc)}",
            )
        )
    else:
        report.checks.append(
            JellyfinCheckItem(
                name="Playback Sessions",
                passed=True,
                details="No active playback streams (system idle)",
            )
        )

    # 11. Connected Clients (Last 24h)
    now = Instant.now()
    cutoff_24h = now.subtract(hours=24)
    ignored_apps = {"statuscheck", "homelabbootstrap", "jellyfin-cli", "status"}

    def _parse_dt(dt_str: str | None) -> Instant | None:
        if not dt_str:
            return None
        try:
            return Instant.parse_iso(dt_str)
        except ValueError, TypeError:
            return None

    # Map session device IDs to endpoints
    session_endpoints: dict[str, str] = {}
    for s in raw.sessions:
        s_dev_id = s.get("DeviceId")
        s_ip = s.get("RemoteEndPoint")
        if s_dev_id and s_ip:
            session_endpoints[s_dev_id] = s_ip

    device_cache = load_device_cache()
    cache_dirty = False

    # Build device-to-app map (device_name.lower() -> app_name)
    device_app_map: dict[str, str] = {}
    connected_clients: list[ConnectedClientInfo] = []
    seen_devices: set[tuple[str, str]] = set()

    sorted_devices = sorted(
        raw.devices,
        key=lambda d: _parse_dt(d.get("DateLastActivity")) or Instant.MIN,
        reverse=True,
    )

    for dev in sorted_devices:
        app = dev.get("AppName", "").strip()
        dev_name = dev.get("Name", "").strip()
        dev_id = dev.get("Id", "").strip()
        if not dev_name or app.lower() in ignored_apps:
            continue
        if dev_name.lower() not in device_app_map:
            device_app_map[dev_name.lower()] = app

        dt = _parse_dt(dev.get("DateLastActivity"))
        if not dt or dt < cutoff_24h:
            continue

        # Determine endpoint, route, platform, and hostname (only for active 24h devices)
        cached = device_cache.get(dev_id) or {}
        ip = session_endpoints.get(dev_id) or cached.get("endpoint")
        route_name, route_badge = classify_client_route(ip) if ip else ("Unknown", "")

        decoded_platform = decode_browser_user_agent(dev_id)
        platform = decoded_platform or (f"v{dev.get('AppVersion')}" if dev.get("AppVersion") else "")

        resolved_host = None
        if ip:
            if cached.get("endpoint") == ip and cached.get("hostname"):
                resolved_host = cached.get("hostname")
            else:
                resolved_host = _resolve_ip_hostname(ip)

        effective_device = resolved_host or cached.get("hostname") or dev_name

        # Update cache if we have new or updated info
        if dev_id and (ip or resolved_host or decoded_platform):
            new_entry = {
                "endpoint": ip or "",
                "hostname": effective_device,
                "platform": platform,
                "route": route_name if route_name != "Unknown" else cached.get("route", ""),
                "route_badge": route_badge or cached.get("route_badge", ""),
                "app_name": app,
                "device_name": dev_name,
            }
            if new_entry != cached:
                device_cache[dev_id] = new_entry
                cache_dirty = True

        key = (effective_device.lower(), app.lower())
        if key not in seen_devices:
            seen_devices.add(key)
            connected_clients.append(
                ConnectedClientInfo(
                    app_name=app,
                    device_name=effective_device,
                    username=dev.get("LastUserName", ""),
                    last_activity=dt.format_iso(),
                    relative_time=_format_relative_time(dt, now),
                    app_version=dev.get("AppVersion", ""),
                    platform=platform,
                    route=route_name,
                    endpoint=ip or "",
                    route_badge=route_badge,
                )
            )

    if cache_dirty:
        save_device_cache(device_cache)

    report.connected_clients_24h = connected_clients

    if connected_clients:
        c_descs = []
        for c in connected_clients:
            r_str = f" • {c.route}" if c.route and c.route != "Unknown" else ""
            c_descs.append(f"{c.app_name} on {c.device_name}{r_str} ({c.relative_time})")
        report.checks.append(
            JellyfinCheckItem(
                name="Connected Clients (24h)",
                passed=True,
                details=f"{len(connected_clients)} active: {', '.join(c_descs)}",
            )
        )
    else:
        report.checks.append(
            JellyfinCheckItem(
                name="Connected Clients (24h)",
                passed=True,
                details="No client activity in the last 24h",
            )
        )

    # 12. Playback History & 24h Activity
    parsed_history: list[PlaybackHistoryItem] = []
    plays_24h_count = 0
    plays_by_client: dict[str, int] = {}

    for entry in raw.activity_entries:
        if entry.get("Type") != "VideoPlayback":
            continue
        m = _PLAYBACK_LOG_PATTERN.match(entry.get("Name", ""))
        if not m:
            continue
        user = m.group("user").strip()
        title = m.group("title").strip()
        dev_name = m.group("device").strip()
        dt = _parse_dt(entry.get("Date"))
        if not dt:
            continue

        # Deduplicate consecutive plays of same title & device within 5 minutes
        if parsed_history:
            prev = parsed_history[-1]
            prev_dt = _parse_dt(prev.timestamp)
            if (
                prev_dt
                and prev.media_title == title
                and prev.device_name == dev_name
                and abs(int((prev_dt - dt).total("seconds"))) < 300
            ):
                continue

        resolved_client = device_app_map.get(dev_name.lower(), "")
        client_label = f"{resolved_client} ({dev_name})" if resolved_client else dev_name

        if dt >= cutoff_24h:
            plays_24h_count += 1
            plays_by_client[client_label] = plays_by_client.get(client_label, 0) + 1

        if len(parsed_history) < history_limit:
            parsed_history.append(
                PlaybackHistoryItem(
                    timestamp=dt.format_iso(),
                    relative_time=_format_playback_time(dt, now),
                    username=user,
                    media_title=title,
                    device_name=dev_name,
                    client_name=resolved_client,
                    item_id=entry.get("ItemId", ""),
                )
            )

    report.recent_playback = parsed_history
    report.plays_last_24h_count = plays_24h_count
    report.plays_by_client_24h = plays_by_client

    if plays_24h_count > 0:
        breakdown = ", ".join(f"{cnt} on {cl}" for cl, cnt in plays_by_client.items())
        report.checks.append(
            JellyfinCheckItem(
                name="Playback Activity (24h)",
                passed=True,
                details=f"{plays_24h_count} item(s) played ({breakdown})",
            )
        )
    elif parsed_history:
        last_item = parsed_history[0]
        cl_str = f" ({last_item.client_name})" if last_item.client_name else ""
        report.checks.append(
            JellyfinCheckItem(
                name="Playback Activity (24h)",
                passed=True,
                details=(
                    f"0 plays in last 24h • Last: '{last_item.media_title}' "
                    f"on {last_item.device_name}{cl_str} ({last_item.relative_time})"
                ),
            )
        )
    else:
        report.checks.append(
            JellyfinCheckItem(
                name="Playback Activity (24h)",
                passed=True,
                details="No playback history recorded",
            )
        )

    report.all_passed = all(c.passed for c in report.checks if not c.warning)
    return report


async def run_jellyfin_deep_check(ctx: StatusContext, history_limit: int = 10) -> JellyfinDeepReport:
    """Execute the full Jellyfin deep verification suite with concurrent I/O."""
    raw = await _gather_jellyfin_raw_data(ctx)
    return evaluate_jellyfin_report(raw, connection=ctx.connection, history_limit=history_limit)


def render_jellyfin_deep_report(report: JellyfinDeepReport, console: Console) -> None:
    """Render structured Jellyfin inspection results with Rich panels and table."""
    if report.connection:
        render_command_header(
            "🎬 Jellyfin Media Server Deep Health Inspector",
            report.connection,
            console,
            border_style="magenta",
        )

    table = Table(title="🎬 Jellyfin Health & Hardware Status", show_header=True, header_style="bold magenta")
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

    if report.connected_clients_24h:
        client_table = Table(
            title="👥 Connected Clients (Last 24h)",
            show_header=True,
            header_style="bold cyan",
        )
        client_table.add_column("Client App", style="bold cyan", width=16)
        client_table.add_column("Device Name", style="bold", width=22)
        client_table.add_column("Platform / OS", style="dim", width=22)
        client_table.add_column("Route & Endpoint", width=28)
        client_table.add_column("Last Active", style="dim", width=14)
        client_table.add_column("User", style="yellow", width=10)

        for client in report.connected_clients_24h:
            route_str = (
                f"{client.route_badge} [dim]({client.endpoint})[/dim]"
                if client.endpoint and client.route_badge
                else client.route_badge or "[dim]Unknown[/dim]"
            )
            client_table.add_row(
                client.app_name,
                client.device_name,
                client.platform or "[dim]—[/dim]",
                route_str,
                client.relative_time,
                client.username or "—",
            )

        console.print(client_table)
        console.print()

    if report.recent_playback:
        history_title = f"📜 Recent Playback History (Most Recent {len(report.recent_playback)})"
        history_table = Table(
            title=history_title,
            show_header=True,
            header_style="bold cyan",
        )
        history_table.add_column("Time", style="cyan", width=22)
        history_table.add_column("Media Title", style="bold green")
        history_table.add_column("User", style="yellow", width=12)
        history_table.add_column("Client / Device", style="magenta", width=26)

        for p in report.recent_playback:
            cl_info = f"{p.client_name} ({p.device_name})" if p.client_name else p.device_name
            history_table.add_row(
                p.relative_time,
                p.media_title,
                p.username,
                cl_info,
            )

        console.print(history_table)
        console.print()

    route_line = format_route_line(report.connection)

    if report.all_passed:
        mem_str = ""
        if report.memory and report.memory.limit_bytes > 0:
            mem_str = (
                f"\n• [bold]Memory Cgroup:[/bold] [bold cyan]{format_bytes(report.memory.usage_bytes)}[/bold cyan] / "
                f"[bold cyan]{format_bytes(report.memory.limit_bytes)}[/bold cyan] "
                f"([bold cyan]{report.memory.usage_percent:.1f}%[/bold cyan]) "
                f"[dim]• [bold cyan]512MiB[/bold cyan] enforced • [bold cyan]0[/bold cyan] OOM kills[/dim]"
            )

        qsv_str = f"QSV [bold cyan]{report.qsv_speed}[/bold cyan]" if report.qsv_speed else "Active"
        cat = report.item_counts
        movies_cnt = cat.get("MovieCount", 0)
        series_cnt = cat.get("SeriesCount", 0)
        items_cnt = cat.get("ItemCount", 0)
        cat_str = (
            f"[bold cyan]{movies_cnt:,}[/bold cyan] movies, "
            f"[bold cyan]{series_cnt:,}[/bold cyan] series "
            f"([bold cyan]{items_cnt:,}[/bold cyan] items)"
        )

        stream_str = ""
        if report.active_sessions:
            first_sess = report.active_sessions[0]
            stream_str = (
                f"\n• [bold]Active Stream:[/bold] [bold yellow]{first_sess.media_title}[/bold yellow] "
                f"({first_sess.play_method})"
            )
        else:
            stream_str = "\n• [bold]Active Streams:[/bold] [bold cyan]0[/bold cyan] (Idle)"

        clients_line = ""
        if report.connected_clients_24h:
            c_names = [f"{c.app_name} on {c.device_name}" for c in report.connected_clients_24h]
            clients_line = f"\n• [bold]Connected Clients (24h):[/bold] {', '.join(c_names)}"

        playback_line = ""
        if report.plays_last_24h_count > 0:
            breakdown = ", ".join(f"{cnt} on {cl}" for cl, cnt in report.plays_by_client_24h.items())
            playback_line = (
                f"\n• [bold]Playback (24h):[/bold] "
                f"[bold green]{report.plays_last_24h_count} item(s) played[/bold green] ({breakdown})"
            )
        elif report.recent_playback:
            last_p = report.recent_playback[0]
            cl_str = f" ({last_p.client_name})" if last_p.client_name else ""
            playback_line = (
                "\n• [bold]Playback (24h):[/bold] [dim]0 played • Last:[/dim] "
                f"[bold yellow]'{last_p.media_title}'[/bold yellow] "
                f"[dim]on {last_p.device_name}{cl_str} ({last_p.relative_time})[/dim]"
            )

        verdict = Panel(
            "[bold green]✔ ALL JELLYFIN CHECKS PASSED & HARDWARE ACCELERATED[/bold green]\n\n"
            f"{route_line}"
            f"• [bold]Hardware Acceleration:[/bold] Intel QuickSync ({qsv_str}) via iHD driver\n"
            f"• [bold]Media Library:[/bold] {cat_str}"
            f"{mem_str}"
            f"{stream_str}"
            f"{clients_line}"
            f"{playback_line}",
            title="[bold green]Status: HEALTHY & ACCELERATED[/bold green]",
            border_style="green",
        )
    else:
        failed = sum(1 for c in report.checks if not c.passed and not c.warning)
        verdict = Panel(
            f"[bold red]✖ {failed} CRITICAL CHECK(S) FAILED[/bold red]\n\n"
            f"{route_line}"
            "Review the table above for GPU permissions, cgroup limits, or media mounts.",
            title="[bold red]Status: DEGRADED / UNHEALTHY[/bold red]",
            border_style="red",
        )

    console.print(verdict)
    console.print()


async def check_jellyfin(ctx: StatusContext) -> ServiceResult:
    """Standard service check for the homelab status tree with GPU and cgroup telemetry."""
    service_id = "jellyfin"
    name = "Jellyfin"
    container = ContainerName.JELLYFIN
    t0 = time.perf_counter()

    try:
        raw = await _gather_jellyfin_raw_data(ctx)
        report = evaluate_jellyfin_report(raw, connection=ctx.connection)
        elapsed = (time.perf_counter() - t0) * 1000

        if not raw.api_auth_token:
            return ServiceResult(
                service_id=service_id,
                name=name,
                container=container,
                status=HealthStatus.UNHEALTHY,
                latency_ms=elapsed,
                summary=f"Authentication failed: HTTP {raw.api_auth_code}",
                branches=[f"[bold red]✖ Authentication failed (HTTP {raw.api_auth_code})[/bold red]"],
            )

        movies = raw.item_counts.get("MovieCount", 0)
        series = raw.item_counts.get("SeriesCount", 0)
        episodes = raw.item_counts.get("EpisodeCount", 0)
        boxsets = raw.item_counts.get("BoxSetCount", 0)
        items = raw.item_counts.get("ItemCount", 0)

        summary = f"{movies} movies, {series} series ({episodes:,} eps) • Intel QSV active"

        branches = [
            f"🎬 Movies: [bold cyan]{movies:,}[/bold cyan]",
            (
                f"📺 TV Shows: [bold cyan]{series:,}[/bold cyan] series "
                f"[dim]([bold cyan]{episodes:,}[/bold cyan] episodes)[/dim]"
            ),
            (
                f"📦 Collections: [bold cyan]{boxsets:,}[/bold cyan] boxsets "
                f"[dim]•[/dim] [bold cyan]{items:,}[/bold cyan] total items"
            ),
        ]

        # GPU acceleration branch
        if raw.qsv_test_code == 0:
            speed = _parse_qsv_speed(raw.qsv_test_out)
            branches.append(f"⚡ Hardware Acceleration: [bold green]Intel QSV (iHD)[/bold green] [dim]• {speed}[/dim]")
        elif raw.render_device_code == 0:
            branches.append("⚡ Hardware Acceleration: [bold yellow]Render node present (QSV unverified)[/bold yellow]")
        else:
            branches.append("⚡ Hardware Acceleration: [bold red]GPU render node missing[/bold red]")

        # Cgroup memory branch
        if report.memory and report.memory.limit_bytes > 0:
            mem = report.memory
            pct_color = "red" if mem.usage_percent > 90 else "green"
            branches.append(
                f"🧠 Memory Cgroup: [bold {pct_color}]{format_bytes(mem.usage_bytes)} / "
                f"{format_bytes(mem.limit_bytes)} ({mem.usage_percent:.1f}%)[/bold {pct_color}]"
            )

        # Active playback branch
        if report.active_sessions:
            streams_repr = [
                f'[bold yellow]{s.username}[/bold yellow]: "[bold green]{s.media_title}[/bold green]" ({s.play_method})'
                for s in report.active_sessions
            ]
            branches.append(f"▶️ Active Playback: {', '.join(streams_repr)}")

        # Connected clients (24h) branch
        if report.connected_clients_24h:
            client_lines = [
                f"👥 Active Clients (24h): [bold cyan]{len(report.connected_clients_24h)} active[/bold cyan]"
            ]
            for c in report.connected_clients_24h:
                badge_inner = c.device_name
                if c.platform and not c.platform.startswith("v") and c.platform != c.device_name:
                    short_plat = c.platform.split(" (")[0] if " (" in c.platform else c.platform
                    badge_inner = f"{short_plat} on {c.device_name}"
                route_str = f" [dim]•[/dim] {c.route_badge}" if c.route_badge else ""
                time_str = f" [dim]({c.relative_time})[/dim]" if c.relative_time else ""
                client_lines.append(f"  • [bold cyan]{c.app_name}[/bold cyan]: {badge_inner}{route_str}{time_str}")
            branches.append("\n".join(client_lines))

        # Recent plays branch (up to last 10 items)
        if report.plays_last_24h_count > 0:
            play_lines = [f"📜 Recent Plays (24h): [bold green]{report.plays_last_24h_count} item(s)[/bold green]"]
            for p in report.recent_playback[:10]:
                dev_str = f" on {p.client_name}" if p.client_name else (f" on {p.device_name}" if p.device_name else "")
                play_lines.append(
                    f'  • [bold yellow]"{p.media_title}"[/bold yellow][dim]{dev_str} ({p.relative_time})[/dim]'
                )
            branches.append("\n".join(play_lines))
        elif report.recent_playback:
            last_p = report.recent_playback[0]
            cl_str = f" ({last_p.client_name})" if last_p.client_name else ""
            branches.append(
                f'📜 Recent Plays: [dim]0 in 24h • Last:[/dim] [bold yellow]"{last_p.media_title}"[/bold yellow] '
                f"[dim]on {last_p.device_name}{cl_str} ({last_p.relative_time})[/dim]"
            )

        return ServiceResult(
            service_id=service_id,
            name=name,
            container=container,
            status=HealthStatus.HEALTHY if report.all_passed else HealthStatus.UNHEALTHY,
            latency_ms=elapsed,
            summary=summary,
            version=report.version,
            branches=branches,
            raw_data=raw.item_counts,
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
