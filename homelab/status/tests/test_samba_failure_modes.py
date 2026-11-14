"""Unit tests simulating failure modes and edge cases for Samba SMB/CIFS status checks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from models import StatusContext, TargetConnection
from services.samba import (
    SambaRawData,
    _parse_samba_version,
    _parse_smb_locks,
    _parse_smb_sessions,
    evaluate_samba_report,
    run_samba_deep_check,
)


def _make_mock_raw(
    container_found: bool = True,
    container_status: str = "running",
    container_health: str = "healthy",
    network_mode: str = "host",
    port_445_open: bool = True,
    port_445_latency_ms: float = 0.45,
    shares: list[str] | None = None,
    accounts: list[str] | None = None,
    auth_check_code: int = 0,
    auth_check_out: str = "Domain=[WORKGROUP] OS=[Windows 6.1] Server=[Samba 4.23.8]",
    empty_pw_check_code: int = 1,
    empty_pw_check_out: str = "session setup failed: NT_STATUS_LOGON_FAILURE",
    mount_check_code: int = 0,
    mount_options: str = "/dev/sda1 on /shares/mango type ext4 (rw,relatime)",
    smbstatus_sessions_code: int = 0,
    smbstatus_sessions_out: str = (
        "Samba version 4.23.8\n"
        "PID     Username     Group        Machine               Protocol Version  Encryption  Signing\n"
        "----------------------------------------------------------------------------------------------------\n"
        "12345   ehtesh       users        192.168.1.150 (ipv4)  SMB3_11           -           partial\n"
    ),
    smbstatus_locks_code: int = 0,
    smbstatus_locks_out: str = "No locked files\n",
    version: str | None = "v4.23.8",
) -> SambaRawData:
    raw = SambaRawData()
    raw.container_found = container_found
    raw.container_status = container_status
    raw.container_health = container_health
    raw.network_mode = network_mode
    raw.port_445_open = port_445_open
    raw.port_445_latency_ms = port_445_latency_ms
    raw.shares = shares if shares is not None else ["downloads", "mango", "media", "retroarch"]
    raw.accounts = accounts if accounts is not None else ["ehtesh"]
    raw.auth_check_code = auth_check_code
    raw.auth_check_out = auth_check_out
    raw.empty_pw_check_code = empty_pw_check_code
    raw.empty_pw_check_out = empty_pw_check_out
    raw.mount_check_code = mount_check_code
    raw.mount_options = mount_options
    raw.smbstatus_sessions_code = smbstatus_sessions_code
    raw.smbstatus_sessions_out = smbstatus_sessions_out
    raw.smbstatus_locks_code = smbstatus_locks_code
    raw.smbstatus_locks_out = smbstatus_locks_out
    raw.version = version
    return raw


def test_samba_happy_path() -> None:
    conn = TargetConnection("m70q.lan", "192.168.1.10", "lan", "Direct LAN")
    raw = _make_mock_raw()
    report = evaluate_samba_report(raw, conn)

    assert report.all_passed is True
    assert report.version == "v4.23.8"
    assert len(report.shares) == 4
    assert len(report.accounts) == 1
    assert len(report.active_clients) == 1
    assert report.active_clients[0].username == "ehtesh"
    assert report.active_clients[0].protocol == "SMB3_11"
    assert report.drive_mount_mode == "rw"

    check_names = [c.name for c in report.checks]
    assert "Inspection Route" in check_names
    assert "Container Lifecycle" in check_names
    assert "TCP Port 445 Reachability" in check_names
    assert "SMB Authentication" in check_names
    assert "Empty Password Rejection" in check_names
    assert "Storage Mount State" in check_names
    assert "Active Client Sessions" in check_names
    assert "File Locks Table" in check_names


def test_samba_failure_container_stopped() -> None:
    raw = _make_mock_raw(container_found=False, container_status="exited")
    report = evaluate_samba_report(raw)

    assert report.all_passed is False
    c_check = next(c for c in report.checks if c.name == "Container Lifecycle")
    assert c_check.passed is False
    assert "not found" in c_check.details


def test_samba_failure_port_445_closed() -> None:
    raw = _make_mock_raw(port_445_open=False)
    report = evaluate_samba_report(raw)

    assert report.all_passed is False
    p_check = next(c for c in report.checks if c.name == "TCP Port 445 Reachability")
    assert p_check.passed is False
    assert "unreachable" in p_check.details


def test_samba_failure_auth_failed() -> None:
    raw = _make_mock_raw(
        auth_check_code=1,
        auth_check_out="session setup failed: NT_STATUS_LOGON_FAILURE",
    )
    report = evaluate_samba_report(raw)

    assert report.all_passed is False
    auth_check = next(c for c in report.checks if c.name == "SMB Authentication")
    assert auth_check.passed is False
    assert "NT_STATUS_LOGON_FAILURE" in auth_check.details


def test_samba_security_empty_password_rejection() -> None:
    # When empty password fails with NT_STATUS_LOGON_FAILURE, security check passes!
    raw = _make_mock_raw(
        empty_pw_check_code=1,
        empty_pw_check_out="session setup failed: NT_STATUS_LOGON_FAILURE",
    )
    report = evaluate_samba_report(raw)
    sec_check = next(c for c in report.checks if c.name == "Empty Password Rejection")
    assert sec_check.passed is True
    assert "NT_STATUS_LOGON_FAILURE enforced" in sec_check.details


def test_samba_security_empty_password_vulnerability() -> None:
    # If empty password unexpectedly succeeded, that is a security vulnerability!
    raw = _make_mock_raw(
        empty_pw_check_code=0,
        empty_pw_check_out="Domain=[WORKGROUP] OS=[Windows 6.1] Server=[Samba 4.23.8]",
    )
    report = evaluate_samba_report(raw)
    sec_check = next(c for c in report.checks if c.name == "Empty Password Rejection")
    assert sec_check.passed is False
    assert "SECURITY RISK" in sec_check.details
    assert report.all_passed is False


def test_samba_failure_drive_read_only() -> None:
    raw = _make_mock_raw(
        mount_options="/dev/sda1 on /shares/mango type ext4 (ro,relatime,errors=remount-ro)",
    )
    report = evaluate_samba_report(raw)

    assert report.all_passed is False
    mount_check = next(c for c in report.checks if c.name == "Storage Mount State")
    assert mount_check.passed is False
    assert "read-only (ro)" in mount_check.details
    assert report.drive_mount_mode == "ro"


def test_samba_smbstatus_parser() -> None:
    sample_b = (
        "Samba version 4.23.8\n"
        "PID     Username     Group        Machine               Protocol Version  Encryption   Signing\n"
        "----------------------------------------------------------------------------------------------------\n"
        "101     ehtesh       users        192.168.1.50 (ipv4)   SMB3_11           AES-128-GCM  AES-128-GMAC\n"
        "102     guest        nobody       100.120.146.5 (ipv4)  SMB3_00           -            partial\n"
    )
    sessions = _parse_smb_sessions(sample_b)
    assert len(sessions) == 2
    assert sessions[0].pid == "101"
    assert sessions[0].username == "ehtesh"
    assert sessions[0].protocol == "SMB3_11"
    assert sessions[0].encryption == "AES-128-GCM"
    assert sessions[1].username == "guest"
    assert sessions[1].protocol == "SMB3_00"

    version = _parse_samba_version(sample_b)
    assert version == "v4.23.8"


def test_samba_smbstatus_locks_parser() -> None:
    sample_l = (
        "Locked files:\n"
        "Pid          Uid        DenyMode   Access      R/W        Oplock      SharePath       Name       Time\n"
        "----------------------------------------------------------------------------------------------------\n"
        "101          1000       DENY_NONE  0x120089    RDONLY     LEASE(R)    /shares/media   movie.mkv  Fri\n"
    )
    locks = _parse_smb_locks(sample_l)
    assert len(locks) == 1
    assert locks[0].pid == "101"
    assert locks[0].filename == "movie.mkv"
    assert locks[0].rw == "RDONLY"

    empty_locks = _parse_smb_locks("No locked files\n")
    assert empty_locks == []


@pytest.mark.anyio
async def test_run_samba_deep_check_with_mock_context() -> None:
    ctx = MagicMock(spec=StatusContext)
    ctx.no_docker = False
    ctx.username = "username"
    ctx.password = "secret"
    ctx.lan_host = "localhost"
    ctx.http_timeout = 2.0
    ctx.connection = TargetConnection("localhost", "127.0.0.1", "local", "On-Device")

    c_mock = MagicMock()
    c_mock.attrs = {
        "State": {"Status": "running", "Health": {"Status": "healthy"}},
        "Config": {"Env": ["SAMBA_VOLUME_CONFIG_mango=...", "ACCOUNT_username=..."]},
        "HostConfig": {"NetworkMode": "host"},
    }

    async def _get_c(name: str, full: bool = False) -> MagicMock:
        return c_mock

    async def _exec_c(name: str, cmd: str | list[str]) -> tuple[int, str]:
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "-Uehtesh%secret" in cmd_str:
            return 0, "Domain=[WORKGROUP]"
        if "-Uehtesh%" in cmd_str:
            return 1, "session setup failed: NT_STATUS_LOGON_FAILURE"
        if "mount | grep" in cmd_str:
            return 0, "/dev/sda1 on /shares/mango type ext4 (rw,relatime)"
        if "smbstatus -b" in cmd_str:
            return 0, "Samba version 4.23.8\n---"
        if "smbstatus -L" in cmd_str:
            return 0, "No locked files\n"
        return 0, ""

    ctx.get_container = _get_c
    ctx.exec_container = _exec_c
    ctx.get_container_version = AsyncMock(return_value="v4.23.8")

    report = await run_samba_deep_check(ctx)
    assert report.connection == ctx.connection
    assert "mango" in report.shares
    assert "ehtesh" in report.accounts
