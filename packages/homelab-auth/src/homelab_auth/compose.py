from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from homelab_core.docker import (
    compose_stop as core_compose_stop,
)
from homelab_core.docker import (
    compose_up as core_compose_up,
)
from homelab_core.docker import (
    exec_container,
    get_compose_container,
    get_docker_client,
    list_compose_containers,
)
from homelab_core.errors import HomelabError

from homelab_auth.config import ROOT

if TYPE_CHECKING:
    from pathlib import Path

    import docker
    from docker.models.containers import Container

__all__ = [
    "compose_container",
    "compose_containers",
    "compose_exec",
    "compose_service",
    "compose_stop",
    "compose_up",
    "docker_client",
    "run",
]


def run(command: list[str], cwd: Path | str | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)  # noqa: S603


def docker_client() -> docker.DockerClient:
    client = get_docker_client()
    if client is None:
        raise RuntimeError("failed to connect to Docker daemon")
    return client


def compose_service(stack: str, service: str | None = None) -> str:
    return service or stack


def compose_containers(stack: str, service: str | None = None) -> list[Container]:
    service = compose_service(stack, service)
    return list_compose_containers(docker_client(), service)


def compose_container(stack: str, service: str | None = None) -> Container:
    service = compose_service(stack, service)
    client = docker_client()
    try:
        container = get_compose_container(client, service)
    except HomelabError as exc:
        raise RuntimeError(str(exc)) from exc
    if container is None:
        raise RuntimeError(
            f"expected one Compose container for {stack}/{service}, found 0"
        )
    return container


def compose_up(stack: str, service: str | None = None) -> None:
    svc_name = compose_service(stack, service)
    try:
        core_compose_up(svc_name, client=docker_client(), compose_dir=ROOT)
    except HomelabError as exc:
        raise RuntimeError(str(exc)) from exc


def compose_exec(stack: str, command: list[str], service: str | None = None) -> None:
    service = compose_service(stack, service)
    container = compose_container(stack, service)
    try:
        exec_container(container, command, check=True)
    except HomelabError as exc:
        raise RuntimeError(
            f"{stack}/{service} exec failed with exit code:\n{exc}"
        ) from exc


def compose_stop(stack: str, service: str | None = None) -> None:
    svc_name = compose_service(stack, service)
    try:
        core_compose_stop(svc_name, client=docker_client())
    except HomelabError as exc:
        raise RuntimeError(str(exc)) from exc

