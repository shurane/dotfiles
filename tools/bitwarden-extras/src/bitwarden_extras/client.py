"""Bitwarden REST API and CLI client."""

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

from bitwarden_extras.models import clean_str

DEFAULT_SERVE_PORT = 8087
DEFAULT_SERVE_URLS: tuple[str, ...] = (
    f"http://[::1]:{DEFAULT_SERVE_PORT}",
    f"http://127.0.0.1:{DEFAULT_SERVE_PORT}",
    f"http://localhost:{DEFAULT_SERVE_PORT}",
)


class BitwardenError(Exception):
    """Base exception for Bitwarden operations."""


class VaultLockedError(BitwardenError):
    """Raised when the vault is locked."""


class VaultUnauthenticatedError(BitwardenError):
    """Raised when the user is not authenticated."""


class ServeConnectionError(BitwardenError):
    """Raised when connection to bw serve fails."""


class CliNotFoundError(BitwardenError):
    """Raised when the bw executable cannot be found in PATH."""


class BitwardenClient:
    """Client for interacting with Bitwarden via bw serve REST API and CLI fallback."""

    def __init__(self, serve_port: int = DEFAULT_SERVE_PORT) -> None:
        self.serve_port = serve_port

    def http_request(
        self,
        url: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: float = 5.0,
    ) -> dict[str, Any] | None:
        """Issue an HTTP request to the local bw serve daemon."""
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError, OSError:
            return None

    def run_bw_cli(self, args: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
        """Execute a Bitwarden CLI command using the local binary."""
        bw_bin = shutil.which("bw")
        if not bw_bin:
            raise CliNotFoundError("Bitwarden CLI ('bw') executable not found in PATH.")

        res = subprocess.run(
            [bw_bin, *args],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )

        combined_output = f"{res.stdout}\n{res.stderr}"
        if "Master password" in combined_output or "Vault is locked" in combined_output:
            raise VaultLockedError(
                "Vault is locked and BW_SESSION is not set.\n"
                "Please run: export BW_SESSION=$(bw unlock --raw)"
            )

        if res.returncode != 0:
            err = res.stderr.strip()
            if "BW_SESSION" not in os.environ:
                raise VaultLockedError(
                    "Vault is locked and BW_SESSION is not set.\n"
                    "Please run: export BW_SESSION=$(bw unlock --raw)"
                )
            if check:
                raise BitwardenError(f"Bitwarden CLI error: {err}")

        return res

    def get_active_serve_url(self, server_url: str | None = None) -> str | None:
        """Find an active, unlocked bw serve URL or raise appropriate status exceptions."""
        urls_to_try = [server_url] if server_url else DEFAULT_SERVE_URLS
        locked_url: str | None = None

        for base_url in urls_to_try:
            if not base_url:
                continue
            res = self.http_request(f"{base_url}/status", timeout=1.0)
            if res is not None:
                status = res.get("data", {}).get("template", {}).get("status")
                if status == "locked":
                    locked_url = base_url
                    continue
                if status == "unauthenticated":
                    raise VaultUnauthenticatedError(
                        f"Vault is not logged in on 'bw serve' ({base_url}).\nPlease run: bw login"
                    )
                return base_url

        if locked_url:
            raise VaultLockedError(
                f"Vault is locked on 'bw serve' ({locked_url}).\n"
                "Please run: export BW_SESSION=$(bw unlock --raw)"
            )

        if server_url:
            raise ServeConnectionError(
                f"Could not connect to custom Bitwarden server at {server_url}"
            )

        return None

    def get_last_sync(self, base_url: str) -> datetime | None:
        """Return the UTC timestamp of the last vault sync."""
        res = self.http_request(f"{base_url}/status", timeout=1.0)
        if res:
            raw_sync = res.get("data", {}).get("template", {}).get("lastSync")
            if raw_sync:
                try:
                    return datetime.fromisoformat(raw_sync)
                except ValueError:
                    pass
        return None

    def sync(self, server_url: str | None = None) -> bool:
        """Trigger a vault sync with Bitwarden cloud servers."""
        base_url = self.get_active_serve_url(server_url)
        if base_url:
            res = self.http_request(f"{base_url}/sync", method="POST", timeout=10.0)
            return bool(res and res.get("success"))

        # CLI Fallback
        res_cli = self.run_bw_cli(["sync"])
        return res_cli.returncode == 0

    def fetch_via_serve(
        self, server_url: str | None = None, timeout: float = 10.0
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
        """Fetch folders and items via bw serve REST endpoints."""
        base_url = self.get_active_serve_url(server_url)
        if not base_url:
            return None

        f_json = self.http_request(f"{base_url}/list/object/folders", timeout=timeout)
        i_json = self.http_request(f"{base_url}/list/object/items", timeout=timeout)

        if (
            not f_json
            or not f_json.get("success", True)
            or not i_json
            or not i_json.get("success", True)
        ):
            return None

        folders: list[dict[str, Any]] = f_json.get("data", {}).get("data", [])
        items: list[dict[str, Any]] = i_json.get("data", {}).get("data", [])
        return folders, items

    def fetch_via_cli(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
        """Fetch folders and items via the bw list CLI commands."""
        folders_res = self.run_bw_cli(["list", "folders"])
        items_res = self.run_bw_cli(["list", "items"])

        if folders_res.returncode != 0 or items_res.returncode != 0:
            return None

        try:
            folders: list[dict[str, Any]] = json.loads(folders_res.stdout)
            items: list[dict[str, Any]] = json.loads(items_res.stdout)
        except json.JSONDecodeError as err:
            raise BitwardenError("Failed to parse Bitwarden CLI output as JSON.") from err
        return folders, items

    def fetch_live_data(
        self,
        server_url: str | None = None,
        sync: bool = False,
        no_sync: bool = False,
        auto_sync_seconds: int = 300,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        """
        Fetch live vault data with smart auto-sync.
        Returns (folders, items, sync_info_str).
        """
        active_url = self.get_active_serve_url(server_url)

        if active_url:
            should_sync = sync
            if not no_sync and not should_sync:
                last_sync_dt = self.get_last_sync(active_url)
                if last_sync_dt:
                    age_seconds = (datetime.now(UTC) - last_sync_dt).total_seconds()
                    if age_seconds > auto_sync_seconds:
                        should_sync = True

            if should_sync and not no_sync:
                self.sync(server_url=active_url)

            serve_data = self.fetch_via_serve(server_url=server_url)
            if serve_data is not None:
                last_sync_dt = self.get_last_sync(active_url)
                sync_info = ""
                if last_sync_dt:
                    age = int((datetime.now(UTC) - last_sync_dt).total_seconds())
                    sync_info = (
                        f" (synced {age}s ago)" if age < 60 else f" (synced {age // 60}m ago)"
                    )
                return serve_data[0], serve_data[1], f"Connected to bw serve{sync_info}"

        if server_url:
            raise ServeConnectionError(f"Could not connect to {server_url}")

        if sync and not no_sync:
            self.sync()

        cli_data = self.fetch_via_cli()
        if cli_data is None:
            raise BitwardenError("Failed to retrieve data from Bitwarden CLI.")

        return cli_data[0], cli_data[1], "Retrieved via Bitwarden CLI"

    def find_blank_note_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Identify items that have empty, whitespace, or phantom control-character notes."""
        blank_items: list[dict[str, Any]] = []
        for it in items:
            raw_notes = it.get("notes")
            if raw_notes is not None and not clean_str(raw_notes):
                blank_items.append(it)
        return blank_items
