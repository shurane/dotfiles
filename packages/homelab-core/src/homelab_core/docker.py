"""Docker client resolution, container inspection, and execution helpers."""

from __future__ import annotations

import atexit
import contextlib
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

import docker
import docker.errors

from homelab_core.env import find_homelab_root
from homelab_core.errors import HomelabConnectionError, HomelabError
from homelab_core.network import get_ssh_user, is_target_local, resolve_target_host
from homelab_core.services import Service

if TYPE_CHECKING:
    from docker.models.containers import Container

__all__ = [
    "compose_stop",
    "compose_up",
    "exec_container",
    "get_compose_container",
    "get_docker_client",
    "list_compose_containers",
    "require_docker_client",
]


def _get_ssh_tunnel_client(
    lan_host: str,
    ssh_user: str | None = None,
    timeout: float = 3.0,
) -> docker.DockerClient | None:
    """Establish or reuse an OpenSSH UNIX socket tunnel to remote docker.sock with PID isolation."""
    user = get_ssh_user(ssh_user)
    runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir()))
    # Process-isolated socket file to prevent concurrency collisions
    sock_path = runtime_dir / f"homelab-docker-{os.getuid()}-{os.getpid()}.sock"
    sock_str = str(sock_path)

    # 1. Reuse existing healthy socket if already alive in this process
    if sock_path.exists():
        with contextlib.suppress(Exception):
            c = docker.DockerClient(base_url=f"unix://{sock_str}", timeout=1.0)
            c.ping()
            return c
        with contextlib.suppress(OSError):
            sock_path.unlink(missing_ok=True)

    cmd = [
        "ssh",
        "-N",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={max(int(timeout), 1)}",
        "-L",
        f"{sock_str}:/var/run/docker.sock",
        f"{user}@{lan_host}",
    ]
    try:
        proc = subprocess.Popen(  # noqa: S603
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None

    def _cleanup() -> None:
        try:
            proc.terminate()
            proc.wait(timeout=0.3)
        except Exception:
            with contextlib.suppress(Exception):
                proc.kill()
        with contextlib.suppress(OSError):
            sock_path.unlink(missing_ok=True)

    atexit.register(_cleanup)

    # Wait for the tunnel socket to be established
    t_end = time.perf_counter() + timeout
    while time.perf_counter() < t_end:
        if sock_path.exists():
            with contextlib.suppress(docker.errors.DockerException, OSError):
                c = docker.DockerClient(base_url=f"unix://{sock_str}", timeout=1.0)
                c.ping()
                return c
        time.sleep(0.02)

    _cleanup()
    return None


def get_docker_client(
    docker_host: str | None = None,
    lan_host: str | None = None,
    no_docker: bool = False,
    ssh_user: str | None = None,
) -> docker.DockerClient | None:
    """Resolve Docker client using local socket, OpenSSH tunnel, or DOCKER_HOST environment variable."""
    if no_docker:
        return None

    if docker_host:
        with contextlib.suppress(docker.errors.DockerException, OSError):
            c = docker.DockerClient(base_url=docker_host, timeout=5)
            c.ping()
            return c
        return None

    if os.environ.get("DOCKER_HOST"):
        with contextlib.suppress(docker.errors.DockerException, OSError):
            c = docker.from_env()
            c.ping()
            return c

    if lan_host is None:
        with contextlib.suppress(Exception):
            lan_host = resolve_target_host()

    target_host = lan_host or "localhost"

    # Connect to local UNIX socket if target is local
    if is_target_local(target_host):
        sock_p = Path("/var/run/docker.sock")
        if sock_p.exists() and os.access(sock_p, os.R_OK):
            with contextlib.suppress(docker.errors.DockerException, OSError):
                c = docker.from_env()
                c.ping()
                return c
        return None

    # Connect to remote target via OpenSSH tunnel
    return _get_ssh_tunnel_client(target_host, ssh_user, timeout=3.0)


def require_docker_client(
    docker_host: str | None = None,
    lan_host: str | None = None,
    no_docker: bool = False,
    ssh_user: str | None = None,
) -> docker.DockerClient:
    """Resolve Docker client or raise HomelabConnectionError if daemon is unreachable."""
    client = get_docker_client(
        docker_host=docker_host,
        lan_host=lan_host,
        no_docker=no_docker,
        ssh_user=ssh_user,
    )
    if client is None:
        raise HomelabConnectionError("Failed to connect to Docker daemon")
    return client


def list_compose_containers(
    client: docker.DockerClient,
    service: str | Service,
) -> list[Container]:
    """List all containers for a Compose service using the Compose service label."""
    svc_name = service.value if isinstance(service, Service) else str(service)
    return client.containers.list(
        all=True,
        filters={"label": [f"com.docker.compose.service={svc_name}"]},
    )


def get_compose_container(
    client: docker.DockerClient,
    service: str | Service,
) -> Container | None:
    """Find a single container for a Compose service, or None if not found.

    Raises:
        HomelabError: If more than one container matches the Compose service label.
    """
    containers = list_compose_containers(client, service)
    if not containers:
        return None
    if len(containers) > 1:
        svc_name = service.value if isinstance(service, Service) else str(service)
        raise HomelabError(
            f"Expected at most one Compose container for service {svc_name!r}, found {len(containers)}"
        )
    return containers[0]


def exec_container(
    container: Container,
    cmd: list[str] | str,
    check: bool = False,
) -> tuple[int, str]:
    """Execute command inside a container, returning (exit_code, output_text).

    Decodes binary output gracefully. If check=True and exit_code != 0,
    raises HomelabError with container output.
    """
    res = container.exec_run(cmd, stdout=True, stderr=True)
    out = (
        res.output.decode("utf-8", errors="replace")
        if isinstance(res.output, (bytes, bytearray))
        else str(res.output or "")
    )
    if check and res.exit_code != 0:
        raise HomelabError(
            f"Container {container.name} command {cmd!r} failed with exit code {res.exit_code}:\n{out}"
        )
    return (res.exit_code, out)


def compose_up(
    service: str | Service,
    client: docker.DockerClient | None = None,
    compose_dir: Path | None = None,
) -> None:
    """Ensure a Compose service container is running, starting it or invoking 'docker compose up -d'."""
    svc_name = service.value if isinstance(service, Service) else str(service)
    docker_c = client or require_docker_client()
    containers = list_compose_containers(docker_c, svc_name)
    if len(containers) == 1:
        container = containers[0]
        container.reload()
        if container.status not in {"running", "restarting"}:
            container.start()
        return
    if len(containers) > 1:
        raise HomelabError(
            f"Expected at most one Compose container for service {svc_name!r}, found {len(containers)}"
        )

    root = compose_dir or find_homelab_root()
    cwd = root if (root / "docker-compose.yml").exists() else root / svc_name
    subprocess.run(["docker", "compose", "up", "-d", svc_name], cwd=cwd, check=True)  # noqa: S603, S607


def compose_stop(
    service: str | Service,
    client: docker.DockerClient | None = None,
) -> None:
    """Stop a running Compose service container."""
    svc_name = service.value if isinstance(service, Service) else str(service)
    docker_c = client or require_docker_client()
    container = get_compose_container(docker_c, svc_name)
    if container is None:
        raise HomelabError(f"No Compose container found for service {svc_name!r}")
    container.reload()
    if container.status in {"running", "restarting"}:
        container.stop()

