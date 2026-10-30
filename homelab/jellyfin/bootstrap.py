#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "lxml>=5.3.0",
#     "rich>=13.0.0",
# ]
# ///
"""Jellyfin Hardware & Settings Bootstrap Manager.

Detects host GPU capabilities and safely manages:
1. homelab/.env: Sets dynamic RENDER_GID and VIDEO_GID for docker-compose.
2. Jellyfin XML configuration: encoding.xml, system.xml, and library options.xml
   using proper DOM/XML tree parsing instead of fragile regex replacements.
"""

from __future__ import annotations

import argparse
import difflib
import os
from pathlib import Path
import sys
import tempfile
from typing import NamedTuple
import unittest
from unittest.mock import patch

from lxml import etree
from rich.console import Console
from rich.table import Table

console = Console()

SYS_VENDOR_PATH = Path("/sys/class/drm/renderD128/device/vendor")
RENDER_DEV_PATH = Path("/dev/dri/renderD128")
CARD_DEV_PATH = Path("/dev/dri/card0")


class GpuInfo(NamedTuple):
    vendor_id: str
    accel_type: str
    render_gid: str
    video_gid: str


def detect_gpu(
    vendor_path: Path = SYS_VENDOR_PATH,
    render_path: Path = RENDER_DEV_PATH,
    card_path: Path = CARD_DEV_PATH,
) -> GpuInfo:
    """Detect host GPU vendor and determine target hardware acceleration."""
    vendor = "unknown"
    if vendor_path.exists():
        try:
            vendor = vendor_path.read_text(encoding="utf-8").strip().lower()
        except OSError:
            pass

    match vendor:
        case "0x8086":
            accel = "qsv"
        case "0x10de":
            accel = "nvenc"
        case "0x1002":
            accel = "vaapi"
        case _:
            accel = "none" if not render_path.exists() else "vaapi"

    render_gid = "none"
    if render_path.exists():
        try:
            render_gid = str(render_path.stat().st_gid)
        except OSError:
            pass

    video_gid = "none"
    if card_path.exists():
        try:
            video_gid = str(card_path.stat().st_gid)
        except OSError:
            pass

    return GpuInfo(
        vendor_id=vendor,
        accel_type=accel,
        render_gid=render_gid,
        video_gid=video_gid,
    )


def locate_config_dir(custom_path: Path | None = None) -> Path:
    """Find the Jellyfin configuration directory."""
    if custom_path:
        return custom_path

    candidates = [
        Path(__file__).resolve().parent / "config",
        Path("/home/ehtesh/dotfiles/homelab/jellyfin/config"),
        Path("/config"),
    ]
    for candidate in candidates:
        if candidate.exists() and (candidate / "config").exists():
            return candidate

    return Path(__file__).resolve().parent / "config"


