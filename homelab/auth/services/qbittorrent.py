import json
from typing import TYPE_CHECKING

import httpx

from common import ensure_state_dir, wait_for_http
from compose import compose_up
from config import QBITTORRENT_URL, ROOT
from http_models import QbittorrentPreferences, QbittorrentSetPreferencesRequest

if TYPE_CHECKING:
    from models import HomelabAuth


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


def authenticate_qbittorrent(client: httpx.Client, auth: HomelabAuth) -> None:
    if not qbittorrent_login(client, auth.username, auth.password):
        raise RuntimeError(f"qBittorrent rejected centralized credentials for user {auth.username!r}")


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


def check_qbittorrent(auth: HomelabAuth) -> bool:
    with httpx.Client(timeout=httpx.Timeout(5.0, connect=0.5)) as client:
        try:
            return qbittorrent_login(client, auth.username, auth.password)
        except Exception:
            return False


def apply_and_verify_qbittorrent(auth: HomelabAuth) -> None:
    with httpx.Client(timeout=15) as client:
        apply_qbittorrent(client, auth)
        verify_qbittorrent(client, auth)
