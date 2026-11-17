"""Unit tests for homelab_core.models."""

from __future__ import annotations

import pytest
from homelab_core.models import HomelabAuth, HomelabConfig
from pydantic import ValidationError


def test_homelab_auth_valid() -> None:
    auth = HomelabAuth.model_validate({
        "HOMELAB_USERNAME": "admin",
        "HOMELAB_PASSWORD": "supersecretpassword",
    })
    assert auth.username == "admin"
    assert auth.password == "supersecretpassword"


def test_homelab_auth_missing_password_raises() -> None:
    with pytest.raises(ValidationError):
        HomelabAuth.model_validate({"HOMELAB_USERNAME": "admin"})


def test_homelab_config_valid() -> None:
    cfg = HomelabConfig.model_validate({
        "HOMELAB_USERNAME": "admin",
        "HOMELAB_PASSWORD": "supersecretpassword",
        "HOSTNAME_BASE": "home.lan",
        "HOMELAB_LAN_SUBNET": "192.168.1.0/24",
        "HOMELAB_SSH_USER": "ehtesh",
    })
    assert cfg.username == "admin"
    assert cfg.base_domain == "home.lan"
    assert cfg.effective_ssh_user == "ehtesh"


def test_homelab_config_fallback_ssh_user() -> None:
    cfg = HomelabConfig.model_validate({
        "HOMELAB_USERNAME": "myuser",
        "HOMELAB_PASSWORD": "supersecretpassword",
        "HOSTNAME_BASE": "home.lan",
        "HOMELAB_LAN_SUBNET": "192.168.1.0/24",
    })
    assert cfg.effective_ssh_user == "myuser"


def test_homelab_auth_masks_password_in_repr() -> None:
    auth = HomelabAuth.model_validate({
        "HOMELAB_USERNAME": "admin",
        "HOMELAB_PASSWORD": "supersecretpassword",
    })
    assert "supersecretpassword" not in repr(auth)
    assert "********" in repr(auth)
    assert auth.password == "supersecretpassword"

    cfg = HomelabConfig.model_validate({
        "HOMELAB_USERNAME": "admin",
        "HOMELAB_PASSWORD": "supersecretpassword",
        "HOSTNAME_BASE": "home.lan",
        "HOMELAB_LAN_SUBNET": "192.168.1.0/24",
    })
    assert "supersecretpassword" not in repr(cfg)
    assert "********" in repr(cfg)
    assert cfg.password == "supersecretpassword"
