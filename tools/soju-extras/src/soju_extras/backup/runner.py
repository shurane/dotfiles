"""Coordinate an online SQLite snapshot, compressed files, and verified rsync delivery."""

import os
import shlex
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from whenever import Instant

from soju_extras.backup.models import BackupConfig, FileEntry, Receipt, Remote
from soju_extras.backup.retention import completed, prune_completed, validate_root
from soju_extras.backup.snapshot import (
    MANIFEST,
    RECEIPT,
    backup_database,
    pack_tree,
    sha256,
    verify_snapshot,
)
from soju_extras.export_fs.storage import atomic_write, export_lock, sync_directory


def run(argv: Sequence[str], *, env: dict[str, str] | None = None) -> str:
    return subprocess.run(argv, check=True, text=True, stdout=subprocess.PIPE, env=env).stdout


def flush_weechat(config: BackupConfig) -> None:
    checkpoint = config.weechat
    if checkpoint is None:
        return
    result = subprocess.run(
        ["pgrep", "-u", checkpoint.user, "-x", "weechat"], stdout=subprocess.DEVNULL, check=False
    )
    if result.returncode == 1:
        return  # Saved configuration remains available while the client is stopped.
    if result.returncode != 0:
        raise ValueError("Unable to determine whether WeeChat is running")
    checkpoint.ready_file.unlink(missing_ok=True)
    run(
        [
            "runuser",
            "-u",
            checkpoint.user,
            "--",
            str(checkpoint.command),
            "core",
            "/soju_backup_checkpoint",
        ]
    )
    deadline = time.monotonic() + 60
    while not checkpoint.ready_file.is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError("WeeChat did not flush its settings within 60 seconds")
        time.sleep(0.1)


def copy_sources(config: BackupConfig, stage: Path) -> None:
    for source in config.sources:
        destination = stage / source.destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        exclusions = [f"--exclude={pattern}" for pattern in source.excludes]
        if source.source.is_dir() and not source.source.is_symlink():
            destination.mkdir(exist_ok=True)
            run(
                ["rsync", "-a", *exclusions, "--", str(source.source) + "/", str(destination) + "/"]
            )
        else:
            run(["rsync", "-a", *exclusions, "--", str(source.source), str(destination)])


def remote_environment(remote: Remote) -> dict[str, str]:
    return dict(
        os.environ,
        RSYNC_RSH=shlex.join(
            [
                "ssh",
                "-i",
                str(remote.identity_file),
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                f"UserKnownHostsFile={remote.known_hosts}",
            ]
        ),
    )


def deliver(snapshot: Path, remote: Remote, previous: str | None) -> None:
    env = remote_environment(remote)
    destination = f"{remote.host}:{snapshot.name}/"
    links = [f"--link-dest=/{previous}"] if previous else []
    run(
        ["rsync", "-a", "--no-owner", "--no-group", *links, "--", str(snapshot) + "/", destination],
        env=env,
    )
    differences = run(["rsync", "-rlcni", "--", str(snapshot) + "/", destination], env=env)
    if differences.strip():
        raise ValueError("Remote backup failed checksum verification")


def complete(snapshot: Path, remote: Remote | None) -> None:
    receipt = Receipt(snapshot=snapshot.name, manifest_sha256=sha256(snapshot / MANIFEST))
    if remote:
        # Publish remote eligibility only after all payload checksums have matched.
        with TemporaryDirectory(prefix=".receipt-", dir=snapshot.parent) as temporary:
            marker = Path(temporary) / RECEIPT
            atomic_write(marker, receipt.model_dump_json() + "\n")
            destination = f"{remote.host}:{snapshot.name}/"
            env = remote_environment(remote)
            run(
                ["rsync", "-a", "--no-owner", "--no-group", "--", str(marker), destination], env=env
            )
            if run(["rsync", "-rcni", "--", str(marker), destination], env=env).strip():
                raise ValueError("Remote completion receipt did not verify")
    atomic_write(snapshot / RECEIPT, receipt.model_dump_json() + "\n")


def create_backup(config: BackupConfig) -> Path:
    config.root.mkdir(mode=0o700, parents=True, exist_ok=True)
    validate_root(config.root)
    with export_lock(config.root / ".backup.lock", label="backup"):
        names = completed(config.root)
        previous = names[-1] if names else None
        name = Instant.now().format_iso(unit="second").replace(":", "")
        destination = config.root / name
        if destination.exists():
            raise FileExistsError(destination)
        flush_weechat(config)
        with TemporaryDirectory(prefix=".pending-", dir=config.root) as temporary:
            raw = Path(temporary) / "raw"
            raw.mkdir(mode=0o700)
            # Same lock as the exporter: exported checkpoints cannot get ahead of DB.
            with export_lock(config.export_directory / ".export.lock"):
                copy_sources(config, raw)
                backup_database(config.database, raw / config.database_destination)
            packed = Path(temporary) / "snapshot"
            manifest = pack_tree(raw, packed, name)
            verify_snapshot(packed)
            # Reuse unchanged compressed files, even when gzip headers/mtimes changed.
            if previous:
                prior = config.root / previous
                for entry in manifest.entries:
                    if not isinstance(entry, FileEntry):
                        continue
                    path, old = packed / entry.stored, prior / entry.stored
                    if (
                        old.is_file()
                        and not old.is_symlink()
                        and entry.stored_sha256 == sha256(old)
                    ):
                        path.unlink()
                        os.link(old, path)
                        sync_directory(path.parent)
            os.rename(packed, destination)
            sync_directory(config.root)
        if config.remote:
            deliver(destination, config.remote, previous)
        complete(destination, config.remote)
        if config.last_file:
            atomic_write(config.last_file, name + "\n")
        if config.success_file:
            atomic_write(config.success_file, name + "\n")
        # Local pruning follows verified remote completion; a failed transfer cannot prune.
        prune_completed(config.root, names + [name], config.retention, apply=True)
        return destination
