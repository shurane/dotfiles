#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "httpx>=0.27.0",
#   "pydantic>=2.7.0",
# ]
# ///
import argparse
import json
import os
import pathlib
import re
import secrets
import sqlite3
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


ROOT = pathlib.Path(__file__).resolve().parents[1]
AUTH_ENV = pathlib.Path(os.environ.get("AUTH_ENV", ROOT / "homelab.env"))
QBITTORRENT_URL = os.environ.get("QBITTORRENT_URL", "http://qbittorrent.m70q.lan").rstrip("/")
ARCANE_URL = os.environ.get("ARCANE_URL", "http://arcane.m70q.lan").rstrip("/")
JELLYFIN_URL = os.environ.get("JELLYFIN_URL", "http://jellyfin.m.lan").rstrip("/")


class HomelabAuth(BaseModel):
    model_config = ConfigDict(extra="ignore")

    username: str = Field(alias="HOMELAB_AUTH_USERNAME", min_length=1)
    password: str = Field(alias="HOMELAB_AUTH_PASSWORD", min_length=8)


class BootstrapOptions(BaseModel):
    skip_backup: bool = False


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


class JellyfinUser(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="Id", min_length=1)
    name: str = Field(alias="Name", min_length=1)


class JellyfinAuthResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user: JellyfinUser = Field(alias="User")
    access_token: str = Field(alias="AccessToken", min_length=1)


JELLYFIN_PERMISSION_VALUES = {
    0: 1,
    1: 1,
    2: 0,
    3: 1,
    4: 1,
    5: 1,
    6: 1,
    7: 1,
    8: 1,
    9: 1,
    10: 1,
    11: 1,
    12: 1,
    13: 1,
    14: 1,
    15: 1,
    16: 1,
    17: 1,
    18: 1,
    19: 1,
    20: 0,
    21: 0,
    22: 0,
    23: 0,
}

JELLYFIN_PREFERENCE_KINDS = range(13)


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


