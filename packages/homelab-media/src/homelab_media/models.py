"""Pydantic schemas and domain models for homelab-media."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class PathTraversalSecurityError(ValueError):
    """Raised when a target path attempts to escape the configured media library root."""


class MediaKind(StrEnum):
    """Supported media library categories."""

    TV = "tv"
    MOVIE = "movies"


class ActionType(StrEnum):
    """Classification of a media file or torrent during gap scanning."""

    SYNC = "SYNC"
    ALREADY_SYNCED = "ALREADY_SYNCED"
    FLAGGED_FOR_REVIEW = "FLAGGED_FOR_REVIEW"
    SKIP_EXTRA = "SKIP_EXTRA"
    SKIP_IN_PROGRESS = "SKIP_IN_PROGRESS"
    IGNORED = "IGNORED"
    CONFLICT = "CONFLICT"


class TorrentItem(BaseModel):
    """Represents a torrent download state from qBittorrent."""

    model_config = ConfigDict(extra="ignore")

    hash: str = Field(alias="hash", default="")
    name: str
    category: str = ""
    progress: float = 0.0
    state: str = ""
    dlspeed: int = 0
    eta: int = 0
    size: int = 0
    content_path: Path = Path()


class SyncAction(BaseModel):
    """Represents a single file action (sync, skip, ignore, conflict)."""

    torrent_name: str
    source_file: Path
    target_file: Path | None = None
    kind: MediaKind
    action_type: ActionType
    reason: str
    file_size: int = 0
    confidence: float = 1.0
    season: int | None = None
    episode: int | str | None = None
    tracked_by_qbittorrent: bool = True


class CandidateOption(BaseModel):
    """Selectable resolution option for a flagged review item."""

    option_id: str
    target_path: Path
    description: str


class ReviewItem(BaseModel):
    """Ambiguous or structurally mismatched item requiring agy or human review."""

    id: str
    torrent_name: str
    kind: MediaKind
    issue: str
    confidence: float
    message: str
    candidates: list[CandidateOption] = Field(default_factory=list)
    source_files: list[Path] = Field(default_factory=list)


class GapReport(BaseModel):
    """Full structured report produced by the media gap scanner."""

    in_progress: list[TorrentItem] = Field(default_factory=list)
    ready_to_sync: list[SyncAction] = Field(default_factory=list)
    flagged_for_review: list[ReviewItem] = Field(default_factory=list)
    skipped_extras: list[SyncAction] = Field(default_factory=list)
    ignored_items: list[SyncAction] = Field(default_factory=list)
    conflicts: list[SyncAction] = Field(default_factory=list)
    already_synced_count: int = 0
    qbittorrent_online: bool = True
    scan_duration_ms: float = 0.0
    generated_at: str = ""
