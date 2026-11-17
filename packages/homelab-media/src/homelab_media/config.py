"""Configuration loading and host environment detection for homelab-media."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values
from homelab_core.env import find_homelab_env
from homelab_core.network import get_ssh_user
from homelab_core.services import Service, resolve_service_url
from pydantic import BaseModel, ConfigDict, Field

from homelab_media.models import MediaKind


class MediaConfig(BaseModel):
    """Configuration for homelab-media scanner, clients, and remote dispatch."""

    model_config = ConfigDict(extra="ignore")

    torrents_dir: Path = Field(default=Path("/mnt/mango/torrents"))
    media_dir: Path = Field(default=Path("/mnt/mango/media"))
    hostname_base: str = Field(default="009973.xyz")
    homelab_host: str = Field(default="m70q.lan")
    ssh_user: str = Field(default="ehtesh")
    qbittorrent_url: str = Field(default="https://qbittorrent.009973.xyz")
    qbittorrent_user: str = Field(default="ehtesh")
    qbittorrent_pass: str = Field(default="")
    jellyfin_url: str = Field(default="https://jellyfin.009973.xyz")
    jellyfin_api_key: str = Field(default="")
    tmdb_api_key: str = Field(default="")
    tmdb_read_token: str = Field(default="")

    @property
    def torrents_tv_dir(self) -> Path:
        """Return the TV torrents directory."""
        return self.torrents_dir / "tv"

    @property
    def torrents_movies_dir(self) -> Path:
        """Return the movies torrents directory."""
        return self.torrents_dir / "movies"

    @property
    def media_tv_dir(self) -> Path:
        """Return the TV media library directory."""
        return self.media_dir / "tv"

    @property
    def media_movies_dir(self) -> Path:
        """Return the movies media library directory."""
        return self.media_dir / "movies"

    def torrents_root(self, kind: MediaKind) -> Path:
        """Return the torrents root directory for the given MediaKind."""
        return self.torrents_tv_dir if kind == MediaKind.TV else self.torrents_movies_dir

    def media_root(self, kind: MediaKind) -> Path:
        """Return the media library root directory for the given MediaKind."""
        return self.media_tv_dir if kind == MediaKind.TV else self.media_movies_dir


def load_config(env_path: Path | None = None) -> MediaConfig:
    """Load MediaConfig from homelab .env file and environment variables."""
    resolved_env = find_homelab_env(env_path)
    raw: dict[str, str] = {}
    if resolved_env is not None:
        raw = {k: v for k, v in dotenv_values(resolved_env).items() if v is not None}

    def _get(key: str, default: str = "") -> str:
        return os.environ.get(key) or raw.get(key) or default

    hostname_base = _get("HOSTNAME_BASE", "009973.xyz")
    homelab_host = _get("HOMELAB_HOSTNAME", "m70q.lan")
    ssh_user = get_ssh_user(_get("HOMELAB_SSH_USER") or None, env_path=resolved_env)

    qb_url = resolve_service_url(
        Service.QBITTORRENT,
        base_domain=hostname_base,
        host=homelab_host,
        env_override=_get("QBITTORRENT_URL") or None,
        env_path=resolved_env,
    )
    jf_url = resolve_service_url(
        Service.JELLYFIN,
        base_domain=hostname_base,
        host=homelab_host,
        env_override=_get("JELLYFIN_URL") or None,
        env_path=resolved_env,
    )

    return MediaConfig(
        torrents_dir=Path(_get("MEDIA_TORRENTS_DIR", "/mnt/mango/torrents")),
        media_dir=Path(_get("MEDIA_LIBRARY_DIR", "/mnt/mango/media")),
        hostname_base=hostname_base,
        homelab_host=homelab_host,
        ssh_user=ssh_user,
        qbittorrent_url=qb_url,
        qbittorrent_user=_get("QBITTORRENT_USER") or _get("HOMELAB_USERNAME", "ehtesh"),
        qbittorrent_pass=_get("QBITTORRENT_PASS") or _get("HOMELAB_PASSWORD", ""),
        jellyfin_url=jf_url,
        jellyfin_api_key=_get("JELLYFIN_API_KEY", ""),
        tmdb_api_key=_get("TMDB_API_KEY", ""),
        tmdb_read_token=_get("TMDB_READ_TOKEN", ""),
    )


def is_local_target(config: MediaConfig) -> bool:
    """Return True if the media/torrents filesystem is mounted locally."""
    return config.torrents_dir.exists() and config.media_dir.exists()
