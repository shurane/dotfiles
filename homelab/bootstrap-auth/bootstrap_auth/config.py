import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUTH_ENV = Path(os.environ.get("AUTH_ENV", ROOT / "homelab.env"))

QBITTORRENT_URL = os.environ.get("QBITTORRENT_URL", "http://qbittorrent:8080").rstrip("/")
QUI_URL = os.environ.get("QUI_URL", "http://qui:7476").rstrip("/")
ARCANE_URL = os.environ.get("ARCANE_URL", "http://arcane:3552").rstrip("/")
JELLYFIN_URL = os.environ.get("JELLYFIN_URL", "http://jellyfin:8096").rstrip("/")
