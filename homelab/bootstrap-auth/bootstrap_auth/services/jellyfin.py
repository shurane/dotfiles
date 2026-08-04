import hashlib
import secrets
import shutil
import sqlite3
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

from ..common import ensure_state_dir
from ..compose import compose_stop, compose_up
from ..config import JELLYFIN_URL, ROOT
from ..http_models import JellyfinAuthRequest, JellyfinAuthResponse
from ..models import BootstrapOptions, HomelabAuth


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
    payload = JellyfinAuthRequest(username=username, password=password)
    response = client.post(
        f"{JELLYFIN_URL}/Users/AuthenticateByName",
        headers=jellyfin_auth_headers(),
        json=payload.model_dump(by_alias=True),
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
    iterations = 210_000
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, iterations)
    return f"$PBKDF2-SHA512$iterations={iterations}${salt.hex().upper()}${password_hash.hex().upper()}"


def wait_for_jellyfin(timeout_seconds: int = 90) -> None:
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


def ensure_jellyfin_files(jellyfin_root: Path, db_path: Path, system_config: Path) -> None:
    if db_path.exists() and system_config.exists():
        return

    print("Starting Jellyfin once so it can create its local schema")
    compose_up("jellyfin")
    wait_for_jellyfin()

    if not db_path.exists():
        raise RuntimeError(f"missing Jellyfin database after startup: {db_path}")
    if not system_config.exists():
        raise RuntimeError(f"missing Jellyfin system config after startup: {system_config}")


def backup_jellyfin_db(db_path: Path) -> Path:
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
            shutil.copy2(source, backup_root / source.name)
    return backup_root


def mark_jellyfin_wizard_complete(system_config: Path) -> None:
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


def write_jellyfin_admin_user(db_path: Path, auth: HomelabAuth) -> None:
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

    compose_stop("jellyfin")
    try:
        if options.skip_backup:
            print("Skipping Jellyfin database backup")
        else:
            backup_jellyfin_db(db_path)
        write_jellyfin_admin_user(db_path, auth)
        mark_jellyfin_wizard_complete(system_config)
    finally:
        compose_up("jellyfin")


def verify_jellyfin(auth: HomelabAuth) -> None:
    print("Verifying Jellyfin login")
    deadline = time.monotonic() + 90
    login: JellyfinAuthResponse | None = None
    with httpx.Client(timeout=15) as client:
        while time.monotonic() < deadline:
            try:
                login = jellyfin_login(client, auth.username, auth.password)
            except httpx.HTTPError:
                login = None
            if login is not None:
                break
            time.sleep(2)
    if login is None:
        raise RuntimeError("Jellyfin shared credential login failed")
    if login.user.name != auth.username:
        raise RuntimeError("Jellyfin username did not match")


def apply_and_verify_jellyfin(auth: HomelabAuth, options: BootstrapOptions) -> None:
    apply_jellyfin(auth, options)
    verify_jellyfin(auth)
