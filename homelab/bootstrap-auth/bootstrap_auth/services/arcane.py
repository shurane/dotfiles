import sys
import time
from typing import Any

import httpx

from ..common import ensure_state_dir
from ..compose import compose_up
from ..config import ARCANE_URL, ROOT
from ..http_models import ArcaneLoginRequest, ArcanePasswordRequest, ArcaneResponse, ArcaneUpdateUserRequest, ArcaneUser
from ..models import HomelabAuth


def wait_for_arcane(client: httpx.Client, timeout_seconds: int = 60) -> None:
    url = f"{ARCANE_URL}/api/health"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = client.get(url)
            if response.status_code == 200 and response.json().get("status") == "UP":
                return
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(2)
    raise RuntimeError(f"timed out waiting for {url}")


def arcane_login(client: httpx.Client, username: str, password: str) -> bool:
    payload = ArcaneLoginRequest(username=username, password=password)
    response = client.post(f"{ARCANE_URL}/api/auth/login", json=payload.model_dump())
    if response.status_code == 200:
        if not response.content and "set-cookie" not in response.headers:
            print(f"Arcane login for {username!r} returned empty 200 without a session cookie", file=sys.stderr)
            return False
        return True
    if response.status_code == 401:
        print(f"Arcane login failed for {username!r}: {response.text[:240]}", file=sys.stderr)
        return False
    response.raise_for_status()
    return False


def arcane_current_user(client: httpx.Client) -> ArcaneUser:
    response = client.get(f"{ARCANE_URL}/api/auth/me")
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    parsed = ArcaneResponse.model_validate(payload)
    if parsed.data is None:
        return ArcaneUser.model_validate(payload)
    return parsed.data


def arcane_change_password(client: httpx.Client, current_password: str, auth: HomelabAuth) -> None:
    payload = ArcanePasswordRequest(current_password=current_password, new_password=auth.password)
    response = client.post(f"{ARCANE_URL}/api/auth/password", json=payload.model_dump(by_alias=True))
    if response.status_code == 400 and "same" in response.text.lower():
        return
    response.raise_for_status()


def arcane_update_via_api(client: httpx.Client, user: ArcaneUser, auth: HomelabAuth) -> None:
    payload = ArcaneUpdateUserRequest(
        username=auth.username,
        password=auth.password,
        display_name=auth.username,
        email="admin@localhost",
    )
    response = client.put(f"{ARCANE_URL}/api/users/{user.id}", json=payload.model_dump(by_alias=True))
    response.raise_for_status()


def apply_arcane(client: httpx.Client, auth: HomelabAuth) -> None:
    print("Applying Arcane credentials")
    ensure_state_dir(ROOT / "arcane" / "backups")
    ensure_state_dir(ROOT / "arcane" / "builds")
    compose_up("arcane")
    wait_for_arcane(client)

    if arcane_login(client, auth.username, auth.password):
        user = arcane_current_user(client)
        arcane_change_password(client, auth.password, auth)
        arcane_update_via_api(client, user, auth)
        return

    if arcane_login(client, "arcane", "arcane-admin"):
        user = arcane_current_user(client)
        arcane_change_password(client, "arcane-admin", auth)
        arcane_update_via_api(client, user, auth)
        return

    raise RuntimeError("Arcane accepts neither the current centralized credentials nor the first-run default")


def verify_arcane(auth: HomelabAuth) -> None:
    print("Verifying Arcane login")
    with httpx.Client(timeout=15) as client:
        if not arcane_login(client, auth.username, auth.password):
            raise RuntimeError("Arcane shared credential login failed")
        user = arcane_current_user(client)
    if user.username != auth.username:
        raise RuntimeError("Arcane username did not update")


def apply_and_verify_arcane(auth: HomelabAuth) -> None:
    with httpx.Client(timeout=15) as client:
        apply_arcane(client, auth)
    verify_arcane(auth)