def output(command: list[str], cwd: pathlib.Path | None = None) -> str:
    return subprocess.run(command, cwd=cwd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout


def compose_up(stack: str, service: str) -> None:
    run(["docker", "compose", "up", "-d", service], cwd=ROOT / stack)


def ensure_state_dir(path: pathlib.Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def wait_for_http(client: httpx.Client, url: str, ready_statuses: set[int], timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = client.get(url)
            if response.status_code in ready_statuses:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise RuntimeError(f"timed out waiting for {url}")


def wait_for_sqlite_table(db_path: pathlib.Path, table_name: str, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if db_path.exists():
            try:
                with sqlite3.connect(db_path) as db:
                    row = db.execute(
                        "select name from sqlite_master where type = 'table' and name = ?",
                        (table_name,),
                    ).fetchone()
                if row is not None:
                    return
            except sqlite3.Error:
                pass
        time.sleep(2)
    raise RuntimeError(f"timed out waiting for table {table_name!r} in {db_path}")


def parse_args() -> BootstrapOptions:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Do not back up Jellyfin SQLite files before changing auth state.",
    )
    args = parser.parse_args()
    return BootstrapOptions(skip_backup=args.skip_backup)


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
        logs = output(["docker", "compose", "logs", "--no-color", "qbittorrent"], cwd=ROOT / "qbittorrent")
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
    compose_up("qbittorrent", "qbittorrent")
    wait_for_http(client, QBITTORRENT_URL, {200, 401, 403})

    preferences = {
        "web_ui_username": auth.username,
        "web_ui_password": auth.password,
    }
    response = client.post(
        f"{QBITTORRENT_URL}/api/v2/app/setPreferences",
        data={"json": json.dumps(preferences)},
    )
    if response.status_code in {401, 403}:
        authenticate_qbittorrent(client, auth)
        response = client.post(
            f"{QBITTORRENT_URL}/api/v2/app/setPreferences",
            data={"json": json.dumps(preferences)},
        )
    response.raise_for_status()


def apply_qui(auth: HomelabAuth) -> None:
    print("Applying Qui credentials")
    qui_config = ROOT / "qui" / "config"
    db_path = qui_config / "qui.db"
    ensure_state_dir(qui_config)
    compose_up("qui", "qui")
    wait_for_sqlite_table(db_path, "user")

    with sqlite3.connect(db_path) as db:
        row: tuple[str] | None = db.execute("select username from user where id = 1").fetchone()
        if row is not None and row[0] != auth.username:
            db.execute(
                "update user set username = ?, updated_at = current_timestamp where id = 1",
                (auth.username,),
            )

    if row is None:
        run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "qui",
                "qui",
                "create-user",
                "--config-dir",
                "/config",
                "--data-dir",
                "/config",
                "--username",
                auth.username,
                "--password",
                auth.password,
            ],
            cwd=ROOT / "qui",
        )
        return

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
        f"{ARCANE_URL}/api/auth/login",
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
    response = client.get(f"{ARCANE_URL}/api/auth/me")
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    parsed = ArcaneResponse.model_validate(payload)
    if parsed.data is None:
        return ArcaneUser.model_validate(payload)
    return parsed.data


def arcane_change_password(client: httpx.Client, current_password: str, auth: HomelabAuth) -> None:
    response = client.post(
        f"{ARCANE_URL}/api/auth/password",
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
        f"{ARCANE_URL}/api/users/{user.id}",
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
    ensure_state_dir(ROOT / "arcane" / "backups")
    ensure_state_dir(ROOT / "arcane" / "builds")
    compose_up("arcane", "arcane")
    wait_for_http(client, ARCANE_URL, {200, 404})

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


def jellyfin_auth_headers(token: str | None = None) -> dict[str, str]:
    auth_parts = [
        'MediaBrowser Client="HomelabBootstrap"',
        'Device="HomelabBootstrap"',
        'DeviceId="homelab-bootstrap"',
        'Version="1.0"',
    ]
    if token:
        auth_parts.append(f'Token="{token}"')
    return {"X-Emby-Authorization": ", ".join(auth_parts)}


def jellyfin_login(client: httpx.Client, username: str, password: str) -> JellyfinAuthResponse | None:
    response = client.post(
        f"{JELLYFIN_URL}/Users/AuthenticateByName",
        headers=jellyfin_auth_headers(),
        json={
            "Username": username,
            "Pw": password,
        },
    )
    if response.status_code == 200:
        if not response.content:
            return None
        return JellyfinAuthResponse.model_validate(response.json())
    if response.status_code in {400, 401, 403, 502, 503, 504}:
        return None
    response.raise_for_status()
    return None


def hash_jellyfin_password(password: str) -> str:
    import hashlib

    iterations = 210_000
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, iterations)
    return f"$PBKDF2-SHA512$iterations={iterations}${salt.hex().upper()}${password_hash.hex().upper()}"


def wait_for_jellyfin(timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{JELLYFIN_URL}/System/Info/Public", timeout=5)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise RuntimeError("Jellyfin did not become ready")


def ensure_jellyfin_files(jellyfin_root: pathlib.Path, db_path: pathlib.Path, system_config: pathlib.Path) -> None:
    if db_path.exists() and system_config.exists():
        return

    print("Starting Jellyfin once so it can create its local schema")
    run(["docker", "compose", "up", "-d", "jellyfin"], cwd=jellyfin_root)
    wait_for_jellyfin()

    if not db_path.exists():
        raise RuntimeError(f"missing Jellyfin database after startup: {db_path}")
    if not system_config.exists():
        raise RuntimeError(f"missing Jellyfin system config after startup: {system_config}")


def backup_jellyfin_db(db_path: pathlib.Path) -> pathlib.Path:
    backup_root = (
        ROOT
        / "jellyfin"
        / "backups"
        / f"auth-bootstrap-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
    )
    backup_root.mkdir(parents=True, exist_ok=False)
    for suffix in ("", "-wal", "-shm"):
        source = db_path.with_name(db_path.name + suffix)
        if source.exists():
            run(["cp", "-a", str(source), str(backup_root / source.name)])
    return backup_root


def mark_jellyfin_wizard_complete(system_config: pathlib.Path) -> None:
    tree = ET.parse(system_config)
    root = tree.getroot()
    wizard = root.find("IsStartupWizardCompleted")
    if wizard is None:
        wizard = ET.SubElement(root, "IsStartupWizardCompleted")
    wizard.text = "true"
    tree.write(system_config, encoding="utf-8", xml_declaration=True)


def next_jellyfin_internal_id(db: sqlite3.Connection) -> int:
    row: tuple[int | None] = db.execute("select max(InternalId) from Users").fetchone()
    return (row[0] or 0) + 1


def select_jellyfin_user_id(db: sqlite3.Connection, auth: HomelabAuth) -> str | None:
    normalized_username = auth.username.upper()
    matching = db.execute(
        "select Id from Users where NormalizedUsername = ? or Username = ?",
        (normalized_username, auth.username),
    ).fetchall()
    if len(matching) == 1:
        return matching[0][0]
    if len(matching) > 1:
        raise RuntimeError(f"found multiple Jellyfin users matching {auth.username!r}")

    users = db.execute("select Id from Users").fetchall()
    if len(users) == 0:
        return None
    if len(users) == 1:
        return users[0][0]
    raise RuntimeError(
        f"found {len(users)} Jellyfin users and none match {auth.username!r}; refusing to pick one automatically"
    )


def insert_jellyfin_admin_user(db: sqlite3.Connection, auth: HomelabAuth, password_hash: str) -> str:
    user_id = str(uuid.uuid4()).upper()
    db.execute(
        """
        insert into Users (
            Id,
            AudioLanguagePreference,
            AuthenticationProviderId,
            CastReceiverId,
            DisplayCollectionsView,
            DisplayMissingEpisodes,
            EnableAutoLogin,
            EnableLocalPassword,
            EnableNextEpisodeAutoPlay,
            EnableUserPreferenceAccess,
            HidePlayedInLatest,
            InternalId,
            InvalidLoginAttemptCount,
            LastActivityDate,
            LastLoginDate,
            LoginAttemptsBeforeLockout,
            MaxActiveSessions,
            MaxParentalRatingScore,
            MustUpdatePassword,
            Password,
            PasswordResetProviderId,
            PlayDefaultAudioTrack,
            RememberAudioSelections,
            RememberSubtitleSelections,
            RemoteClientBitrateLimit,
            RowVersion,
            SubtitleLanguagePreference,
            SubtitleMode,
            SyncPlayAccess,
            Username,
            MaxParentalRatingSubScore,
            NormalizedUsername
        )
        values (?, '', ?, null, 0, 0, 0, 0, 1, 1, 1, ?, 0, null, null, null, 0, null, 0, ?, ?, 1, 1, 1, null, 0, '', 0, 0, ?, null, ?)
        """,
        (
            user_id,
            "Jellyfin.Server.Implementations.Users.DefaultAuthenticationProvider",
            next_jellyfin_internal_id(db),
            password_hash,
            "Jellyfin.Server.Implementations.Users.DefaultPasswordResetProvider",
            auth.username,
            auth.username.upper(),
        ),
    )
    return user_id


def upsert_jellyfin_admin_permissions(db: sqlite3.Connection, user_id: str) -> None:
    db.execute("delete from Permissions where UserId = ?", (user_id,))
    db.executemany(
        """
        insert into Permissions (Kind, Permission_Permissions_Guid, RowVersion, UserId, Value)
        values (?, null, 0, ?, ?)
        """,
        [(kind, user_id, value) for kind, value in JELLYFIN_PERMISSION_VALUES.items()],
    )

    db.execute("delete from Preferences where UserId = ?", (user_id,))
    db.executemany(
        """
        insert into Preferences (Kind, Preference_Preferences_Guid, RowVersion, UserId, Value)
        values (?, null, 0, ?, '')
        """,
        [(kind, user_id) for kind in JELLYFIN_PREFERENCE_KINDS],
    )


def write_jellyfin_admin_user(db_path: pathlib.Path, auth: HomelabAuth) -> None:
    password_hash = hash_jellyfin_password(auth.password)
    with sqlite3.connect(db_path) as db:
        user_id = select_jellyfin_user_id(db, auth)
        if user_id is None:
            user_id = insert_jellyfin_admin_user(db, auth, password_hash)
        else:
            db.execute(
                """
                update Users
                set Password = ?,
                    MustUpdatePassword = 0,
                    InvalidLoginAttemptCount = 0,
                    Username = ?,
                    NormalizedUsername = ?
                where Id = ?
                """,
                (password_hash, auth.username, auth.username.upper(), user_id),
            )
        upsert_jellyfin_admin_permissions(db, user_id)


def apply_jellyfin(auth: HomelabAuth, options: BootstrapOptions) -> None:
    print("Applying Jellyfin credentials and first-run config")

    jellyfin_root = ROOT / "jellyfin"
    db_path = jellyfin_root / "config" / "data" / "jellyfin.db"
    system_config = jellyfin_root / "config" / "config" / "system.xml"
    ensure_state_dir(jellyfin_root / "config")
    ensure_state_dir(jellyfin_root / "cache")

    ensure_jellyfin_files(jellyfin_root, db_path, system_config)

    run(["docker", "compose", "stop", "jellyfin"], cwd=jellyfin_root)
    try:
        if options.skip_backup:
            print("Skipping Jellyfin database backup")
        else:
            backup_jellyfin_db(db_path)
        write_jellyfin_admin_user(db_path, auth)
        mark_jellyfin_wizard_complete(system_config)
    finally:
        run(["docker", "compose", "up", "-d", "jellyfin"], cwd=jellyfin_root)


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


def verify_jellyfin(auth: HomelabAuth) -> None:
    print("Verifying Jellyfin login")
    deadline = time.monotonic() + 60
    login: JellyfinAuthResponse | None = None
    with httpx.Client(timeout=15) as client:
        while time.monotonic() < deadline:
            login = jellyfin_login(client, auth.username, auth.password)
            if login is not None:
                break
            time.sleep(2)
    if login is None:
        raise RuntimeError("Jellyfin shared credential login failed")
    if login.user.name != auth.username:
        raise RuntimeError("Jellyfin username did not match")


def main() -> int:
    options = parse_args()

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

    apply_jellyfin(auth, options)
    verify_jellyfin(auth)

    print("Homelab credentials applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
