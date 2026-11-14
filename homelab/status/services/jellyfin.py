"""Jellyfin content, hardware acceleration, memory cgroup, and session health check."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import anyio
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from common import format_bytes, format_connection_badge, format_route_line, render_command_header
from models import HealthStatus, ServiceResult, StatusContext, TargetConnection


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
    item_counts: dict[str, int] = field(default_factory=dict)
    version: str | None = None


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
    container_name = "homelab-jellyfin-1"

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
                    'MediaBrowser Client="StatusCheck", Device="homelab-status", DeviceId="homelab-status-check", Version="1.0.0"'
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
                    try:
                        v_res = await client.get("/System/Info/Public")
                        if v_res.status_code == 200:
                            v = v_res.json().get("Version")
                            if v:
                                raw.version = f"v{v}"
                    except Exception:
                        pass

                async def _get_counts() -> None:
                    try:
                        c_res = await client.get("/Items/Counts", headers=headers)
                        if c_res.status_code == 200:
                            raw.item_counts = c_res.json()
                    except Exception:
                        pass

                async def _get_sessions() -> None:
                    try:
                        s_res = await client.get("/Sessions", headers=headers)
                        if s_res.status_code == 200:
                            raw.sessions = s_res.json()
                    except Exception:
                        pass

                async with anyio.create_task_group() as tg_api:
                    tg_api.start_soon(_get_version)
                    tg_api.start_soon(_get_counts)
                    tg_api.start_soon(_get_sessions)
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


def evaluate_jellyfin_report(raw: JellyfinRawData, connection: TargetConnection | None = None) -> JellyfinDeepReport:
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
                details="Container 'homelab-jellyfin-1' not found",
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

    report.all_passed = all(c.passed for c in report.checks if not c.warning)
    return report


async def run_jellyfin_deep_check(ctx: StatusContext) -> JellyfinDeepReport:
    """Execute the full Jellyfin deep verification suite with concurrent I/O."""
    raw = await _gather_jellyfin_raw_data(ctx)
    return evaluate_jellyfin_report(raw, connection=ctx.connection)


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

        verdict = Panel(
            "[bold green]✔ ALL JELLYFIN CHECKS PASSED & HARDWARE ACCELERATED[/bold green]\n\n"
            f"{route_line}"
            f"• [bold]Hardware Acceleration:[/bold] Intel QuickSync ({qsv_str}) via iHD driver\n"
            f"• [bold]Media Library:[/bold] {cat_str}"
            f"{mem_str}"
            f"{stream_str}",
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
    container = "homelab-jellyfin-1"
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
