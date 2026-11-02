import subprocess

import docker
from docker.models.containers import Container

from config import ROOT


def run(command: list[str], cwd: object | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def docker_client() -> docker.DockerClient:
    return docker.from_env()


def compose_service(stack: str, service: str | None = None) -> str:
    return service or stack


def compose_containers(stack: str, service: str | None = None) -> list[Container]:
    service = compose_service(stack, service)
    client = docker_client()
    containers = client.containers.list(
        all=True,
        filters={"label": [f"com.docker.compose.service={service}"]},
    )
    if not containers:
        containers = client.containers.list(
            all=True,
            filters={
                "label": [
                    f"com.docker.compose.project={stack}",
                    f"com.docker.compose.service={service}",
                ],
            },
        )
    return containers


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
    cwd = ROOT if (ROOT / "docker-compose.yml").exists() else ROOT / stack
    run(["docker", "compose", "up", "-d", service], cwd=cwd)


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


def get_container_ip(service: str, network: str = "proxy-tier") -> str | None:
    """Look up a Compose service container's IPv4 address on the specified Docker network."""
    try:
        client = docker_client()
        containers = client.containers.list(filters={"label": [f"com.docker.compose.service={service}"]})
        if not containers:
            return None
        networks = containers[0].attrs.get("NetworkSettings", {}).get("Networks", {})
        net_info = networks.get(network)
        if net_info and net_info.get("IPAddress"):
            return str(net_info["IPAddress"])
        for net in networks.values():
            if net.get("IPAddress"):
                return str(net["IPAddress"])
    except Exception:
        pass
    return None
