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
    branches: list[str] = field(default_factory=list)
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
                    return (
                        raw.decode("utf-8", errors="replace")
                        if isinstance(raw, (bytes, bytearray))
                        else str(raw)
                    )
                except Exception:
                    return ""

        return await anyio.to_thread.run_sync(_get_logs)
