"""BookOrbit authentication bootstrap service."""

import time

import bcrypt
import httpx

from compose import compose_exec, compose_up
from config import BOOKORBIT_URL
from models import HomelabAuth


def wait_for_bookorbit(client: httpx.Client, timeout_seconds: int = 60) -> None:
    """Wait for BookOrbit healthcheck endpoint to report 200."""
    url = f"{BOOKORBIT_URL}/api/v1/health"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = client.get(url)
            if response.status_code == 200:
                return
        except httpx.HTTPError, ValueError:
            pass
        time.sleep(2)
    raise RuntimeError(f"timed out waiting for {url}")


def bookorbit_login(client: httpx.Client, username: str, password: str) -> bool:
    """Attempt login against BookOrbit auth API."""
    try:
        response = client.post(
            f"{BOOKORBIT_URL}/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        return response.status_code == 200
    except Exception:
        return False


def check_bookorbit(auth: HomelabAuth) -> bool:
    """Check if BookOrbit accepts current centralized credentials."""
    with httpx.Client(timeout=10) as client:
        return bookorbit_login(client, auth.username, auth.password)


def apply_bookorbit(auth: HomelabAuth) -> None:
    """Ensure BookOrbit credentials match centralized credentials via database upsert."""
    print("Applying BookOrbit credentials")
    compose_up("bookorbit", "bookorbit-postgres")
    compose_up("bookorbit")

    with httpx.Client(timeout=15) as client:
        try:
            wait_for_bookorbit(client, timeout_seconds=15)
            if bookorbit_login(client, auth.username, auth.password):
                return
        except Exception:
            pass

    password_hash = bcrypt.hashpw(auth.password.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")
    escaped_user = auth.username.replace("'", "''")
    escaped_hash = password_hash.replace("'", "''")

    sql = (
        f"INSERT INTO users (username, name, email, password_hash, is_superuser, failed_login_attempts, locked_until) "
        f"VALUES ('{escaped_user}', '{escaped_user}', '{escaped_user}@localhost', '{escaped_hash}', true, 0, NULL) "
        f"ON CONFLICT (username) DO UPDATE SET "
        f"password_hash = EXCLUDED.password_hash, "
        f"failed_login_attempts = 0, "
        f"locked_until = NULL;"
    )

    compose_exec(
        "bookorbit",
        ["psql", "-U", "bookorbit", "-d", "bookorbit", "-c", sql],
        service="bookorbit-postgres",
    )


def verify_bookorbit(auth: HomelabAuth) -> None:
    """Verify that BookOrbit authentication succeeds with centralized credentials."""
    print("Verifying BookOrbit login")
    with httpx.Client(timeout=15) as client:
        wait_for_bookorbit(client, timeout_seconds=30)
        if not bookorbit_login(client, auth.username, auth.password):
            raise RuntimeError("BookOrbit shared credential login failed")


def apply_and_verify_bookorbit(auth: HomelabAuth) -> None:
    apply_bookorbit(auth)
    verify_bookorbit(auth)
