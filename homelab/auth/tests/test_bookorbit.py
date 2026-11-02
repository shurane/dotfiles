from unittest.mock import MagicMock, patch

import pytest

from models import HomelabAuth, ServiceName
from services.bookorbit import (
    apply_bookorbit,
    bookorbit_login,
    check_bookorbit,
    verify_bookorbit,
    wait_for_bookorbit,
)


@pytest.fixture
def auth() -> HomelabAuth:
    return HomelabAuth(HOMELAB_USERNAME="testuser", HOMELAB_PASSWORD="testpassword123")


def test_bookorbit_service_name_enum() -> None:
    assert ServiceName.BOOKORBIT == "bookorbit"


def test_bookorbit_login_success() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client.post.return_value = mock_response

    assert bookorbit_login(mock_client, "user", "pass") is True
    mock_client.post.assert_called_once()


def test_bookorbit_login_failure() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_client.post.return_value = mock_response

    assert bookorbit_login(mock_client, "user", "wrong") is False


def test_check_bookorbit_uses_login(auth: HomelabAuth) -> None:
    with patch("services.bookorbit.bookorbit_login", return_value=True) as mock_login:
        assert check_bookorbit(auth) is True
        mock_login.assert_called_once()


def test_apply_bookorbit_skips_if_already_valid(auth: HomelabAuth) -> None:
    with (
        patch("services.bookorbit.compose_up") as mock_up,
        patch("services.bookorbit.wait_for_bookorbit"),
        patch("services.bookorbit.bookorbit_login", return_value=True),
        patch("services.bookorbit.compose_exec") as mock_exec,
    ):
        apply_bookorbit(auth)
        assert mock_up.call_count == 2
        mock_exec.assert_not_called()


def test_apply_bookorbit_executes_upsert_when_invalid(auth: HomelabAuth) -> None:
    with (
        patch("services.bookorbit.compose_up"),
        patch("services.bookorbit.wait_for_bookorbit"),
        patch("services.bookorbit.bookorbit_login", return_value=False),
        patch("services.bookorbit.compose_exec") as mock_exec,
    ):
        apply_bookorbit(auth)
        mock_exec.assert_called_once()
        stack, cmd = mock_exec.call_args[0]
        service = mock_exec.call_args[1].get("service")
        assert stack == "bookorbit"
        assert service == "bookorbit-postgres"
        assert cmd[0] == "psql"
        sql = cmd[-1]
        assert "INSERT INTO users" in sql
        assert "testuser" in sql
        assert "ON CONFLICT (username) DO UPDATE" in sql


def test_verify_bookorbit_raises_on_failure(auth: HomelabAuth) -> None:
    with (
        patch("services.bookorbit.wait_for_bookorbit"),
        patch("services.bookorbit.bookorbit_login", return_value=False),
        pytest.raises(RuntimeError, match="BookOrbit shared credential login failed"),
    ):
        verify_bookorbit(auth)


def test_wait_for_bookorbit_times_out() -> None:
    mock_client = MagicMock()
    mock_client.get.side_effect = Exception("Connection refused")
    with pytest.raises(RuntimeError, match="timed out waiting"):
        wait_for_bookorbit(mock_client, timeout_seconds=0)
