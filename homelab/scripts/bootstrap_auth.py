#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "httpx>=0.27.0",
#   "pydantic>=2.7.0",
# ]
# ///
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import subprocess
import sys
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


ROOT = pathlib.Path(__file__).resolve().parents[1]
AUTH_ENV = pathlib.Path(os.environ.get("AUTH_ENV", ROOT / "homelab-auth.env"))


class HomelabAuth(BaseModel):
    model_config = ConfigDict(extra="ignore")

    username: str = Field(alias="HOMELAB_AUTH_USERNAME", min_length=1)
    password: str = Field(alias="HOMELAB_AUTH_PASSWORD", min_length=8)


class QbittorrentPreferences(BaseModel):
    model_config = ConfigDict(extra="ignore")

    web_ui_username: str


class ArcaneUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    username: str = Field(min_length=1)


class ArcaneResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    data: ArcaneUser | None = None


def load_env(path: pathlib.Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def run(command: list[str], cwd: pathlib.Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def apply_qbittorrent(client: httpx.Client, auth: HomelabAuth) -> None:
    print("Applying qBittorrent credentials")
    preferences = {
        "web_ui_username": auth.username,
        "web_ui_password": auth.password,
    }
    response = client.post(
        "http://qbittorrent.m70q.lan/api/v2/app/setPreferences",
        data={"json": json.dumps(preferences)},
    )
    response.raise_for_status()


def apply_qui(auth: HomelabAuth) -> None:
    print("Applying Qui credentials")
    qui_config = ROOT / "qui" / "config"
    db_path = qui_config / "qui.db"

    with sqlite3.connect(db_path) as db:
        row: tuple[str] | None = db.execute("select username from user where id = 1").fetchone()
        if row and row[0] != auth.username:
            db.execute(
                "update user set username = ?, updated_at = current_timestamp where id = 1",
                (auth.username,),
            )

    run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "qui",
            "qui",
            "change-password",
            "--config-dir",
            "/config",
            "--data-dir",
            "/config",
            "--username",
            auth.username,
            "--new-password",
            auth.password,
        ],
        cwd=ROOT / "qui",
    )


def arcane_login(client: httpx.Client, username: str, password: str) -> bool:
    response = client.post(
        "http://arcane.m70q.lan/api/auth/login",
        json={"username": username, "password": password},
    )
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
    response = client.get("http://arcane.m70q.lan/api/auth/me")
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    parsed = ArcaneResponse.model_validate(payload)
    if parsed.data is None:
        return ArcaneUser.model_validate(payload)
    return parsed.data


def arcane_change_password(client: httpx.Client, current_password: str, auth: HomelabAuth) -> None:
    response = client.post(
        "http://arcane.m70q.lan/api/auth/password",
        json={
            "currentPassword": current_password,
            "newPassword": auth.password,
        },
    )
    if response.status_code == 400 and "same" in response.text.lower():
        return
    response.raise_for_status()


def arcane_update_via_api(client: httpx.Client, user: ArcaneUser, auth: HomelabAuth) -> None:
    response = client.put(
        f"http://arcane.m70q.lan/api/users/{user.id}",
        json={
            "username": auth.username,
            "password": auth.password,
            "displayName": auth.username,
            "email": "admin@localhost",
        },
    )
    response.raise_for_status()


def apply_arcane(client: httpx.Client, auth: HomelabAuth) -> None:
    print("Applying Arcane credentials")

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


def verify_qbittorrent(client: httpx.Client, auth: HomelabAuth) -> None:
    print("Verifying qBittorrent username")
    response = client.get("http://qbittorrent.m70q.lan/api/v2/app/preferences")
    response.raise_for_status()
    prefs = QbittorrentPreferences.model_validate(response.json())
    if prefs.web_ui_username != auth.username:
        raise RuntimeError("qBittorrent username did not update")


def verify_qui(auth: HomelabAuth) -> None:
    print("Verifying Qui username")
    with sqlite3.connect(ROOT / "qui" / "config" / "qui.db") as db:
        row: tuple[str] | None = db.execute("select username from user where id = 1").fetchone()
    if not row or row[0] != auth.username:
        raise RuntimeError("Qui username did not update")


def verify_arcane(auth: HomelabAuth) -> None:
    print("Verifying Arcane login")
    with httpx.Client(timeout=15) as client:
        if not arcane_login(client, auth.username, auth.password):
            raise RuntimeError("Arcane shared credential login failed")
        user = arcane_current_user(client)
    if user.username != auth.username:
        raise RuntimeError("Arcane username did not update")


def main() -> int:
    if not AUTH_ENV.exists():
        print(f"missing auth env: {AUTH_ENV}", file=sys.stderr)
        return 1

    try:
        auth = HomelabAuth.model_validate(load_env(AUTH_ENV))
    except ValidationError as error:
        print(error, file=sys.stderr)
        return 1

    with httpx.Client(timeout=15) as client:
        apply_qbittorrent(client, auth)
        verify_qbittorrent(client, auth)

    apply_qui(auth)
    verify_qui(auth)

    with httpx.Client(timeout=15) as client:
        apply_arcane(client, auth)
    verify_arcane(auth)

    print("Homelab credentials applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
