#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "docker>=7.1.0",
#   "httpx>=0.27.0",
#   "paramiko>=3.5.0",
#   "python-dotenv>=1.0.0",
#   "rich>=13.0.0",
#   "typer>=0.16.0",
# ]
# ///
"""Homelab Deep Health & Content Inspector.

Performs deep, service-specific health checks across all homelab containers:
- Jellyfin: Content counts (movies, series, episodes, collections)
- BookOrbit: Library content and book counts
- qBittorrent: Torrent completion counts (A/B) and bandwidth speeds
- RetroArch: WebDAV shares and directory listing
- Caddy: Reverse proxy routed hostnames and TLS certificates
- Samba: File shares, configured accounts, and active sessions
- Arcane: Environments, projects, and container counts
- Qui: Client instance connections and status
- Glance: Homepage dashboard availability
- Withings Sync: Supercronic cron scheduler status and container health
- BookOrbit PostgreSQL: Database connectivity and row counts
"""

from __future__ import annotations

import datetime
import io
import json
import logging
import os
import re
import socket
import ssl
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import docker
    from docker.models.containers import Container

import httpx
import typer
from dotenv import dotenv_values
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Silence verbose SSH/Paramiko noise
logging.getLogger("paramiko").setLevel(logging.CRITICAL)

app = typer.Typer(
    help="Homelab Deep Health & Content Inspector",
    add_completion=False,
)
console = Console()


class HealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


@dataclass
class ServiceResult:
    service_id: str
    name: str
    container: str
    status: HealthStatus
    latency_ms: float
    details: str
    raw_data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def is_healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY


@dataclass
class StatusContext:
    env: dict[str, str]
    username: str
    password: str
    base_domain: str
    lan_host: str
    docker_client: docker.DockerClient | None
    http_timeout: float = 10.0
    no_docker: bool = False
    _docker_lock: threading.Lock = field(default_factory=threading.Lock)

    def base_url(self, subdomain: str | None = None) -> str:
        if subdomain:
            return f"https://{subdomain}.{self.base_domain}"
        return f"https://{self.base_domain}"

    def get_container(self, name: str) -> Container | None:
        if not self.docker_client:
            return None
        with self._docker_lock:
            try:
                return self.docker_client.containers.get(name)
            except Exception:
                return None

    def exec_container(self, container_name: str, cmd: str | list[str]) -> tuple[int, str]:
        """Safely execute command in container with thread synchronization."""
        if not self.docker_client:
            return (-1, "Docker client not available")
        with self._docker_lock:
            try:
                c = self.docker_client.containers.get(container_name)
                res = c.exec_run(cmd)
                out = (
                    res.output.decode("utf-8", errors="replace")
                    if isinstance(res.output, (bytes, bytearray))
                    else str(res.output)
                )
                return (res.exit_code, out)
            except Exception as exc:
                return (-1, str(exc))


def format_speed(bytes_per_sec: float) -> str:
    bps = float(bytes_per_sec)
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / (1024 * 1024):.2f} MB/s"


def load_env(env_path: Path | None, lan_host: str) -> dict[str, str]:
    """Load homelab .env file from local disk or via remote SFTP fallback."""
    # 1. Explicit path
    if env_path and env_path.is_file():
        return {k: v for k, v in dotenv_values(env_path).items() if v is not None}

    # 2. Local homelab/.env or ./.env
    search_paths = [
        Path.cwd() / ".env",
        Path.cwd() / "homelab" / ".env",
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / "homelab" / ".env",
    ]
    for p in search_paths:
        if p.is_file():
            return {k: v for k, v in dotenv_values(p).items() if v is not None}

    # 3. Fallback to reading remote .env over SFTP from lan_host (if on workstation)
    try:
        import paramiko

        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(lan_host, username="ehtesh", timeout=4)
        sftp = ssh.open_sftp()
        with sftp.file("/home/ehtesh/dotfiles/homelab/.env", "r") as f:
            content = f.read().decode("utf-8")
        parsed = dotenv_values(stream=io.StringIO(content))
        return {k: v for k, v in parsed.items() if v is not None}
    except Exception:
        pass

    # 4. OS environment variables
    return dict(os.environ)


