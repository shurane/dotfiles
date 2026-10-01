"""Data models for sojugrep using Pydantic v2."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SearchQuery(BaseModel):
    """Parameters for an FTS5 search query."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    pattern: str = Field(min_length=1, description="Search query string or FTS5 phrase")
    target: str | None = Field(default=None, description="Optional channel or nickname")
    network: str | None = Field(default=None, description="Optional IRC network filter")
    db_path: Path = Field(
        default=Path("/var/lib/soju/main.db"),
        description="Path to Soju SQLite database",
    )
    limit: int = Field(default=100, ge=1, le=10000, description="Max results")


class SearchResult(BaseModel):
    """A single matched IRC message from SQLite FTS5."""

    model_config = ConfigDict(frozen=True)

    message_id: int
    timestamp_str: str
    network: str
    target: str
    sender_nick: str
    text: str
