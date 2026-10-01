"""Keep recent daily, weekly and monthly recovery points; ignore unowned directories."""

import shutil
from datetime import date
from pathlib import Path

from soju_extras.backup.models import Receipt, Retention, snapshot_name
from soju_extras.backup.snapshot import MANIFEST, RECEIPT, sha256
from soju_extras.export_fs.storage import export_lock, sync_directory
from soju_extras.time import parse_timestamp


def snapshot_date(name: str, timezone: str) -> date:
    snapshot_name(name)
    stamp = f"{name[:13]}:{name[13:15]}:{name[15:17]}Z"
    return date.fromisoformat(str(parse_timestamp(stamp).to_tz(timezone).date()))


def retained(names: list[str], policy: Retention) -> set[str]:
    """Keep the newest snapshot in each of N distinct calendar buckets.

    Buckets overlap, so 7/4/6 retains at most 17 snapshots. Sparse schedules retain
    older available recovery points rather than deleting everything after downtime.
    """
    keep: set[str] = set()
    seen: list[set[tuple[int, ...]]] = [set(), set(), set()]
    counts = (policy.daily, policy.weekly, policy.monthly)
    for name in sorted(names, reverse=True):
        day = snapshot_date(name, policy.timezone)
        iso_year, iso_week, _ = day.isocalendar()
        buckets = ((day.year, day.month, day.day), (iso_year, iso_week), (day.year, day.month))
        for bucket, visited, count in zip(buckets, seen, counts, strict=True):
            if bucket not in visited and len(visited) < count:
                visited.add(bucket)
                keep.add(name)
    return keep


def validate_root(root: Path) -> None:
    if not root.is_dir():
        raise FileNotFoundError(root)
    if root.is_symlink() or root.resolve() != root.absolute():
        raise ValueError("Backup root must not contain symlinks")


def completed(root: Path) -> list[str]:
    validate_root(root)
    names: list[str] = []
    for child in root.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        try:
            snapshot_name(child.name)
        except ValueError:
            continue
        marker = child / RECEIPT
        if not marker.exists():
            continue  # Legacy snapshots and interrupted uploads are never pruned.
        if marker.is_symlink() or (child / MANIFEST).is_symlink():
            raise ValueError("Snapshot metadata must not be symlinks")
        receipt = Receipt.model_validate_json(marker.read_bytes())
        if receipt.snapshot != child.name or receipt.manifest_sha256 != sha256(child / MANIFEST):
            raise ValueError(f"Invalid completion receipt: {child.name}")
        names.append(child.name)
    return sorted(names)


def prune_completed(root: Path, names: list[str], policy: Retention, *, apply: bool) -> list[str]:
    """Caller holds the backup lock; names have already passed receipt validation."""
    keep = retained(names, policy)
    obsolete = [name for name in names if name not in keep]
    if apply:
        for name in obsolete:
            shutil.rmtree(root / name)
        sync_directory(root)
    return obsolete


def prune(root: Path, policy: Retention, *, apply: bool = False) -> list[str]:
    validate_root(root)
    with export_lock(root / ".backup.lock", label="backup"):
        return prune_completed(root, completed(root), policy, apply=apply)