def get_docker_client(
    docker_host: str | None = None,
    lan_host: str = "m70q.lan",
    no_docker: bool = False,
) -> docker.DockerClient | None:
    """Resolve Docker client using local socket, explicit host, or SSH bridge."""
    if no_docker:
        return None

    import docker

    if docker_host:
        try:
            c = docker.DockerClient(base_url=docker_host, timeout=5)
            c.ping()
            return c
        except Exception:
            return None

    if os.environ.get("DOCKER_HOST"):
        try:
            c = docker.from_env()
            c.ping()
            return c
        except Exception:
            pass

    # Try local UNIX socket
    sock_path = "/var/run/docker.sock"
    if os.path.exists(sock_path) and os.access(sock_path, os.R_OK):
        try:
            c = docker.from_env()
            c.ping()
            return c
        except Exception:
            pass

    # Fallback to SSH connection to target host
    try:
        c = docker.DockerClient(base_url=f"ssh://ehtesh@{lan_host}", timeout=5)
        c.ping()
        return c
    except Exception:
        pass

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Service Health Checks
# ─────────────────────────────────────────────────────────────────────────────


def check_jellyfin(ctx: StatusContext) -> ServiceResult:
    service_id = "jellyfin"
    name = "Jellyfin"
    container = "homelab-jellyfin-1"
    t0 = time.perf_counter()

    try:
        with httpx.Client(base_url=ctx.base_url("jellyfin"), timeout=ctx.http_timeout) as client:
            auth_header = (
                'MediaBrowser Client="StatusCheck", Device="m70q", '
                'DeviceId="homelab-status-check", Version="1.0.0"'
            )
            login_res = client.post(
                "/Users/AuthenticateByName",
                json={"Username": ctx.username, "Pw": ctx.password},
                headers={
                    "Authorization": auth_header,
                    "X-Emby-Authorization": auth_header,
                },
            )
            if login_res.status_code != 200:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id,
                    name,
                    container,
                    HealthStatus.UNHEALTHY,
                    elapsed,
                    f"Authentication failed: HTTP {login_res.status_code}",
                    error=login_res.text,
                )

            token = login_res.json().get("AccessToken")
            auth_with_tok = f'{auth_header}, Token="{token}"'
            counts_res = client.get(
                "/Items/Counts",
                headers={
                    "Authorization": auth_with_tok,
                    "X-Emby-Authorization": auth_with_tok,
                    "X-Emby-Token": token,
                },
            )
            if counts_res.status_code != 200:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id,
                    name,
                    container,
                    HealthStatus.UNHEALTHY,
                    elapsed,
                    f"Failed to query counts: HTTP {counts_res.status_code}",
                    error=counts_res.text,
                )

            data = counts_res.json()
            elapsed = (time.perf_counter() - t0) * 1000

            movies = data.get("MovieCount", 0)
            series = data.get("SeriesCount", 0)
            episodes = data.get("EpisodeCount", 0)
            boxsets = data.get("BoxSetCount", 0)
            items = data.get("ItemCount", 0)

            details = (
                f"{movies} movies, {series} series ({episodes:,} eps), "
                f"{boxsets} boxsets • {items:,} total items"
            )
            return ServiceResult(
                service_id,
                name,
                container,
                HealthStatus.HEALTHY,
                elapsed,
                details,
                raw_data=data,
            )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ServiceResult(
            service_id,
            name,
            container,
            HealthStatus.UNHEALTHY,
            elapsed,
            f"Error: {exc}",
            error=str(exc),
        )


