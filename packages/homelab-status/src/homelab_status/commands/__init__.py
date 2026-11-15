"""Subcommand modules for homelab status inspector."""

from __future__ import annotations

from homelab_status.commands.jellyfin import jellyfin_command
from homelab_status.commands.samba import samba_command
from homelab_status.commands.vpn import vpn_command

__all__ = ["jellyfin_command", "samba_command", "vpn_command"]
