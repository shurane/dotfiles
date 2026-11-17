"""Custom exception hierarchy for homelab core and consumer tools."""

from __future__ import annotations


class HomelabError(RuntimeError):
    """Base exception for all homelab errors."""


class HomelabConfigError(HomelabError):
    """Raised when configuration or .env cannot be located, parsed, or validated."""


class HomelabConnectionError(HomelabError):
    """Raised when a homelab service, host, or Docker daemon is unreachable."""