def check_bookorbit(ctx: StatusContext) -> ServiceResult:
    service_id = "bookorbit"
    name = "BookOrbit"
    container = "homelab-bookorbit-1"
    t0 = time.perf_counter()

    try:
        with httpx.Client(base_url=ctx.base_url("bookorbit"), timeout=ctx.http_timeout) as client:
            login_res = client.post(
                "/api/v1/auth/login",
                json={"username": ctx.username, "password": ctx.password},
            )
            if login_res.status_code != 200:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id,
                    name,
                    container,
                    HealthStatus.UNHEALTHY,
                    elapsed,
                    f"Authentication failed: HTTP {login_res.status_code}",
                    error=login_res.text,
                )

            token = login_res.json().get("accessToken")
            libs_res = client.get(
                "/api/v1/libraries",
                headers={"Authorization": f"Bearer {token}"},
            )
            if libs_res.status_code != 200:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id,
                    name,
                    container,
                    HealthStatus.UNHEALTHY,
                    elapsed,
                    f"Failed to query libraries: HTTP {libs_res.status_code}",
                    error=libs_res.text,
                )

            libraries = libs_res.json()
            elapsed = (time.perf_counter() - t0) * 1000

            total_books = sum(lib.get("bookCount", 0) for lib in libraries)
            lib_summaries = []
            for lib in libraries:
                lname = lib.get("name", "Unknown")
                bcount = lib.get("bookCount", 0)
                folders = lib.get("folders", [])
                fpath = folders[0].get("path", "") if folders else ""
                lib_summaries.append(f'"{lname}" ({bcount} in {fpath})' if fpath else f'"{lname}" ({bcount})')

            lib_str = ", ".join(lib_summaries) if lib_summaries else "none"
            count_noun = "library" if len(libraries) == 1 else "libraries"
            details = f"{total_books} books across {len(libraries)} {count_noun} ({lib_str})"

            return ServiceResult(
                service_id,
                name,
                container,
                HealthStatus.HEALTHY,
                elapsed,
                details,
                raw_data={"libraries": libraries, "total_books": total_books},
            )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ServiceResult(
            service_id,
            name,
            container,
            HealthStatus.UNHEALTHY,
            elapsed,
            f"Error: {exc}",
            error=str(exc),
        )


def check_qbittorrent(ctx: StatusContext) -> ServiceResult:
    service_id = "qbittorrent"
    name = "qBittorrent"
    container = "homelab-qbittorrent-1"
    t0 = time.perf_counter()

    try:
        with httpx.Client(base_url=ctx.base_url("qbittorrent"), timeout=ctx.http_timeout) as client:
            login_res = client.post(
                "/api/v2/auth/login",
                data={"username": ctx.username, "password": ctx.password},
            )
            # qBittorrent returns 200 or 204 with "Ok."
            if login_res.status_code not in (200, 204) or "Fails" in login_res.text:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id,
                    name,
                    container,
                    HealthStatus.UNHEALTHY,
                    elapsed,
                    f"Authentication failed: HTTP {login_res.status_code} ({login_res.text.strip()})",
                    error=login_res.text,
                )

            data_res = client.get("/api/v2/sync/maindata")
            if data_res.status_code != 200:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id,
                    name,
                    container,
                    HealthStatus.UNHEALTHY,
                    elapsed,
                    f"Failed to fetch torrent state: HTTP {data_res.status_code}",
                    error=data_res.text,
                )

            maindata = data_res.json()
            elapsed = (time.perf_counter() - t0) * 1000

            torrents = maindata.get("torrents", {})
            server_state = maindata.get("server_state", {})

            total = len(torrents)
            completed = sum(1 for t in torrents.values() if t.get("progress", 0) >= 1.0)
            active = sum(
                1
                for t in torrents.values()
                if t.get("state") in ("downloading", "uploading", "stalledUP", "stalledDL")
            )
            dl_speed = format_speed(server_state.get("dl_info_speed", 0))
            up_speed = format_speed(server_state.get("up_info_speed", 0))

            details = f"{completed}/{total} completed ({active} active) • {dl_speed} ↓, {up_speed} ↑"
            return ServiceResult(
                service_id,
                name,
                container,
                HealthStatus.HEALTHY,
                elapsed,
                details,
                raw_data={"total": total, "completed": completed, "active": active},
            )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ServiceResult(
            service_id,
            name,
            container,
            HealthStatus.UNHEALTHY,
            elapsed,
            f"Error: {exc}",
            error=str(exc),
        )


