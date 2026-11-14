import pykakasi
import pytest


@pytest.fixture(scope="session")
def kakasi_converter() -> pykakasi.kakasi:
    """Session-scoped pykakasi converter to eliminate dictionary reloading overhead."""
    return pykakasi.kakasi()
