import secrets
import shutil
import sqlite3
import time
from pathlib import Path

from werkzeug.security import generate_password_hash

from ..common import ensure_state_dir, wait_for_sqlite_table
from ..compose import compose_stop, compose_up
from ..config import ROOT
from ..models import BootstrapOptions, HomelabAuth


def backup_cwa_db(db_path: Path) -> Path:
    backup_root = (
        ROOT
        / "calibre-web-automated"
        / "backups"
        / f"auth-bootstrap-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
    )
    backup_root.mkdir(parents=True, exist_ok=False)
    for suffix in ("", "-wal", "-shm"):
        source = db_path.with_name(db_path.name + suffix)
        if source.exists():
            shutil.copy2(source, backup_root / source.name)
    return backup_root


def write_cwa_admin_user(db_path: Path, auth: HomelabAuth) -> None:
    password_hash = generate_password_hash(auth.password, method="scrypt")
    with sqlite3.connect(db_path) as db:
        conflict = db.execute(
            "select id, name, email from user where id != 1 and (name = ? or email = ?)",
            (auth.username, "admin@localhost"),
        ).fetchall()
        if conflict:
            raise RuntimeError(
                "found another Calibre-Web-Automated user with the target username or email; refusing to overwrite"
            )

        row = db.execute("select id from user where id = 1").fetchone()
        if row is None:
            raise RuntimeError("Calibre-Web-Automated admin user id 1 was not found")

        db.execute(
            """
            update user
            set name = ?,
                email = ?,
                password = ?
            where id = 1
            """,
            (auth.username, "admin@localhost", password_hash),
        )


def apply_cwa(auth: HomelabAuth, options: BootstrapOptions) -> None:
    print("Applying Calibre-Web-Automated credentials")

    cwa_root = ROOT / "calibre-web-automated"
    config_root = cwa_root / "config"
    db_path = config_root / "app.db"
    ensure_state_dir(config_root)
    ensure_state_dir(cwa_root / "ingest")
    ensure_state_dir(cwa_root / "library")
    compose_up("calibre-web-automated")
    wait_for_sqlite_table(db_path, "user")

    compose_stop("calibre-web-automated")
    try:
        if options.skip_backup:
            print("Skipping Calibre-Web-Automated database backup")
        else:
            backup_cwa_db(db_path)
        write_cwa_admin_user(db_path, auth)
    finally:
        compose_up("calibre-web-automated")


def verify_cwa(auth: HomelabAuth) -> None:
    print("Verifying Calibre-Web-Automated username")
    with sqlite3.connect(ROOT / "calibre-web-automated" / "config" / "app.db") as db:
        row: tuple[str] | None = db.execute("select name from user where id = 1").fetchone()
    if not row or row[0] != auth.username:
        raise RuntimeError("Calibre-Web-Automated username did not update")


def apply_and_verify_cwa(auth: HomelabAuth, options: BootstrapOptions) -> None:
    apply_cwa(auth, options)
    verify_cwa(auth)
