"""Tests for data models, sanitization, and privacy invariants."""

from typing import Any

import pytest

from bitwarden_extras.models import (
    LoginData,
    LoginUri,
    clean_str,
    extract_domains,
    match_type,
    process_vault,
)


class TestStringCleaning:
    def test_clean_str_none(self):
        assert clean_str(None) == ""

    def test_clean_str_normal(self):
        assert clean_str("Hello World") == "Hello World"

    def test_clean_str_control_characters(self):
        assert clean_str("\x10") == ""
        assert clean_str(" \x10 \x00 \x1f ") == ""
        assert clean_str("Hello \x10 World") == "Hello \x10 World"

    def test_clean_str_unicode_whitespace(self):
        assert clean_str("\xa0\x10\u2009") == ""
        assert clean_str("\xa0 Secret Note \xa0") == "Secret Note"

    def test_clean_str_preserves_multiline(self):
        text = "Line 1\nLine 2\nLine 3"
        assert clean_str(text) == text


class TestDomainExtraction:
    def test_standard_urls(self):
        login = LoginData(
            uris=[
                LoginUri(uri="https://github.com/login"),
                LoginUri(uri="http://api.github.com/v1"),
            ]
        )
        assert extract_domains(login) == ["github.com", "api.github.com"]

    def test_schemeless_and_ports(self):
        login = LoginData(
            uris=[
                LoginUri(uri="sub.example.com:8443/test"),
                LoginUri(uri="http://localhost:8087"),
            ]
        )
        assert extract_domains(login) == ["sub.example.com", "localhost"]

    def test_deduplication(self):
        login = LoginData(
            uris=[
                LoginUri(uri="https://google.com/search"),
                LoginUri(uri="https://google.com/mail"),
            ]
        )
        assert extract_domains(login) == ["google.com"]

    def test_empty_and_malformed(self):
        login = LoginData(
            uris=[
                LoginUri(uri=""),
                LoginUri(uri="   "),
                LoginUri(uri="not a valid uri :::: 99999"),
            ]
        )
        assert isinstance(extract_domains(login), list)


class TestPrivacyAndSanitization:
    @pytest.fixture
    def mock_vault_data(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        folders = [
            {"id": "f1", "name": "Work"},
            {"id": "f2", "name": "Personal"},
        ]
        items = [
            {
                "id": "item-1",
                "name": "My Work Email",
                "folderId": "f1",
                "type": 1,
                "login": {
                    "username": "user@work.com",
                    "password": "SUPER_SECRET_PASSWORD_123",
                    "totp": "TOTP_SEED_SECRET_456",
                    "uris": [{"uri": "https://work.com"}],
                },
                "notes": "Sensitive freeform note",
                "favorite": True,
            },
            {
                "id": "item-2",
                "name": None,
                "folderId": None,
                "type": 2,
                "login": None,
                "notes": "\x10",
                "favorite": False,
            },
        ]
        return folders, items

    def test_zero_secret_leakage(self, mock_vault_data):
        folders, items = mock_vault_data
        metadata = process_vault(folders, items, include_notes=False)

        for item in metadata.items:
            item_dump = item.model_dump_json()
            assert "SUPER_SECRET_PASSWORD_123" not in item_dump
            assert "TOTP_SEED_SECRET_456" not in item_dump
            assert item.notes is None

    def test_nullable_tracking_unfiled_and_unnamed(self, mock_vault_data):
        folders, items = mock_vault_data
        metadata = process_vault(folders, items, include_notes=True)

        item1 = metadata.items[0]
        assert item1.name == "My Work Email"
        assert item1.folder == "Work"

        item2 = metadata.items[1]
        assert item2.name is None
        assert item2.folder is None

    def test_match_type_helper(self):
        assert match_type(1) == "Login"
        assert match_type(2) == "Secure Note"
        assert match_type(3) == "Card"
        assert match_type(4) == "Identity"
        assert match_type(99) == "Other"
