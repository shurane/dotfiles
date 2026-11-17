"""Core Pydantic models and schemas for homelab configuration and credentials."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any


class HomelabAuth(BaseModel):
    """Core credentials loaded from environment or .env file."""

    model_config = ConfigDict(extra="ignore")

    username: str = Field(default="username", alias="HOMELAB_USERNAME", min_length=1)
    password: str = Field(alias="HOMELAB_PASSWORD", min_length=1)

    @override
    def __repr_args__(self) -> Sequence[tuple[str | None, Any]]:
        """Mask sensitive password in string/repr outputs."""
        masked: list[tuple[str | None, Any]] = []
        for k, v in super().__repr_args__():
            if k == "password":
                masked.append((k, "********"))
            else:
                masked.append((k, v))
        return masked


class HomelabConfig(HomelabAuth):
    """Full homelab infrastructure configuration loaded from .env or environment with validation."""

    base_domain: str = Field(alias="HOSTNAME_BASE", min_length=1)
    lan_subnet: str = Field(alias="HOMELAB_LAN_SUBNET", min_length=1)
    hostname: str | None = Field(default=None, alias="HOMELAB_HOSTNAME")
    ssh_user: str | None = Field(default=None, alias="HOMELAB_SSH_USER")
    node_name: str | None = Field(default=None, alias="HOMELAB_NODE_NAME")

    @property
    def effective_ssh_user(self) -> str:
        """Return explicit SSH user override or fall back to homelab username."""
        return self.ssh_user or self.username
