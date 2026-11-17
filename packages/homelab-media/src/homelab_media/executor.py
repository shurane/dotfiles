"""Safe POSIX hardlink execution engine with conflict and traversal guards."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homelab_media.models import ActionType, PathTraversalSecurityError, SyncAction
from homelab_media.parser import assert_safe_target

if TYPE_CHECKING:
    from pathlib import Path

    from homelab_media.config import MediaConfig


@dataclass(slots=True)
class ExecutionSummary:
    """Result of executing a batch of SyncActions."""

    linked_count: int = 0
    already_synced_count: int = 0
    errors: list[str] = field(default_factory=list)
    linked_actions: list[SyncAction] = field(default_factory=list)


def _record_existing_target(target: Path, tgt_ino: int, src_ino: int, summary: ExecutionSummary) -> None:
    """Record whether an already-existing target file is an inode match or a conflict."""
    if tgt_ino == src_ino:
        summary.already_synced_count += 1
    else:
        summary.errors.append(
            f"Conflict at {target}: already exists with different inode ({tgt_ino} != {src_ino})"
        )


def _create_hardlink(source: Path, target: Path, src_ino: int, summary: ExecutionSummary) -> bool:
    """Create the hardlink on disk and verify its inode. Returns True if newly linked."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(source, target)
        if target.lstat().st_ino != src_ino:
            summary.errors.append(f"Inode mismatch after hardlink for {target}")
            return False
    except FileExistsError:
        _record_existing_target(target, target.lstat().st_ino, src_ino, summary)
        return False
    except OSError as exc:
        summary.errors.append(f"Failed to hardlink {source} -> {target}: {exc}")
        return False
    return True


def _execute_one(
    action: SyncAction,
    config: MediaConfig,
    summary: ExecutionSummary,
    *,
    dry_run: bool,
) -> None:
    """Validate and hardlink a single SYNC action, updating `summary` in place."""
    if action.action_type != ActionType.SYNC or action.target_file is None:
        return

    source = action.source_file
    target = action.target_file
    try:
        assert_safe_target(target, config.media_root(action.kind), follow_symlinks=True)
    except PathTraversalSecurityError as exc:
        summary.errors.append(f"{source.name}: {exc}")
        return

    try:
        src_st = source.lstat()
    except OSError:
        src_st = None
    if src_st is None or not stat.S_ISREG(src_st.st_mode):
        summary.errors.append(f"Refusing non-regular or symlink source: {source}")
        return
    src_ino = src_st.st_ino

    try:
        tgt_ino = target.lstat().st_ino
    except FileNotFoundError:
        tgt_ino = None
    except OSError as exc:
        summary.errors.append(f"Failed to stat target {target}: {exc}")
        return

    if tgt_ino is not None:
        _record_existing_target(target, tgt_ino, src_ino, summary)
        return

    if not dry_run and not _create_hardlink(source, target, src_ino, summary):
        return

    summary.linked_count += 1
    summary.linked_actions.append(action)


def execute_sync(
    actions: list[SyncAction],
    config: MediaConfig,
    *,
    dry_run: bool = False,
) -> ExecutionSummary:
    """Execute hardlinks for approved SYNC actions with safety and inode verification."""
    summary = ExecutionSummary()
    for action in actions:
        _execute_one(action, config, summary, dry_run=dry_run)
    return summary
