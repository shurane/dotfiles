"""Tests for Typer CLI commands and safety guards."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from bitwarden_extras.cli import app

runner = CliRunner()


class TestCliExportAndQuery:
    @patch("bitwarden_extras.cli.client.fetch_live_data")
    def test_export_yaml(self, mock_fetch, tmp_path: Path):
        mock_fetch.return_value = (
            [{"id": "f1", "name": "Work"}],
            [
                {
                    "id": "i1",
                    "name": "Test Login",
                    "type": 1,
                    "folderId": "f1",
                    "login": {"username": "user"},
                }
            ],
            "Connected to bw serve",
        )
        out_file = tmp_path / "metadata.yaml"
        result = runner.invoke(app, ["export", "--format", "yaml", "--output", str(out_file)])
        assert result.exit_code == 0
        assert out_file.exists()
        content = out_file.read_text()
        assert "Test Login" in content
        assert "Work" in content

    @patch("bitwarden_extras.cli.client.fetch_live_data")
    def test_query_sql(self, mock_fetch):
        mock_fetch.return_value = (
            [{"id": "f1", "name": "Work"}],
            [{"id": "i1", "name": "Test Item", "type": 1, "folderId": "f1"}],
            "Connected to bw serve",
        )
        result = runner.invoke(app, ["query", "SELECT name FROM items"])
        assert result.exit_code == 0
        assert "Test Item" in result.stdout

    @patch("bitwarden_extras.cli.client.fetch_live_data")
    def test_handle_vault_locked_error(self, mock_fetch):
        from bitwarden_extras.client import VaultLockedError

        mock_fetch.side_effect = VaultLockedError("Vault is locked.")
        result = runner.invoke(app, ["query", "SELECT 1"])
        assert result.exit_code == 1
        assert "Vault is locked" in result.stderr or "Vault is locked" in result.stdout


class TestCleanBlankNotesSafety:
    @patch("bitwarden_extras.cli.client.http_request")
    @patch("bitwarden_extras.cli.client.get_active_serve_url", return_value="http://127.0.0.1:8087")
    @patch("bitwarden_extras.cli.client.sync")
    def test_clean_blank_notes_aborts_on_failed_get(self, mock_sync, mock_get_url, mock_http):
        # 1. list items -> item with blank note
        # 2. GET item -> returns None (simulating network failure)
        mock_http.side_effect = [
            {
                "success": True,
                "data": {"data": [{"id": "item-1", "name": "Item 1", "notes": "\x10"}]},
            },
            None,  # GET failed!
        ]

        result = runner.invoke(app, ["clean-blank-notes", "--yes"])
        assert result.exit_code == 0

        # Verify destructive PUT was never called
        put_calls = [c for c in mock_http.call_args_list if c.kwargs.get("method") == "PUT"]
        assert len(put_calls) == 0, "Destructive PUT must never be called when GET returns None"
