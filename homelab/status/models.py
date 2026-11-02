"""Data models and context for homelab status inspection."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import StrEnum
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

    def base_url(self, subdomain: str | None = None) -> str:
        if subdomain:
            return f"https://{subdomain}.{self.base_domain}"
        return f"https://{self.base_domain}"

    async def get_container(self, name: str) -> Container | None:
        if not self.docker_client:
            return None

        def _get() -> Container | None:
            with self._docker_lock:
                try:
                    return self.docker_client.containers.get(name)
                except Exception:
                    return None

        return await anyio.to_thread.run_sync(_get)

    async def exec_container(self, container_name: str, cmd: str | list[str]) -> tuple[int, str]:
        """Safely execute command in container with thread synchronization."""
        if not self.docker_client:
            return (-1, "Docker client not available")

        def _sync_exec() -> tuple[int, str]:
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

        return await anyio.to_thread.run_sync(_sync_exec)

    async def get_container_logs(self, container_name: str, tail: int = 25) -> str:
        """Safely fetch recent container logs with thread synchronization."""
        if not self.docker_client:
            return ""

        def _get_logs() -> str:
            with self._docker_lock:
                try:
                    c = self.docker_client.containers.get(container_name)
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

        def _extract() -> str | None:
            with self._docker_lock:
                try:
                    cont = self.docker_client.containers.get(container_name)
                except Exception:
                    return None

                labels = cont.labels or {}
                for k in ("org.opencontainers.image.version", "version", "image.version"):
                    if (v := labels.get(k)) and v != "nightly":
                        m = re.match(r"^(\d+\.\d+(\.\d+)?)", v)
                        if m:
                            return f"v{m.group(1)}"
                        return v if v.startswith("v") else f"v{v}"

                env = dict(e.split("=", 1) for e in cont.attrs.get("Config", {}).get("Env", []) if "=" in e)
                for k in ("APP_VERSION", "PG_VERSION", "CADDY_VERSION", "VERSION"):
                    if v := env.get(k):
                        m = re.match(r"^(\d+\.\d+(\.\d+)?)", v)
                        if m:
                            return f"v{m.group(1)}"
                        return v if v.startswith("v") else f"v{v}"

                name = cont.name or container_name
                if "samba" in name:
                    try:
                        res = cont.exec_run("smbd -V")
                        if res.exit_code == 0:
                            m = re.search(r"(\d+\.\d+(\.\d+)?)", res.output.decode())
                            if m:
                                return f"v{m.group(1)}"
                    except Exception:
                        pass
                elif "glance" in name:
                    try:
                        res = cont.exec_run("/app/glance --version")
                        if res.exit_code == 0:
                            m = re.search(r"v?(\d+\.\d+(\.\d+)?)", res.output.decode())
                            if m:
                                return f"v{m.group(1)}"
                    except Exception:
                        pass

                return None

        return await anyio.to_thread.run_sync(_extract)

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
                        found.append({
                            "mount": path,
                            "total_bytes": total,
                            "used_bytes": used,
                            "free_bytes": free,
                            "use_percent": pct,
                        })
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
                            disks.append({
                                "mount": mount_name,
                                "total_bytes": total,
                                "used_bytes": used,
                                "free_bytes": free,
                                "use_percent": pct,
                            })
                        except Exception:
                            pass

        self._disk_usage = disks
        return disks
