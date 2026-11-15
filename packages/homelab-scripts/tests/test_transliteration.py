from typing import TYPE_CHECKING

from homelab_scripts.build_anpanman_metadata import to_romaji as anpanman_to_romaji
from homelab_scripts.build_maruko_metadata import clean_en_title
from homelab_scripts.build_maruko_metadata import to_romaji as maruko_to_romaji

if TYPE_CHECKING:
    import pykakasi


def test_maruko_to_romaji_maki_and_brackets(kakasi_converter: pykakasi.kakasi) -> None:
    # Bracket stripping and "no Maki" suffix
    res = maruko_to_romaji(kakasi_converter, "「まる子の赤い靴」の巻")
    assert res.endswith("no Maki")
    assert "「" not in res
    assert "」" not in res


def test_maruko_to_romaji_particle_casing(kakasi_converter: pykakasi.kakasi) -> None:
    # Common grammatical particles must remain lowercased
    res = maruko_to_romaji(kakasi_converter, "お母さんの日")
    assert " no " in res


def test_anpanman_to_romaji_particle_and_names(kakasi_converter: pykakasi.kakasi) -> None:
    # Character name separation and "to" particle
    res = anpanman_to_romaji(kakasi_converter, "アンパンマンとばいきんまん")
    assert res == "Anpanman to Baikinman"


def test_anpanman_to_romaji_sanitization(kakasi_converter: pykakasi.kakasi) -> None:
    # Unsafe filesystem characters must be removed or replaced
    res = anpanman_to_romaji(kakasi_converter, "アンパンマン/テスト:クエスチョン?*")
    assert "/" not in res
    assert ":" not in res
    assert "?" not in res
    assert "*" not in res
    assert "-" in res


def test_clean_en_title_parenthetical_and_quotes() -> None:
    # Wikipedia parentheticals
    assert clean_en_title('"English Title"(Japanese:日本語)') == "English Title"
    # Bare quotes
    assert clean_en_title('"The Great Adventure"') == "The Great Adventure"
    # Plain title
    assert clean_en_title("Plain Episode Title") == "Plain Episode Title"
