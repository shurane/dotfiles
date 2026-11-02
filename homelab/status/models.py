"""Data models and context for homelab status inspection."""

from __future__ import annotations

import contextlib
import json
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio

if TYPE_CHECKING:
    import docker
    from docker.models.containers import Container


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
    summary: str
    version: str | None = None
    branches: list[str] = field(default_factory=list)
    raw_data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def is_healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY


@dataclass
class TargetConnection:
    host: str
    ip: str
    route: str  # "local", "lan", "tailscale", "wan"
    description: str  # "Local Host (UNIX socket)", "Direct LAN", "Tailscale MagicDNS", "WAN / Remote"
    is_local: bool = False


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
    connection: TargetConnection | None = None
    _docker_lock: threading.Lock = field(default_factory=threading.Lock)
    _disk_usage: list[dict[str, Any]] | None = field(default=None, init=False)
    _containers_cache: dict[str, Container] | None = field(default=None, init=False)
    _version_cache: dict[str, str] | None = field(default=None, init=False)

    def _get_version_cache(self) -> dict[str, str]:
        if self._version_cache is not None:
            return self._version_cache
        cache_file = Path.home() / ".cache" / "homelab" / "image_versions.json"
        if cache_file.exists():
            try:
                self._version_cache = json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                self._version_cache = {}
        else:
            self._version_cache = {}
        return self._version_cache

    def _save_version_cache(self, image_id: str, version: str) -> None:
        cache = self._get_version_cache()
        cache[image_id] = version
        cache_file = Path.home() / ".cache" / "homelab" / "image_versions.json"
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        except Exception:
            pass

    @property
    def disk_usage(self) -> list[dict[str, Any]] | None:
        return self._disk_usage

    def base_url(self, subdomain: str | None = None) -> str:
        if subdomain:
            return f"https://{subdomain}.{self.base_domain}"
        return f"https://{self.base_domain}"

    @property
    def _needs_docker_lock(self) -> bool:
        if not self.docker_client:
            return False
        base = getattr(self.docker_client.api, "base_url", "")
        return str(base).startswith("ssh://")

    async def get_all_containers(self) -> dict[str, Container]:
        """Fetch all running containers in one single Docker API call and cache them."""
        if self._containers_cache is not None:
            return self._containers_cache

        if not self.docker_client:
            self._containers_cache = {}
            return self._containers_cache

        client = self.docker_client

        def _fetch() -> dict[str, Container]:
            lock = self._docker_lock if self._needs_docker_lock else contextlib.nullcontext()
            with lock:
                try:
                    conts = client.containers.list()
                    return {c.name.lstrip("/"): c for c in conts}
                except Exception:
                    return {}

        self._containers_cache = await anyio.to_thread.run_sync(_fetch)
        return self._containers_cache

    async def get_container(self, name: str) -> Container | None:
        """Fetch container by name, checking pre-fetched cache first."""
        clean_name = name.lstrip("/")
        conts = await self.get_all_containers()
        if clean_name in conts:
            return conts[clean_name]

        if not self.docker_client:
            return None

        client = self.docker_client

        def _get() -> Container | None:
            lock = self._docker_lock if self._needs_docker_lock else contextlib.nullcontext()
            with lock:
                try:
                    return client.containers.get(clean_name)
                except Exception:
                    return None

        return await anyio.to_thread.run_sync(_get)

    async def exec_container(self, container_name: str, cmd: str | list[str]) -> tuple[int, str]:
        """Safely execute command in container with thread synchronization."""
        if not self.docker_client:
            return (-1, "Docker client not available")

        c = await self.get_container(container_name)
        if not c:
            return (-1, f"Container {container_name} not found")

        def _sync_exec() -> tuple[int, str]:
            lock = self._docker_lock if self._needs_docker_lock else contextlib.nullcontext()
            with lock:
                try:
                    res = c.exec_run(cmd)
                    out = (
                        res.output.decode("utf-8", errors="replace")
                        if isinstance(res.output, (bytes, bytearray))
                        else str(res.output)
                    )
                    return (res.exit_code, out)
                except Exception as exc:
                    return (-1, str(exc))

        return await anyio.to_thread.run_sync(_sync_exec)

    async def get_container_logs(self, container_name: str, tail: int = 25) -> str:
        """Safely fetch recent container logs with thread synchronization."""
        if not self.docker_client:
            return ""

        c = await self.get_container(container_name)
        if not c:
            return ""

        def _get_logs() -> str:
            lock = self._docker_lock if self._needs_docker_lock else contextlib.nullcontext()
            with lock:
                try:
                    raw = c.logs(tail=tail)
                    return raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
                except Exception:
                    return ""

        return await anyio.to_thread.run_sync(_get_logs)

    async def get_container_version(self, container_name: str) -> str | None:
        """Extract software version from container labels, environment variables, or exec."""
        if not self.docker_client:
            return None

        import re

        cont = await self.get_container(container_name)
        if not cont:
            return None

        attrs = cont.attrs or {}
        img_id = str(attrs.get("Image", ""))
        vcache = self._get_version_cache()
        if img_id and img_id in vcache:
            return vcache[img_id]

        labels = cont.labels or {}
        for k in ("org.opencontainers.image.version", "version", "image.version"):
            if (v := labels.get(k)) and v != "nightly":
                m = re.match(r"^(\d+\.\d+(\.\d+)?)", v)
                ver = f"v{m.group(1)}" if m else (v if v.startswith("v") else f"v{v}")
                if img_id:
                    self._save_version_cache(img_id, ver)
                return ver

        config = attrs.get("Config") or {}
        raw_env = config.get("Env") or []
        env = dict(e.split("=", 1) for e in raw_env if isinstance(e, str) and "=" in e)
        for k in ("APP_VERSION", "PG_VERSION", "CADDY_VERSION", "VERSION"):
            if v := env.get(k):
                m = re.match(r"^(\d+\.\d+(\.\d+)?)", v)
                ver = f"v{m.group(1)}" if m else (v if v.startswith("v") else f"v{v}")
                if img_id:
                    self._save_version_cache(img_id, ver)
                return ver

        name = cont.name or container_name
        if "samba" in name:
            code, out = await self.exec_container(container_name, "smbd -V")
            if code == 0:
                m = re.search(r"(\d+\.\d+(\.\d+)?)", out)
                if m:
                    ver = f"v{m.group(1)}"
                    if img_id:
                        self._save_version_cache(img_id, ver)
                    return ver
        elif "glance" in name:
            code, out = await self.exec_container(container_name, "/app/glance --version")
            if code == 0:
                m = re.search(r"v?(\d+\.\d+(\.\d+)?)", out)
                if m:
                    ver = f"v{m.group(1)}"
                    if img_id:
                        self._save_version_cache(img_id, ver)
                    return ver

        return None

    async def get_disk_usage(self) -> list[dict[str, Any]]:
        """Fetch disk usage for storage partitions (e.g. /mnt/mango and /)."""
        if self._disk_usage is not None:
            return self._disk_usage

        disks: list[dict[str, Any]] = []

        # 1. If running locally on target host:
        if self.connection and self.connection.is_local:

            def _local_stat() -> list[dict[str, Any]]:
                import os

                found = []
                targets = ["/mnt/mango", "/"] if os.path.exists("/mnt/mango") else ["/"]
                for path in targets:
                    try:
                        st = os.statvfs(path)
                        total = st.f_blocks * st.f_frsize
                        free = st.f_bavail * st.f_frsize
                        used = total - (st.f_bfree * st.f_frsize)
                        total_avail = used + free
                        pct = round(used / total_avail * 100) if total_avail else 0
                        found.append(
                            {
                                "mount": path,
                                "total_bytes": total,
                                "used_bytes": used,
                                "free_bytes": free,
                                "use_percent": pct,
                            }
                        )
                    except Exception:
                        pass
                return found

            disks = await anyio.to_thread.run_sync(_local_stat)
            self._disk_usage = disks
            return disks

        # 2. If running remotely with docker client:
        if self.docker_client and not self.no_docker:
            code, out = await self.exec_container("homelab-qbittorrent-1", "df -k /mnt/mango/torrents /")
            if code != 0:
                code, out = await self.exec_container("homelab-samba-1", "df -k /shares/mango /")

            if code == 0:
                for line in out.strip().splitlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 6:
                        m = parts[5]
                        if "mango" in m or "downloads" in m:
                            mount_name = "/mnt/mango"
                        elif m == "/":
                            mount_name = "/"
                        else:
                            continue

                        if any(d["mount"] == mount_name for d in disks):
                            continue

                        try:
                            total = int(parts[1]) * 1024
                            used = int(parts[2]) * 1024
                            free = int(parts[3]) * 1024
                            pct = int(parts[4].rstrip("%"))
                            disks.append(
                                {
                                    "mount": mount_name,
                                    "total_bytes": total,
                                    "used_bytes": used,
                                    "free_bytes": free,
                                    "use_percent": pct,
                                }
                            )
                        except Exception:
                            pass

        self._disk_usage = disks
        return disks
