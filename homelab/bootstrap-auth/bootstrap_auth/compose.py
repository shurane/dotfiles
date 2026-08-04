import subprocess

import docker
from docker.models.containers import Container

from .config import ROOT


def run(command: list[str], cwd: object | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def docker_client() -> docker.DockerClient:
    return docker.from_env()


def compose_service(stack: str, service: str | None = None) -> str:
    return service or stack


def compose_containers(stack: str, service: str | None = None) -> list[Container]:
    service = compose_service(stack, service)
    client = docker_client()
    return client.containers.list(
        all=True,
        filters={
            "label": [
                f"com.docker.compose.project={stack}",
                f"com.docker.compose.service={service}",
            ],
        },
    )


def compose_container(stack: str, service: str | None = None) -> Container:
    service = compose_service(stack, service)
    containers = compose_containers(stack, service)
    if len(containers) != 1:
        raise RuntimeError(f"expected one Compose container for {stack}/{service}, found {len(containers)}")
    return containers[0]


def compose_up(stack: str, service: str | None = None) -> None:
    service = compose_service(stack, service)
    containers = compose_containers(stack, service)
    if len(containers) == 1:
        container = containers[0]
        container.reload()
        if container.status not in {"running", "restarting"}:
            container.start()
        return
    if len(containers) > 1:
        raise RuntimeError(f"expected at most one Compose container for {stack}/{service}, found {len(containers)}")

    # docker-py manages Docker Engine resources, but it does not apply Compose
    # YAML. Keep first creation/reconciliation on the Compose CLI.
    run(["docker", "compose", "up", "-d", service], cwd=ROOT / stack)


def compose_logs(stack: str, service: str | None = None) -> str:
    return compose_container(stack, service).logs(stdout=True, stderr=True).decode(errors="replace")


def compose_exec(stack: str, command: list[str], service: str | None = None) -> None:
    service = compose_service(stack, service)
    result = compose_container(stack, service).exec_run(command, stdout=True, stderr=True)
    if result.exit_code != 0:
        output_text = result.output.decode(errors="replace") if isinstance(result.output, bytes) else str(result.output)
        raise RuntimeError(f"{stack}/{service} exec failed with exit code {result.exit_code}:\n{output_text}")


def compose_stop(stack: str, service: str | None = None) -> None:
    container = compose_container(stack, service)
    container.stop()
