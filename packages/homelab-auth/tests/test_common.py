from pathlib import Path

import pytest
import typer
from homelab_auth.common import build_options, load_env
from homelab_core.services import Service


def test_load_env_parses_simple_quoted_and_ignored_lines(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
        # ignored
        HOMELAB_USERNAME=username
        HOMELAB_PASSWORD="password"
        EMPTY_LINE_IGNORED
        SINGLE='value'
        """
    )

    assert load_env(env_file) == {
        "HOMELAB_USERNAME": "username",
        "HOMELAB_PASSWORD": "password",
        "SINGLE": "value",
    }


def test_build_options_parses_services_to_enum_values() -> None:
    options = build_options(skip_backup=True, parallel=True, services_value="qui,jellyfin")

    assert options.apply is False
    assert options.skip_backup is True
    assert options.parallel is True
    assert options.services == (Service.QUI, Service.JELLYFIN)


def test_build_options_accepts_explicit_apply() -> None:
    options = build_options(skip_backup=False, parallel=False, services_value="jellyfin", apply=True)

    assert options.apply is True


def test_build_options_rejects_unknown_services() -> None:
    with pytest.raises(typer.BadParameter, match="unknown services"):
        build_options(skip_backup=False, parallel=False, services_value="qui,nope")


def test_build_options_rejects_empty_services() -> None:
    with pytest.raises(typer.BadParameter, match="must include at least one service"):
        build_options(skip_backup=False, parallel=False, services_value=" , ")
