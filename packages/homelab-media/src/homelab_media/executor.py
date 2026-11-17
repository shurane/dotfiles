"""Safe POSIX hardlink execution engine with conflict and traversal guards."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homelab_media.models import ActionType, MediaKind, PathTraversalSecurityError, SyncAction
from homelab_media.parser import assert_safe_target

if TYPE_CHECKING:
    from homelab_media.config import MediaConfig


@dataclass(slots=True)
class ExecutionSummary:
    """Result of executing a batch of SyncActions."""

    linked_count: int = 0
    already_synced_count: int = 0
    errors: list[str] = field(default_factory=list)
    linked_actions: list[SyncAction] = field(default_factory=list)


def execute_sync(
    actions: list[SyncAction],
    config: MediaConfig,
    *,
    dry_run: bool = False,
) -> ExecutionSummary:
    """Execute hardlinks for approved SYNC actions with safety and inode verification."""
    summary = ExecutionSummary()

    for action in actions:
        if action.action_type != ActionType.SYNC or action.target_file is None:
            continue

        source = action.source_file
        target = action.target_file
        media_root = config.media_tv_dir if action.kind == MediaKind.TV else config.media_movies_dir

        try:
            assert_safe_target(target, media_root, follow_symlinks=True)
        except PathTraversalSecurityError as exc:
            summary.errors.append(f"{source.name}: {exc}")
            continue

        if source.is_symlink() or not source.is_file():
            summary.errors.append(f"Refusing non-regular or symlink source: {source}")
            continue

        src_ino = source.stat(follow_symlinks=False).st_ino

        if target.exists():
            tgt_ino = target.stat(follow_symlinks=False).st_ino
            if tgt_ino == src_ino:
                summary.already_synced_count += 1
                continue
            summary.errors.append(
                f"Conflict at {target}: already exists with different inode ({tgt_ino} != {src_ino})"
            )
            continue

        if dry_run:
            summary.linked_count += 1
            summary.linked_actions.append(action)
            continue

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(source, target)
            post_ino = target.stat(follow_symlinks=False).st_ino
            if post_ino != src_ino:
                summary.errors.append(f"Inode mismatch after hardlink for {target}")
                continue
        except OSError as exc:
            summary.errors.append(f"Failed to hardlink {source} -> {target}: {exc}")
            continue

        summary.linked_count += 1
        summary.linked_actions.append(action)

    return summary