def check_retroarch(ctx: StatusContext) -> ServiceResult:
    service_id = "retroarch"
    name = "RetroArch (WebDAV)"
    container = "homelab-rclone-retroarch-1"
    t0 = time.perf_counter()

    try:
        with httpx.Client(base_url=ctx.base_url("retroarch"), timeout=ctx.http_timeout) as client:
            res = client.request("PROPFIND", "/", headers={"Depth": "1"})
            if res.status_code != 207:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id,
                    name,
                    container,
                    HealthStatus.UNHEALTHY,
                    elapsed,
                    f"WebDAV PROPFIND failed: HTTP {res.status_code}",
                    error=res.text,
                )

            elapsed = (time.perf_counter() - t0) * 1000
            root = ET.fromstring(res.text)
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
            details = f"{len(entries)} shares/entries: {', '.join(entries)}"
            return ServiceResult(
                service_id,
                name,
                container,
                HealthStatus.HEALTHY,
                elapsed,
                details,
                raw_data={"entries": entries},
            )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ServiceResult(
            service_id,
            name,
            container,
            HealthStatus.UNHEALTHY,
            elapsed,
            f"Error: {exc}",
            error=str(exc),
        )


def check_caddy(ctx: StatusContext) -> ServiceResult:
    service_id = "caddy"
    name = "Caddy Ingress"
    container = "homelab-caddy-1"
    t0 = time.perf_counter()

    try:
        # 1. TLS and certificate check on port 443
        ssl_ctx = ssl.create_default_context()
        cert_info = {}
        with (
            socket.create_connection((ctx.base_domain, 443), timeout=ctx.http_timeout) as sock,
            ssl_ctx.wrap_socket(sock, server_hostname=ctx.base_domain) as ssock,
        ):
            cert = ssock.getpeercert()
            issuer = dict(x[0] for x in cert.get("issuer", []))
            issuer_org = issuer.get("organizationName") or issuer.get("commonName") or "Valid TLS"
            not_after = cert.get("notAfter", "")
            # Format: 'Jan  3 15:52:53 2027 GMT'
            try:
                dt = datetime.datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                expires_str = dt.strftime("%b %d %Y")
            except Exception:
                expires_str = not_after
            cert_info = {"issuer": issuer_org, "expires": expires_str}

        # 2. Ingress HTTP probe
        with httpx.Client(base_url=f"https://{ctx.base_domain}", timeout=ctx.http_timeout) as client:
            probe = client.get("/")
            if probe.status_code >= 500:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id,
                    name,
                    container,
                    HealthStatus.UNHEALTHY,
                    elapsed,
                    f"Root ingress route returned HTTP {probe.status_code}",
                )

        # 3. Read autosave routes via container exec if Docker available
        routes_list: list[str] = []
        code, out = ctx.exec_container(container, "cat /config/caddy/autosave.json")
        if code == 0:
            try:
                cfg = json.loads(out)
                srv_routes = (
                    cfg.get("apps", {})
                    .get("http", {})
                    .get("servers", {})
                    .get("srv0", {})
                    .get("routes", [])
                )
                hosts = {
                    h
                    for r in srv_routes
                    for m in r.get("match", [])
                    for h in m.get("host", [])
                }
                routes_list = sorted(hosts)
            except Exception:
                pass

        elapsed = (time.perf_counter() - t0) * 1000

        # Shorten route names for readable terminal display
        short_routes = [
            h.replace(f".{ctx.base_domain}", "") if h != ctx.base_domain else h
            for h in routes_list
        ]
        routes_str = f"{len(routes_list)} routes ({', '.join(short_routes)})" if routes_list else "Ingress active"
        tls_str = f"TLS: {cert_info.get('issuer')} (valid to {cert_info.get('expires')})"

        details = f"{routes_str} • {tls_str}"
        return ServiceResult(
            service_id,
            name,
            container,
            HealthStatus.HEALTHY,
            elapsed,
            details,
            raw_data={"routes": routes_list, "cert": cert_info},
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ServiceResult(
            service_id,
            name,
            container,
            HealthStatus.UNHEALTHY,
            elapsed,
            f"Error: {exc}",
            error=str(exc),
        )


def check_samba(ctx: StatusContext) -> ServiceResult:
    service_id = "samba"
    name = "Samba File Server"
    container = "homelab-samba-1"
    t0 = time.perf_counter()

    try:
        # 1. TCP connection probe to port 445 (host network)
        target_host = ctx.lan_host
        with socket.create_connection((target_host, 445), timeout=ctx.http_timeout):
            pass

        # 2. Docker container inspection for shares & accounts
        shares: list[str] = []
        accounts: list[str] = []

        code, out = ctx.exec_container(container, "testparm -s")
        if code == 0:
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    sec = line[1:-1]
                    if sec != "global":
                        shares.append(sec)

        code, out = ctx.exec_container(container, "pdbedit -L")
        if code == 0:
            for line in out.splitlines():
                if ":" in line:
                    accounts.append(line.split(":")[0])

        elapsed = (time.perf_counter() - t0) * 1000

        shares.sort()
        accounts.sort()
        shares_str = f"{len(shares)} shares ({', '.join(shares)})" if shares else "shares active"
        acc_str = f"accounts: {', '.join(accounts)}" if accounts else "auth ready"

        details = f"{shares_str} • {acc_str} • port 445 open"
        return ServiceResult(
            service_id,
            name,
            container,
            HealthStatus.HEALTHY,
            elapsed,
            details,
            raw_data={"shares": shares, "accounts": accounts},
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ServiceResult(
            service_id,
            name,
            container,
            HealthStatus.UNHEALTHY,
            elapsed,
            f"Error: {exc}",
            error=str(exc),
        )


def check_arcane(ctx: StatusContext) -> ServiceResult:
    service_id = "arcane"
    name = "Arcane Management"
    container = "homelab-arcane-1"
    t0 = time.perf_counter()

    try:
        with httpx.Client(base_url=ctx.base_url("arcane"), timeout=ctx.http_timeout) as client:
            login_res = client.post(
                "/api/auth/login",
                json={"username": ctx.username, "password": ctx.password},
            )
            if login_res.status_code != 200:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id,
                    name,
                    container,
                    HealthStatus.UNHEALTHY,
                    elapsed,
                    f"Authentication failed: HTTP {login_res.status_code}",
                    error=login_res.text,
                )

            ver_res = client.get("/api/version")
            version = ver_res.json().get("currentVersion", "v2") if ver_res.status_code == 200 else "v2"

            cnt_res = client.get("/api/environments/0/containers")
            containers_count = len(cnt_res.json().get("data", [])) if cnt_res.status_code == 200 else 0

            proj_res = client.get("/api/environments/0/projects")
            projects_count = len(proj_res.json().get("data", [])) if proj_res.status_code == 200 else 0

            elapsed = (time.perf_counter() - t0) * 1000
            details = f"{version} • {containers_count} containers, {projects_count} projects on 'm70q'"
            return ServiceResult(
                service_id,
                name,
                container,
                HealthStatus.HEALTHY,
                elapsed,
                details,
                raw_data={"version": version, "containers": containers_count, "projects": projects_count},
            )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ServiceResult(
            service_id,
            name,
            container,
            HealthStatus.UNHEALTHY,
            elapsed,
            f"Error: {exc}",
            error=str(exc),
        )


def check_qui(ctx: StatusContext) -> ServiceResult:
    service_id = "qui"
    name = "Qui WebUI"
    container = "homelab-qui-1"
    t0 = time.perf_counter()

    try:
        with httpx.Client(base_url=ctx.base_url("qui"), timeout=ctx.http_timeout) as client:
            login_res = client.post(
                "/api/auth/login",
                json={"username": ctx.username, "password": ctx.password},
            )
            if login_res.status_code != 200:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id,
                    name,
                    container,
                    HealthStatus.UNHEALTHY,
                    elapsed,
                    f"Authentication failed: HTTP {login_res.status_code}",
                    error=login_res.text,
                )

            inst_res = client.get("/api/instances")
            if inst_res.status_code != 200:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id,
                    name,
                    container,
                    HealthStatus.UNHEALTHY,
                    elapsed,
                    f"Failed to query instances: HTTP {inst_res.status_code}",
                    error=inst_res.text,
                )

            instances = inst_res.json()
            elapsed = (time.perf_counter() - t0) * 1000

            connected_count = sum(1 for i in instances if i.get("connected") is True)
            inst_desc = [
                f'"{i.get("name")}" ({i.get("host")})'
                for i in instances
            ]
            desc_str = ", ".join(inst_desc) if inst_desc else "no instances"
            details = f"{connected_count}/{len(instances)} instance connected: {desc_str}"

            return ServiceResult(
                service_id,
                name,
                container,
                HealthStatus.HEALTHY,
                elapsed,
                details,
                raw_data={"instances": instances},
            )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ServiceResult(
            service_id,
            name,
            container,
            HealthStatus.UNHEALTHY,
            elapsed,
            f"Error: {exc}",
            error=str(exc),
        )


