import json
import re
import time

import httpx

from ..common import ensure_state_dir, wait_for_http
from ..compose import compose_logs, compose_up
from ..config import QBITTORRENT_URL, ROOT
from ..http_models import QbittorrentPreferences, QbittorrentSetPreferencesRequest
from ..models import HomelabAuth


def qbittorrent_login(client: httpx.Client, username: str, password: str) -> bool:
    response = client.post(
        f"{QBITTORRENT_URL}/api/v2/auth/login",
        data={"username": username, "password": password},
    )
    if response.status_code == 204:
        return True
    if response.status_code != 200:
        return False
    return response.text.strip() == "Ok."


def qbittorrent_temporary_password(timeout_seconds: int = 60) -> str | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        logs = compose_logs("qbittorrent")
        match = re.search(r"temporary password[^:]*:\s*(\S+)", logs, flags=re.IGNORECASE)
        if match is not None:
            return match.group(1)
        time.sleep(2)
    return None


def authenticate_qbittorrent(client: httpx.Client, auth: HomelabAuth) -> None:
    if qbittorrent_login(client, auth.username, auth.password):
        return

    temporary_password = qbittorrent_temporary_password()
    if temporary_password and qbittorrent_login(client, "admin", temporary_password):
        return

    raise RuntimeError("qBittorrent rejected shared credentials and no working temporary admin password was found")


def apply_qbittorrent(client: httpx.Client, auth: HomelabAuth) -> None:
    print("Applying qBittorrent credentials")
    ensure_state_dir(ROOT / "qbittorrent" / "config")
    compose_up("qbittorrent")
    wait_for_http(client, f"{QBITTORRENT_URL}/api/v2/app/version", {200, 403})

    preferences = QbittorrentSetPreferencesRequest(
        web_ui_username=auth.username,
        web_ui_password=auth.password,
    )
    response = client.post(
        f"{QBITTORRENT_URL}/api/v2/app/setPreferences",
        data={"json": json.dumps(preferences.model_dump())},
    )
    if response.status_code in {401, 403}:
        authenticate_qbittorrent(client, auth)
        response = client.post(
            f"{QBITTORRENT_URL}/api/v2/app/setPreferences",
            data={"json": json.dumps(preferences.model_dump())},
        )
    response.raise_for_status()


def verify_qbittorrent(client: httpx.Client, auth: HomelabAuth) -> None:
    print("Verifying qBittorrent username")
    response = client.get(f"{QBITTORRENT_URL}/api/v2/app/preferences")
    if response.status_code in {401, 403}:
        authenticate_qbittorrent(client, auth)
        response = client.get(f"{QBITTORRENT_URL}/api/v2/app/preferences")
    response.raise_for_status()
    prefs = QbittorrentPreferences.model_validate(response.json())
    if prefs.web_ui_username != auth.username:
        raise RuntimeError("qBittorrent username did not update")


def apply_and_verify_qbittorrent(auth: HomelabAuth) -> None:
    with httpx.Client(timeout=15) as client:
        apply_qbittorrent(client, auth)
        verify_qbittorrent(client, auth)
