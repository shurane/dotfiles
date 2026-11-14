"""Subcommand modules for homelab status inspector."""

from __future__ import annotations

from commands.jellyfin import jellyfin_command
from commands.samba import samba_command
from commands.vpn import vpn_command

__all__ = ["jellyfin_command", "samba_command", "vpn_command"]
