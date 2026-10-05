"""Tests for BitwardenClient API and safety guards."""

from unittest.mock import patch

import pytest

from bitwarden_extras.client import (
    BitwardenClient,
    VaultLockedError,
    VaultUnauthenticatedError,
)


class TestClientStatusAndAuth:
    @patch.object(BitwardenClient, "http_request")
    def test_active_serve_url_unlocked(self, mock_http):
        mock_http.return_value = {
            "success": True,
            "data": {"template": {"status": "unlocked"}},
        }
        client = BitwardenClient()
        url = client.get_active_serve_url("http://127.0.0.1:8087")
        assert url == "http://127.0.0.1:8087"

    @patch.object(BitwardenClient, "http_request")
    def test_active_serve_url_locked(self, mock_http):
        mock_http.return_value = {
            "success": True,
            "data": {"template": {"status": "locked"}},
        }
        client = BitwardenClient()
        with pytest.raises(VaultLockedError):
            client.get_active_serve_url("http://127.0.0.1:8087")

    @patch.object(BitwardenClient, "http_request")
    def test_active_serve_url_unauthenticated(self, mock_http):
        mock_http.return_value = {
            "success": True,
            "data": {"template": {"status": "unauthenticated"}},
        }
        client = BitwardenClient()
        with pytest.raises(VaultUnauthenticatedError):
            client.get_active_serve_url("http://127.0.0.1:8087")


class TestClientSyncAndFetch:
    @patch.object(BitwardenClient, "http_request")
    @patch.object(BitwardenClient, "get_active_serve_url", return_value="http://127.0.0.1:8087")
    def test_sync_success(self, mock_get_url, mock_http):
        mock_http.return_value = {"success": True}
        client = BitwardenClient()
        assert client.sync() is True

    def test_find_blank_note_items(self):
        client = BitwardenClient()
        items = [
            {"id": "1", "name": "Item 1", "notes": "\x10"},
            {"id": "2", "name": "Item 2", "notes": "Valid documentation note"},
            {"id": "3", "name": "Item 3", "notes": ""},
            {"id": "4", "name": "Item 4", "notes": None},
        ]
        blank = client.find_blank_note_items(items)
        assert len(blank) == 2
        assert {b["id"] for b in blank} == {"1", "3"}

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/bw")
    def test_run_bw_cli_raises_on_master_password_prompt(self, mock_which, mock_run):
        from unittest.mock import MagicMock

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="? Master password: [input is hidden]\n",
            stderr="",
        )
        client = BitwardenClient()
        with pytest.raises(VaultLockedError, match="Vault is locked"):
            client.run_bw_cli(["list", "items"])

    @patch.object(BitwardenClient, "run_bw_cli")
    def test_fetch_via_cli_raises_on_invalid_json(self, mock_run_bw):
        from unittest.mock import MagicMock

        from bitwarden_extras.client import BitwardenError

        mock_run_bw.return_value = MagicMock(returncode=0, stdout="not-json", stderr="")
        client = BitwardenClient()
        with pytest.raises(BitwardenError, match="Failed to parse"):
            client.fetch_via_cli()

