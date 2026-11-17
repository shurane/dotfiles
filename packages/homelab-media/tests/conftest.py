"""Shared pytest fixtures and test helpers for homelab-media."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homelab_media.config import MediaConfig

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def make_test_config(tmp_path: Path) -> MediaConfig:
    """Create a MediaConfig rooted under `tmp_path` with `torrents/{tv,movies}` and `media/{tv,movies}`."""
    for subdir in ("torrents/tv", "torrents/movies", "media/tv", "media/movies"):
        (tmp_path / subdir).mkdir(parents=True, exist_ok=True)
    return MediaConfig(torrents_dir=tmp_path / "torrents", media_dir=tmp_path / "media")


def make_sparse_video(path: Path, size: int = 100 * 1024 * 1024) -> Path:
    """Create a sparse regular file of the given size without allocating disk blocks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.truncate(size)
    return path


@pytest.fixture
def media_config(tmp_path: Path) -> MediaConfig:
    """Fixture returning a temporary MediaConfig with initialized directory structure."""
    return make_test_config(tmp_path)


@pytest.fixture
def make_video() -> Callable[..., Path]:
    """Fixture returning the `make_sparse_video(path, size=...)` helper."""
    return make_sparse_video
