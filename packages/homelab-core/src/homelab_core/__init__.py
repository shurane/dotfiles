"""Core shared utilities, environment discovery, services, and networking for homelab tools."""

from __future__ import annotations

from homelab_core.db import wait_for_sqlite_table
from homelab_core.docker import (
    compose_stop,
    compose_up,
    exec_container,
    get_compose_container,
    get_docker_client,
    list_compose_containers,
    require_docker_client,
)
from homelab_core.env import (
    ensure_state_dir,
    find_homelab_env,
    find_homelab_root,
    get_env_setting,
    load_homelab_env,
)
from homelab_core.errors import HomelabConfigError, HomelabConnectionError, HomelabError
from homelab_core.formatting import (
    format_bytes,
    format_connection_badge,
    format_path,
    format_route_line,
    format_size,
    format_speed,
    render_command_header,
    render_sparkbar,
)
from homelab_core.models import HomelabAuth, HomelabConfig
from homelab_core.network import (
    TargetConnection,
    classify_route,
    get_ssh_user,
    is_target_local,
    resolve_target_connection,
    resolve_target_host,
    run_ssh_command,
)
from homelab_core.services import (
    SERVICE_CATALOG,
    ContainerName,
    Service,
    ServiceMetadata,
    get_service_by_container,
    get_service_meta,
    make_jellyfin_auth_headers,
    resolve_service_health_url,
    resolve_service_url,
    wait_for_http,
)

__all__ = [
    "SERVICE_CATALOG",
    "ContainerName",
    "HomelabAuth",
    "HomelabConfig",
    "HomelabConfigError",
    "HomelabConnectionError",
    "HomelabError",
    "Service",
    "ServiceMetadata",
    "TargetConnection",
    "classify_route",
    "compose_stop",
    "compose_up",
    "ensure_state_dir",
    "exec_container",
    "find_homelab_env",
    "find_homelab_root",
    "format_bytes",
    "format_connection_badge",
    "format_path",
    "format_route_line",
    "format_size",
    "format_speed",
    "get_compose_container",
    "get_docker_client",
    "get_env_setting",
    "get_service_by_container",
    "get_service_meta",
    "get_ssh_user",
    "is_target_local",
    "list_compose_containers",
    "load_homelab_env",
    "make_jellyfin_auth_headers",
    "render_command_header",
    "render_sparkbar",
    "require_docker_client",
    "resolve_service_health_url",
    "resolve_service_url",
    "resolve_target_connection",
    "resolve_target_host",
    "run_ssh_command",
    "wait_for_http",
    "wait_for_sqlite_table",
]