def locate_env_file(custom_path: Path | None = None) -> Path | None:
    """Find the homelab .env file."""
    if custom_path:
        return custom_path

    candidates = [
        Path(__file__).resolve().parent.parent / ".env",
        Path("/home/ehtesh/dotfiles/homelab/.env"),
        Path.home() / "dotfiles/homelab/.env",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    return Path(__file__).resolve().parent.parent / ".env"


def format_path(path: Path | None) -> str:
    """Format path relative to user's home directory (e.g. ~/dotfiles/...) if applicable."""
    if path is None:
        return "<none>"
    try:
        resolved = path.resolve()
        home = Path.home().resolve()
        if resolved == home:
            return "~"
        if resolved.is_relative_to(home):
            return f"~/{resolved.relative_to(home)}"
    except (ValueError, RuntimeError):
        pass
    return str(path)


def set_or_create_child(parent: etree._Element, tag: str, value: str) -> tuple[bool, str, str]:
    """Ensure an XML child element exists with the specified text value.

    Returns (changed, old_value, new_value).
    """
    elem = parent.find(tag)
    if elem is None:
        elem = etree.SubElement(parent, tag)
        elem.text = value
        return True, "<missing>", value

    old_val = (elem.text or "").strip()
    if old_val != value:
        elem.text = value
        return True, old_val, value

    return False, old_val, value


def serialize_xml(tree: etree._ElementTree) -> str:
    """Serialize an XML ElementTree to an indent-formatted UTF-8 string."""
    return etree.tostring(
        tree,
        encoding="utf-8",
        xml_declaration=True,
        pretty_print=True,
    ).decode("utf-8")


def generate_diff(original_text: str, new_text: str, filename: str) -> list[str]:
    """Generate unified diff lines between original and modified text."""
    orig_lines = original_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    return list(
        difflib.unified_diff(
            orig_lines,
            new_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )
    )


def print_colorized_diff(diff_lines: list[str]) -> None:
    """Print unified diff lines with syntax-highlighted red/green coloring."""
    for line in diff_lines:
        line_str = line.rstrip("\n")
        if line_str.startswith("---") or line_str.startswith("+++"):
            console.print(f"[bold white]{line_str}[/]")
        elif line_str.startswith("@@"):
            console.print(f"[bold cyan]{line_str}[/]")
        elif line_str.startswith("-"):
            console.print(f"[bold red]{line_str}[/]")
        elif line_str.startswith("+"):
            console.print(f"[bold green]{line_str}[/]")
        else:
            console.print(f"[dim]{line_str}[/]")


def write_file_atomic(content: str, target_path: Path) -> None:
    """Write text content atomically using a temporary file."""
    temp_path = target_path.with_name(f"{target_path.name}.tmp")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(target_path)


class FileChangeResult(NamedTuple):
    path: Path
    has_changes: bool
    diff_lines: list[str]
    error: str | None = None


def update_env_content(content: str, updates: dict[str, str]) -> str:
    """Update or append KEY=VALUE pairs in .env content while preserving comments and format."""
    lines = content.splitlines(keepends=True)
    keys_remaining = dict(updates)
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        matched_key = None
        for k in list(keys_remaining.keys()):
            if stripped.startswith(f"{k}=") or stripped == k:
                matched_key = k
                break
        if matched_key:
            new_val = keys_remaining.pop(matched_key)
            new_lines.append(f"{matched_key}={new_val}\n")
        else:
            new_lines.append(line)

    if keys_remaining:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        for k, v in keys_remaining.items():
            new_lines.append(f"{k}={v}\n")

    return "".join(new_lines)


def configure_env_file(
    env_path: Path,
    gpu: GpuInfo,
    dry_run: bool = False,
) -> FileChangeResult:
    """Ensure VIDEO_GID and RENDER_GID are populated in .env without hardcoded defaults."""
    if not env_path.exists():
        original_text = ""
    else:
        try:
            original_text = env_path.read_text(encoding="utf-8")
        except OSError as e:
            return FileChangeResult(env_path, False, [], error=f"Read error: {e}")

    updates: dict[str, str] = {}
    if gpu.video_gid != "none":
        updates["VIDEO_GID"] = gpu.video_gid
    if gpu.render_gid != "none":
        updates["RENDER_GID"] = gpu.render_gid

    if not updates:
        return FileChangeResult(env_path, False, [], error="No GPU GIDs detected on host to configure in .env")

    new_text = update_env_content(original_text, updates)
    diff = generate_diff(original_text, new_text, env_path.name)
    has_changes = len(diff) > 0

    if has_changes and not dry_run:
        write_file_atomic(new_text, env_path)

    return FileChangeResult(env_path, has_changes, diff)


def configure_encoding_xml(
    config_dir: Path,
    accel: str,
    dry_run: bool = False,
) -> FileChangeResult:
    """Configure encoding.xml with hardware acceleration options."""
    encoding_path = config_dir / "config" / "encoding.xml"
    if not encoding_path.exists():
        return FileChangeResult(encoding_path, False, [], error="File does not exist yet")

    try:
        original_text = encoding_path.read_text(encoding="utf-8")
    except OSError as e:
        return FileChangeResult(encoding_path, False, [], error=f"Read error: {e}")

    parser = etree.XMLParser(remove_blank_text=False)
    try:
        tree = etree.fromstring(original_text.encode("utf-8"), parser).getroottree()
    except Exception as e:
        return FileChangeResult(encoding_path, False, [], error=f"Parse error: {e}")

    root = tree.getroot()

    # Hardware Acceleration Type
    set_or_create_child(root, "HardwareAccelerationType", accel)

    if accel in ("qsv", "vaapi"):
        for tag in ("EnableTonemapping", "EnableVppTonemapping", "EnableThrottling"):
            set_or_create_child(root, tag, "true")

    if accel == "qsv":
        for tag in (
            "EnableIntelLowPowerH264HwEncoder",
            "EnableIntelLowPowerHevcHwEncoder",
            "AllowHevcEncoding",
        ):
            set_or_create_child(root, tag, "true")

    new_text = serialize_xml(tree)
    diff = generate_diff(original_text, new_text, encoding_path.name)
    has_changes = len(diff) > 0

    if has_changes and not dry_run:
        write_file_atomic(new_text, encoding_path)

    return FileChangeResult(encoding_path, has_changes, diff)


def configure_system_xml(
    config_dir: Path,
    accel: str,
    dry_run: bool = False,
) -> FileChangeResult:
    """Configure system.xml trickplay hardware acceleration options."""
    system_path = config_dir / "config" / "system.xml"
    if not system_path.exists():
        return FileChangeResult(system_path, False, [], error="File does not exist yet")

    try:
        original_text = system_path.read_text(encoding="utf-8")
    except OSError as e:
        return FileChangeResult(system_path, False, [], error=f"Read error: {e}")

    parser = etree.XMLParser(remove_blank_text=False)
    try:
        tree = etree.fromstring(original_text.encode("utf-8"), parser).getroottree()
    except Exception as e:
        return FileChangeResult(system_path, False, [], error=f"Parse error: {e}")

    root = tree.getroot()
    trickplay = root.find("TrickplayOptions")
    if trickplay is None:
        trickplay = etree.SubElement(root, "TrickplayOptions")

    target_hw = "true" if accel in ("qsv", "vaapi") else "false"
    for tag in ("EnableHwAcceleration", "EnableHwEncoding"):
        set_or_create_child(trickplay, tag, target_hw)

    new_text = serialize_xml(tree)
    diff = generate_diff(original_text, new_text, system_path.name)
    has_changes = len(diff) > 0

    if has_changes and not dry_run:
        write_file_atomic(new_text, system_path)

    return FileChangeResult(system_path, has_changes, diff)


def configure_realtime_monitoring(
    config_dir: Path,
    dry_run: bool = False,
) -> list[FileChangeResult]:
    """Ensure Real-Time Monitoring is enabled across all library options.xml files."""
    root_dir = config_dir / "root"
    if not root_dir.exists():
        return []

    results: list[FileChangeResult] = []
    parser = etree.XMLParser(remove_blank_text=False)

    for options_path in sorted(root_dir.rglob("options.xml")):
        try:
            original_text = options_path.read_text(encoding="utf-8")
        except OSError as e:
            results.append(FileChangeResult(options_path, False, [], error=f"Read error: {e}"))
            continue

        try:
            tree = etree.fromstring(original_text.encode("utf-8"), parser).getroottree()
        except Exception as e:
            results.append(FileChangeResult(options_path, False, [], error=f"Parse error: {e}"))
            continue

        root = tree.getroot()
        set_or_create_child(root, "EnableRealtimeMonitor", "true")

        new_text = serialize_xml(tree)
        rel_path = options_path.relative_to(config_dir)
        diff = generate_diff(original_text, new_text, str(rel_path))
        has_changes = len(diff) > 0

        if has_changes and not dry_run:
            write_file_atomic(new_text, options_path)

        results.append(FileChangeResult(options_path, has_changes, diff))

    return results


# ==============================================================================
# Unit Test Suite
# ==============================================================================

class TestBootstrapJellyfin(unittest.TestCase):
    """Unit tests for GPU detection, XML parsing, .env updates, and diff generation."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        (self.config_dir / "config").mkdir(parents=True)
        (self.config_dir / "root" / "default" / "TV").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_detect_gpu_intel_qsv(self) -> None:
        vendor_file = self.config_dir / "vendor"
        vendor_file.write_text("0x8086\n", encoding="utf-8")
        render_dev = self.config_dir / "renderD128"
        render_dev.touch()

        info = detect_gpu(vendor_path=vendor_file, render_path=render_dev)
        self.assertEqual(info.accel_type, "qsv")
        self.assertEqual(info.vendor_id, "0x8086")

    def test_detect_gpu_amd_vaapi(self) -> None:
        vendor_file = self.config_dir / "vendor"
        vendor_file.write_text("0x1002\n", encoding="utf-8")
        render_dev = self.config_dir / "renderD128"
        render_dev.touch()

        info = detect_gpu(vendor_path=vendor_file, render_path=render_dev)
        self.assertEqual(info.accel_type, "vaapi")
        self.assertEqual(info.vendor_id, "0x1002")

    def test_detect_gpu_nvidia_nvenc(self) -> None:
        vendor_file = self.config_dir / "vendor"
        vendor_file.write_text("0x10de\n", encoding="utf-8")
        render_dev = self.config_dir / "renderD128"
        render_dev.touch()

        info = detect_gpu(vendor_path=vendor_file, render_path=render_dev)
        self.assertEqual(info.accel_type, "nvenc")
        self.assertEqual(info.vendor_id, "0x10de")

    def test_detect_gpu_none_when_no_device(self) -> None:
        vendor_file = self.config_dir / "nonexistent"
        render_dev = self.config_dir / "nonexistent_render"

        info = detect_gpu(vendor_path=vendor_file, render_path=render_dev)
        self.assertEqual(info.accel_type, "none")

    def test_configure_env_file_new_and_update(self) -> None:
        env_file = self.config_dir / ".env"
        initial_content = "HOSTNAME_BASE=009973.xyz\nOTHER_VAR=abc\n"
        env_file.write_text(initial_content, encoding="utf-8")

        mock_gpu = GpuInfo(vendor_id="0x8086", accel_type="qsv", render_gid="989", video_gid="985")

        # 1. Dry-run diff check
        res_dry = configure_env_file(env_file, mock_gpu, dry_run=True)
        self.assertTrue(res_dry.has_changes)
        self.assertEqual(env_file.read_text(encoding="utf-8"), initial_content)
        self.assertTrue(any("+VIDEO_GID=985" in line for line in res_dry.diff_lines))
        self.assertTrue(any("+RENDER_GID=989" in line for line in res_dry.diff_lines))

        # 2. Apply writes changes
        res_apply = configure_env_file(env_file, mock_gpu, dry_run=False)
        self.assertTrue(res_apply.has_changes)
        content_after = env_file.read_text(encoding="utf-8")
        self.assertIn("VIDEO_GID=985\n", content_after)
        self.assertIn("RENDER_GID=989\n", content_after)
        self.assertIn("HOSTNAME_BASE=009973.xyz\n", content_after)

        # 3. Re-run is idempotent (no-op)
        res_rerun = configure_env_file(env_file, mock_gpu, dry_run=False)
        self.assertFalse(res_rerun.has_changes)
        self.assertEqual(len(res_rerun.diff_lines), 0)

        # 4. Changing GID triggers an in-place update
        mock_gpu_changed = GpuInfo(vendor_id="0x8086", accel_type="qsv", render_gid="109", video_gid="44")
        res_change = configure_env_file(env_file, mock_gpu_changed, dry_run=False)
        self.assertTrue(res_change.has_changes)
        updated_content = env_file.read_text(encoding="utf-8")
        self.assertIn("VIDEO_GID=44\n", updated_content)
        self.assertIn("RENDER_GID=109\n", updated_content)
        self.assertNotIn("VIDEO_GID=985", updated_content)

    def test_set_or_create_child_existing(self) -> None:
        root = etree.Element("Options")
        child = etree.SubElement(root, "Accel")
        child.text = "none"

        changed, old_v, new_v = set_or_create_child(root, "Accel", "qsv")
        self.assertTrue(changed)
        self.assertEqual(old_v, "none")
        self.assertEqual(new_v, "qsv")
        self.assertEqual(root.findtext("Accel"), "qsv")

    def test_set_or_create_child_missing(self) -> None:
        root = etree.Element("Options")
        changed, old_v, new_v = set_or_create_child(root, "NewTag", "true")
        self.assertTrue(changed)
        self.assertEqual(old_v, "<missing>")
        self.assertEqual(new_v, "true")
        self.assertEqual(root.findtext("NewTag"), "true")

    def test_set_or_create_child_unchanged(self) -> None:
        root = etree.Element("Options")
        child = etree.SubElement(root, "Same")
        child.text = "true"

        changed, old_v, new_v = set_or_create_child(root, "Same", "true")
        self.assertFalse(changed)
        self.assertEqual(old_v, "true")
        self.assertEqual(new_v, "true")

    def test_encoding_xml_qsv_configuration(self) -> None:
        encoding_file = self.config_dir / "config" / "encoding.xml"
        initial_xml = """<?xml version="1.0" encoding="utf-8"?>
<EncodingOptions>
  <HardwareAccelerationType>none</HardwareAccelerationType>
  <EnableTonemapping>false</EnableTonemapping>
</EncodingOptions>
"""
        encoding_file.write_text(initial_xml, encoding="utf-8")

        # 1. Dry run produces diff without modifying file
        result = configure_encoding_xml(self.config_dir, "qsv", dry_run=True)
        self.assertTrue(result.has_changes)
        self.assertTrue(any("-  <HardwareAccelerationType>none" in line for line in result.diff_lines))
        self.assertTrue(any("+  <HardwareAccelerationType>qsv" in line for line in result.diff_lines))
        self.assertEqual(encoding_file.read_text(encoding="utf-8"), initial_xml)

        # 2. Apply writes file
        apply_res = configure_encoding_xml(self.config_dir, "qsv", dry_run=False)
        self.assertTrue(apply_res.has_changes)
        updated_content = encoding_file.read_text(encoding="utf-8")
        self.assertIn("<HardwareAccelerationType>qsv</HardwareAccelerationType>", updated_content)
        self.assertIn("<EnableTonemapping>true</EnableTonemapping>", updated_content)
        self.assertIn("<EnableIntelLowPowerH264HwEncoder>true</EnableIntelLowPowerH264HwEncoder>", updated_content)

        # 3. Idempotent re-run produces no changes
        rerun_res = configure_encoding_xml(self.config_dir, "qsv", dry_run=False)
        self.assertFalse(rerun_res.has_changes)
        self.assertEqual(len(rerun_res.diff_lines), 0)

    def test_system_xml_trickplay_creation_and_config(self) -> None:
        system_file = self.config_dir / "config" / "system.xml"
        initial_xml = """<?xml version="1.0" encoding="utf-8"?>
<ServerConfiguration>
  <ServerName>MyJellyfin</ServerName>
</ServerConfiguration>
"""
        system_file.write_text(initial_xml, encoding="utf-8")

        result = configure_system_xml(self.config_dir, "qsv", dry_run=False)
        self.assertTrue(result.has_changes)
        updated = system_file.read_text(encoding="utf-8")
        self.assertIn("<TrickplayOptions>", updated)
        self.assertIn("<EnableHwAcceleration>true</EnableHwAcceleration>", updated)
        self.assertIn("<EnableHwEncoding>true</EnableHwEncoding>", updated)

    def test_realtime_monitoring_options_xml(self) -> None:
        opt_file = self.config_dir / "root" / "default" / "TV" / "options.xml"
        initial_xml = """<?xml version="1.0" encoding="utf-8"?>
<LibraryOptions>
  <EnablePhotos>true</EnablePhotos>
  <EnableRealtimeMonitor>false</EnableRealtimeMonitor>
</LibraryOptions>
"""
        opt_file.write_text(initial_xml, encoding="utf-8")

        res_list = configure_realtime_monitoring(self.config_dir, dry_run=False)
        self.assertEqual(len(res_list), 1)
        self.assertTrue(res_list[0].has_changes)
        updated = opt_file.read_text(encoding="utf-8")
        self.assertIn("<EnableRealtimeMonitor>true</EnableRealtimeMonitor>", updated)

        # Second run should be no-op
        res_list2 = configure_realtime_monitoring(self.config_dir, dry_run=False)
        self.assertEqual(len(res_list2), 1)
        self.assertFalse(res_list2[0].has_changes)

    def test_format_path_home_relative(self) -> None:
        home = Path.home()
        test_file = home / "dotfiles" / "test.txt"
        self.assertEqual(format_path(test_file), "~/dotfiles/test.txt")

    def test_format_path_non_home(self) -> None:
        test_file = Path("/tmp/outside/test.txt")
        self.assertEqual(format_path(test_file), "/tmp/outside/test.txt")

    def test_format_path_none(self) -> None:
        self.assertEqual(format_path(None), "<none>")


def run_tests() -> int:
    """Run all test suites and report results."""
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestBootstrapJellyfin)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


# ==============================================================================
# CLI Entrypoint
# ==============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Jellyfin Hardware & Settings Bootstrap Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-d", "--detect",
        action="store_true",
        help="Print detected accelerator (qsv|vaapi|nvenc|none) and exit",
    )
    parser.add_argument(
        "--env",
        action="store_true",
        help="Print recommended host environment variables and GIDs and exit",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Print detailed GPU and configuration diagnostic info",
    )
    parser.add_argument(
        "-a", "--apply",
        action="store_true",
        help="Apply changes to disk and .env (default: dry-run preview only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying disk (default behavior)",
    )
    parser.add_argument(
        "-t", "--test",
        action="store_true",
        help="Run built-in unit test suite and exit",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="Path to Jellyfin config directory (default: auto-detected)",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Path to homelab .env file (default: auto-detected)",
    )

    args = parser.parse_args()

    if args.test:
        return run_tests()

    gpu = detect_gpu()

    if args.detect:
        print(gpu.accel_type)
        return 0

    if args.env:
        print(f"JELLYFIN_HW_ACCEL={gpu.accel_type}")
        print(f"RENDER_GID={gpu.render_gid}")
        print(f"VIDEO_GID={gpu.video_gid}")
        return 0

    config_dir = locate_config_dir(args.config_dir)
    env_file = locate_env_file(args.env_file)

    if args.info:
        table = Table(title="Jellyfin GPU & Host Diagnostic Info")
        table.add_column("Property", style="cyan", no_wrap=True)
        table.add_column("Value", style="green")

        table.add_row("GPU Device", str(RENDER_DEV_PATH))
        table.add_row("Vendor ID", gpu.vendor_id)
        table.add_row("Render GID", gpu.render_gid)
        table.add_row("Video GID", gpu.video_gid)
        table.add_row("Detected Accelerator", gpu.accel_type)
        table.add_row("Config Directory", format_path(config_dir))
        table.add_row(".env File", format_path(env_file) if env_file else "<not found>")

        console.print(table)
        return 0

    is_dry_run = not args.apply

    mode_label = "[bold yellow](DRY RUN)[/]" if is_dry_run else "[bold green](APPLY)[/]"
    prefix = "[bold cyan]\\[jellyfin/bootstrap][/]"
    console.print(f"{prefix} {mode_label} Target Accelerator: [bold green]{gpu.accel_type}[/]")
    console.print(f"{prefix} Config Directory: [magenta]{format_path(config_dir)}[/]")
    if env_file:
        console.print(f"{prefix} .env Path: [magenta]{format_path(env_file)}[/]\n")

    total_changes = 0

    # 1. Update homelab .env with dynamic GIDs
    if env_file:
        env_res = configure_env_file(env_file, gpu, dry_run=is_dry_run)
        if env_res.error:
            console.print(f"[bold red]{env_res.path.name} error:[/] {env_res.error}")
        elif env_res.has_changes:
            total_changes += 1
            action_desc = "Proposed diff for" if is_dry_run else "Applied changes to"
            console.print(
                f"[bold yellow]{action_desc} [magenta]{env_res.path.name}[/]:[/]"
                if is_dry_run
                else f"[bold green]{action_desc} [magenta]{env_res.path.name}[/]:[/]"
            )
            print_colorized_diff(env_res.diff_lines)
            console.print()
        else:
            console.print(
                f"  [bold green]✓[/] [magenta]{env_res.path.name}[/] GIDs "
                f"({gpu.render_gid}/{gpu.video_gid}) are already up to date."
            )

    # 2. Update encoding.xml
    enc_res = configure_encoding_xml(config_dir, gpu.accel_type, dry_run=is_dry_run)
    if enc_res.error:
        console.print(f"[bold red]{enc_res.path.name} error:[/] {enc_res.error}")
    elif enc_res.has_changes:
        total_changes += 1
        action_desc = "Proposed diff for" if is_dry_run else "Applied changes to"
        console.print(
            f"[bold yellow]{action_desc} [magenta]{enc_res.path.name}[/]:[/]"
            if is_dry_run
            else f"[bold green]{action_desc} [magenta]{enc_res.path.name}[/]:[/]"
        )
        print_colorized_diff(enc_res.diff_lines)
        console.print()
    else:
        console.print(f"  [bold green]✓[/] [magenta]{enc_res.path.name}[/] is already optimal.")

    # 3. Update system.xml
    sys_res = configure_system_xml(config_dir, gpu.accel_type, dry_run=is_dry_run)
    if sys_res.error:
        console.print(f"[bold red]{sys_res.path.name} error:[/] {sys_res.error}")
    elif sys_res.has_changes:
        total_changes += 1
        action_desc = "Proposed diff for" if is_dry_run else "Applied changes to"
        console.print(
            f"[bold yellow]{action_desc} [magenta]{sys_res.path.name}[/]:[/]"
            if is_dry_run
            else f"[bold green]{action_desc} [magenta]{sys_res.path.name}[/]:[/]"
        )
        print_colorized_diff(sys_res.diff_lines)
        console.print()
    else:
        console.print(f"  [bold green]✓[/] [magenta]{sys_res.path.name}[/] trickplay is already optimal.")

    # 4. Update library options.xml
    lib_results = configure_realtime_monitoring(config_dir, dry_run=is_dry_run)
    any_lib_changes = False
    for lib_res in lib_results:
        if lib_res.error:
            console.print(f"[bold red]{lib_res.path.name} error:[/] {lib_res.error}")
        elif lib_res.has_changes:
            total_changes += 1
            any_lib_changes = True
            rel_name = lib_res.path.relative_to(config_dir)
            action_desc = "Proposed diff for" if is_dry_run else "Applied changes to"
            console.print(
                f"[bold yellow]{action_desc} [magenta]{rel_name}[/]:[/]"
                if is_dry_run
                else f"[bold green]{action_desc} [magenta]{rel_name}[/]:[/]"
            )
            print_colorized_diff(lib_res.diff_lines)
            console.print()

    if not any_lib_changes:
        console.print("  [bold green]✓[/] Real-Time Monitoring is already enabled across all libraries.")

    if total_changes == 0:
        console.print("\n[bold green]All configuration files and .env are fully up-to-date. No changes needed.[/]")
    elif is_dry_run:
        console.print("\n[bold yellow]Dry-run complete. Re-run with [bold green]--apply[/bold green] to commit these changes.[/]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
