import json
from pathlib import Path
from typing import TYPE_CHECKING

from homelab_scripts import download_anpanman
from homelab_scripts.download_anpanman import load_anpanman_metadata

if TYPE_CHECKING:
    import pytest


def test_maruko_metadata_json_structure() -> None:
    json_path = Path(__file__).resolve().parent.parent / "src" / "homelab_scripts" / "maruko_metadata.json"
    assert json_path.exists(), "maruko_metadata.json must exist in homelab/scripts"

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(data) == 142, "Season 1 must contain exactly 142 episodes"

    for i in range(1, 143):
        key = str(i)
        assert key in data, f"Episode {key} missing from maruko_metadata.json"
        entry = data[key]
        assert entry["episode"] == i
        assert entry["season"] == 1
        assert entry["title_ja"].strip(), f"Episode {key} missing Japanese title"
        assert entry["title_ro"].strip(), f"Episode {key} missing Romaji title"


def test_anpanman_metadata_json_structure() -> None:
    json_path = Path(__file__).resolve().parent.parent / "src" / "homelab_scripts" / "anpanman_metadata.json"
    assert json_path.exists(), "anpanman_metadata.json must exist in homelab/scripts"

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(data) >= 1000, "Catalog must contain over 1,000 indexed episode segments"

    assert "0001a" in data
    assert "0002a" in data
    assert "0002b" in data

    for key, entry in data.items():
        assert isinstance(entry["episode"], int)
        assert isinstance(entry["segment"], str)
        assert entry["title_ja"].strip(), f"Entry {key} missing Japanese title"
        assert entry["title_ro"].strip(), f"Entry {key} missing Romaji title"


def test_load_anpanman_metadata_live() -> None:
    meta = load_anpanman_metadata()
    assert isinstance(meta, dict)
    assert len(meta) >= 1000
    assert "0001a" in meta
    assert meta["0001a"]["title_ro"] == "Anpanman Tanjou"


def test_load_anpanman_metadata_corrupt_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    corrupt_file = tmp_path / "anpanman_metadata.json"
    corrupt_file.write_text("CORRUPTED NOT JSON {{{", encoding="utf-8")

    monkeypatch.setattr(download_anpanman, "__file__", str(tmp_path / "homelab_scripts.download_anpanman.py"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "fake_home")

    result = load_anpanman_metadata()
    assert result == {}
