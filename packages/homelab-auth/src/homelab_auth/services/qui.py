import contextlib
import sqlite3
from typing import TYPE_CHECKING

import httpx

from homelab_auth.common import ensure_state_dir, wait_for_http, wait_for_sqlite_table
from homelab_auth.compose import compose_exec, compose_up
from homelab_auth.config import QUI_URL, ROOT

if TYPE_CHECKING:
    from homelab_auth.models import HomelabAuth


def apply_qui(auth: HomelabAuth) -> None:
    print("Applying Qui credentials")
    qui_config = ROOT / "qui" / "config"
    db_path = qui_config / "qui.db"
    ensure_state_dir(qui_config)
    compose_up("qui")
    with httpx.Client(timeout=15) as client:
        wait_for_http(client, QUI_URL, {200})
    wait_for_sqlite_table(db_path, "user")

    with sqlite3.connect(db_path) as db:
        row: tuple[str] | None = db.execute("select username from user where id = 1").fetchone()
        if row is not None and row[0] != auth.username:
            db.execute(
                "update user set username = ?, updated_at = current_timestamp where id = 1",
                (auth.username,),
            )

    if row is None:
        compose_exec(
            "qui",
            [
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
        )
        return

    compose_exec(
        "qui",
        [
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
    )


def verify_qui(auth: HomelabAuth) -> None:
    print("Verifying Qui username")
    with sqlite3.connect(ROOT / "qui" / "config" / "qui.db") as db:
        row: tuple[str] | None = db.execute("select username from user where id = 1").fetchone()
    if not row or row[0] != auth.username:
        raise RuntimeError("Qui username did not update")


def check_qui(auth: HomelabAuth) -> bool:
    with (
        contextlib.suppress(httpx.HTTPError, OSError),
        httpx.Client(timeout=httpx.Timeout(5.0, connect=0.5)) as client,
    ):
        res = client.post(
            f"{QUI_URL}/api/auth/login",
            json={"username": auth.username, "password": auth.password},
        )
        return res.status_code == 200
    return False


def apply_and_verify_qui(auth: HomelabAuth) -> None:
    apply_qui(auth)
    verify_qui(auth)