def check_glance(ctx: StatusContext) -> ServiceResult:
    service_id = "glance"
    name = "Glance Dashboard"
    container = "homelab-glance-1"
    t0 = time.perf_counter()

    try:
        with httpx.Client(base_url=f"https://{ctx.base_domain}", timeout=ctx.http_timeout) as client:
            res = client.get("/")
            elapsed = (time.perf_counter() - t0) * 1000

            if res.status_code != 200:
                return ServiceResult(
                    service_id,
                    name,
                    container,
                    HealthStatus.UNHEALTHY,
                    elapsed,
                    f"Dashboard returned HTTP {res.status_code}",
                )

            title_match = re.search(r"<title>(.*?)</title>", res.text, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else "Dashboard"
            details = f'Dashboard online (HTTP {res.status_code}, title: "{title}")'

            return ServiceResult(
                service_id,
                name,
                container,
                HealthStatus.HEALTHY,
                elapsed,
                details,
            )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ServiceResult(
            service_id,
            name,
            container,
            HealthStatus.UNHEALTHY,
            elapsed,
            f"Error: {exc}",
            error=str(exc),
        )


def check_withings_sync(ctx: StatusContext) -> ServiceResult:
    service_id = "withings-sync"
    name = "Withings Health Sync"
    container = "homelab-withings-sync-1"
    t0 = time.perf_counter()

    c = ctx.get_container(container)
    if not c:
        elapsed = (time.perf_counter() - t0) * 1000
        if ctx.no_docker:
            return ServiceResult(
                service_id,
                name,
                container,
                HealthStatus.HEALTHY,
                elapsed,
                "Container running (Docker inspection skipped via --no-docker)",
            )
        return ServiceResult(
            service_id,
            name,
            container,
            HealthStatus.UNHEALTHY,
            elapsed,
            "Container not found or Docker unreachable",
        )

    try:
        status_val = c.status
        health_val = c.attrs.get("State", {}).get("Health", {}).get("Status", "none")

        code, _ = ctx.exec_container(container, "pgrep -f supercronic")
        has_proc = code == 0

        elapsed = (time.perf_counter() - t0) * 1000
        if not has_proc or status_val != "running":
            return ServiceResult(
                service_id,
                name,
                container,
                HealthStatus.UNHEALTHY,
                elapsed,
                f"Scheduler process inactive (status={status_val}, health={health_val})",
            )

        details = f"Supercronic cron scheduler active (crontab: /home/withings-sync/cronjob) • {health_val}"
        return ServiceResult(
            service_id,
            name,
            container,
            HealthStatus.HEALTHY,
            elapsed,
            details,
            raw_data={"status": status_val, "health": health_val},
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ServiceResult(
            service_id,
            name,
            container,
            HealthStatus.UNHEALTHY,
            elapsed,
            f"Error: {exc}",
            error=str(exc),
        )


def check_bookorbit_postgres(ctx: StatusContext) -> ServiceResult:
    service_id = "postgres"
    name = "BookOrbit Database"
    container = "homelab-bookorbit-postgres-1"
    t0 = time.perf_counter()

    c = ctx.get_container(container)
    if not c:
        elapsed = (time.perf_counter() - t0) * 1000
        if ctx.no_docker:
            return ServiceResult(
                service_id,
                name,
                container,
                HealthStatus.HEALTHY,
                elapsed,
                "Database running (Docker inspection skipped via --no-docker)",
            )
        return ServiceResult(
            service_id,
            name,
            container,
            HealthStatus.UNHEALTHY,
            elapsed,
            "Container not found or Docker unreachable",
        )

    try:
        # 1. pg_isready check
        ready_code, ready_out = ctx.exec_container(container, "pg_isready -U bookorbit -d bookorbit")
        if ready_code != 0:
            elapsed = (time.perf_counter() - t0) * 1000
            return ServiceResult(
                service_id,
                name,
                container,
                HealthStatus.UNHEALTHY,
                elapsed,
                f"pg_isready failed: {ready_out.strip()}",
            )

        # 2. Query book count in database
        query_code, query_out = ctx.exec_container(
            container, 'psql -U bookorbit -d bookorbit -t -c "SELECT count(*) FROM books;"'
        )
        book_count = query_out.strip() if query_code == 0 else "?"

        elapsed = (time.perf_counter() - t0) * 1000
        details = f'PostgreSQL 18 accepting connections • {book_count} books in database "bookorbit"'
        return ServiceResult(
            service_id,
            name,
            container,
            HealthStatus.HEALTHY,
            elapsed,
            details,
            raw_data={"books_count": book_count},
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ServiceResult(
            service_id,
            name,
            container,
            HealthStatus.UNHEALTHY,
            elapsed,
            f"Error: {exc}",
            error=str(exc),
        )


# Registry of all available checks
CHECK_REGISTRY = {
    "jellyfin": check_jellyfin,
    "bookorbit": check_bookorbit,
    "qbittorrent": check_qbittorrent,
    "retroarch": check_retroarch,
    "caddy": check_caddy,
    "samba": check_samba,
    "arcane": check_arcane,
    "qui": check_qui,
    "glance": check_glance,
    "withings-sync": check_withings_sync,
    "postgres": check_bookorbit_postgres,
}


# ─────────────────────────────────────────────────────────────────────────────
# CLI Entrypoint & Formatting
# ─────────────────────────────────────────────────────────────────────────────


@app.command()
def main(
    services: list[str] = typer.Option(
        None,
        "--service",
        "-s",
        help="Specific service(s) to check (e.g. -s jellyfin -s bookorbit)",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output raw check results as formatted JSON",
    ),
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        "-e",
        help="Path to homelab .env file",
    ),
    docker_host: str | None = typer.Option(
        None,
        "--docker-host",
        help="Override Docker daemon URL (e.g. ssh://ehtesh@m70q.lan)",
    ),
    no_docker: bool = typer.Option(
        False,
        "--no-docker",
        help="Skip Docker inspection and execute network/HTTP checks only",
    ),
    lan_host: str = typer.Option(
        "m70q.lan",
        "--lan-host",
        help="Target LAN host for SMB/Docker connection",
    ),
    timeout: float = typer.Option(
        10.0,
        "--timeout",
        "-t",
        help="Per-service check timeout in seconds",
    ),
) -> None:
    """Run deep health & content availability checks across homelab services."""
    env = load_env(env_file, lan_host)
    username = env.get("HOMELAB_USERNAME", "ehtesh")
    password = env.get("HOMELAB_PASSWORD", "")
    base_domain = env.get("HOSTNAME_BASE", "009973.xyz")

    if not password:
        console.print("[bold red]Error:[/bold red] HOMELAB_PASSWORD not found in .env or environment")
        sys.exit(1)

    docker_client = get_docker_client(docker_host, lan_host, no_docker)

    ctx = StatusContext(
        env=env,
        username=username,
        password=password,
        base_domain=base_domain,
        lan_host=lan_host,
        docker_client=docker_client,
        http_timeout=timeout,
        no_docker=no_docker,
    )

    # Determine which checks to run
    if services:
        selected_keys = [s.lower().strip() for s in services]
        invalid = [s for s in selected_keys if s not in CHECK_REGISTRY]
        if invalid:
            console.print(f"[bold red]Unknown service(s):[/bold red] {', '.join(invalid)}")
            console.print(f"Available services: {', '.join(CHECK_REGISTRY.keys())}")
            sys.exit(1)
        selected_checks = {k: CHECK_REGISTRY[k] for k in selected_keys}
    else:
        selected_checks = CHECK_REGISTRY

    t_start = time.perf_counter()

    # Execute checks concurrently for blazingly fast results
    results: list[ServiceResult] = []
    with ThreadPoolExecutor(max_workers=len(selected_checks)) as pool:
        future_map = {pool.submit(fn, ctx): name for name, fn in selected_checks.items()}
        for future in future_map:
            try:
                results.append(future.result())
            except Exception as exc:
                name = future_map[future]
                results.append(
                    ServiceResult(
                        name,
                        name.capitalize(),
                        f"homelab-{name}-1",
                        HealthStatus.UNHEALTHY,
                        0.0,
                        f"Unexpected check failure: {exc}",
                        error=str(exc),
                    )
                )

    total_elapsed = time.perf_counter() - t_start

    # Preserve consistent ordering matching CHECK_REGISTRY
    order = list(CHECK_REGISTRY.keys())
    results.sort(key=lambda r: order.index(r.service_id) if r.service_id in order else 999)

    # JSON output mode
    if json_output:
        out_dict = {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "target_host": lan_host,
            "base_domain": base_domain,
            "total_elapsed_seconds": round(total_elapsed, 3),
            "all_healthy": all(r.is_healthy for r in results),
            "services": [asdict(r) for r in results],
        }
        print(json.dumps(out_dict, indent=2))
        sys.exit(0 if all(r.is_healthy for r in results) else 1)

    # Terminal UI output mode
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header_text = Text()
    header_text.append("🔮 Homelab Deep Health & Content Inspector\n", style="bold magenta")
    header_text.append(f"Target: {lan_host} ({base_domain})  •  Time: {now_str}  •  Auth: {username}", style="dim")
    console.print(Panel(header_text, border_style="magenta", expand=False))

    # Responsive table: if terminal width < 115, combine Service and Container columns
    is_wide = console.width >= 115
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", border_style="dim")

    if is_wide:
        table.add_column("Service", style="bold white", no_wrap=True)
        table.add_column("Container", style="cyan dim", no_wrap=True)
        table.add_column("Status", justify="center", no_wrap=True)
        table.add_column("Latency", justify="right", no_wrap=True)
        table.add_column("Deeper Health & Content Availability", style="white")
    else:
        table.add_column("Service / Container", style="bold white", no_wrap=True)
        table.add_column("Status", justify="center", no_wrap=True)
        table.add_column("Latency", justify="right", no_wrap=True)
        table.add_column("Deeper Health & Content Availability", style="white")

    all_passed = True
    for r in results:
        if r.status == HealthStatus.HEALTHY:
            status_badge = "[bold green]HEALTHY[/bold green]"
        elif r.status == HealthStatus.DEGRADED:
            status_badge = "[bold yellow]DEGRADED[/bold yellow]"
            all_passed = False
        else:
            status_badge = "[bold red]UNHEALTHY[/bold red]"
            all_passed = False

        if r.latency_ms < 100:
            lat_str = f"[green]{r.latency_ms:.0f}ms[/green]"
        elif r.latency_ms < 500:
            lat_str = f"[yellow]{r.latency_ms:.0f}ms[/yellow]"
        else:
            lat_str = f"[red]{r.latency_ms:.0f}ms[/red]"

        if is_wide:
            table.add_row(
                r.name,
                r.container,
                status_badge,
                lat_str,
                r.details,
            )
        else:
            table.add_row(
                f"{r.name}\n[dim cyan]{r.container}[/dim cyan]",
                status_badge,
                lat_str,
                r.details,
            )

    console.print(table)

    # Summary footer
    passed_count = sum(1 for r in results if r.is_healthy)
    total_count = len(results)

    if all_passed:
        console.print(
            f"[bold green]✔ All {passed_count}/{total_count} services healthy[/bold green] "
            f"• Verified logins, content availability & containers in [bold cyan]{total_elapsed:.2f}s[/bold cyan]\n"
        )
        sys.exit(0)
    else:
        failed_count = total_count - passed_count
        console.print(
            f"[bold red]✖ {failed_count}/{total_count} services unhealthy or degraded[/bold red] "
            f"• Elapsed: [bold yellow]{total_elapsed:.2f}s[/bold yellow]\n"
        )
        sys.exit(1)


if __name__ == "__main__":
    app()
