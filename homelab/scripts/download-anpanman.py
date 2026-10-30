#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "httpx>=0.28.1",
#     "anyio>=4.8.0",
#     "rich>=13.9.4",
# ]
# ///

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from enum import Enum, auto
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Sequence
from urllib.parse import quote

import anyio
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.text import Text

console = Console()

ARCHIVE_ITEM = "anpanman-episodes-1-600"
METADATA_URL = f"https://archive.org/metadata/{ARCHIVE_ITEM}"
BASE_DOWNLOAD_URL = f"https://archive.org/download/{ARCHIVE_ITEM}"


class DownloadStatus(Enum):
    NO_OP = auto()
    COMPLETED = auto()
    RESUMED_AND_COMPLETED = auto()
    FAILED = auto()


@dataclass(frozen=True, slots=True)
class EpisodeFile:
    name: str
    size: int
    md5: str | None
    episode_number: int
    segment: str  # e.g., "a", "b", or ""
    season: int

    @property
    def download_url(self) -> str:
        return f"{BASE_DOWNLOAD_URL}/{quote(self.name)}"

    @property
    def display_tag(self) -> str:
        seg_str = self.segment.upper() if self.segment else ""
        return f"Ep {self.episode_number:03d}{seg_str}"


@dataclass(frozen=True, slots=True)
class DownloadResult:
    file: EpisodeFile
    status: DownloadStatus
    bytes_downloaded: int
    duration_seconds: float
    error_message: str | None = None


def parse_range_spec(range_str: str) -> set[int]:
    """Parse comma/hyphen range string like '1', '1,2,3', '1-20', or 'all' into a set of integers."""
    range_str = range_str.strip().lower()
    if range_str in ("all", "*"):
        return set(range(1, 601))

    numbers: set[int] = set()
    for part in range_str.split(","):
        part = part.strip()
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            numbers.update(range(int(start_s), int(end_s) + 1))
        elif part.isdigit():
            numbers.add(int(part))
        else:
            raise ValueError(f"Invalid range specification: {part}")
    return numbers


async def fetch_archive_files(
    client: httpx.AsyncClient,
    cache_path: Path | None = None,
) -> list[EpisodeFile]:
    """Fetch metadata from Archive.org and extract video files grouped into seasons."""
    raw_data: dict[str, Any] | None = None

    if cache_path and cache_path.exists():
        cache_age = time.time() - cache_path.stat().st_mtime
        if cache_age < 86400:
            try:
                content = await anyio.Path(cache_path).read_text(encoding="utf-8")
                raw_data = json.loads(content)
            except Exception as e:
                console.print(f"[yellow]Warning: Failed to read cache: {e}[/yellow]")

    if raw_data is None:
        console.print(f"[dim]Fetching metadata from [cyan]{METADATA_URL}[/cyan]...[/dim]")
        resp = await client.get(METADATA_URL, timeout=30.0)
        resp.raise_for_status()
        raw_data = resp.json()
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            await anyio.Path(cache_path).write_text(json.dumps(raw_data), encoding="utf-8")

    files_list: list[dict[str, Any]] = raw_data.get("files", [])
    episodes: list[EpisodeFile] = []

    pattern = re.compile(r"^Anpanman\s*-\s*(\d+)([a-zA-Z]?)\.mp4$", re.IGNORECASE)

    for f in files_list:
        fname = f.get("name", "")
        if not fname.endswith(".mp4") or fname.endswith("_512kb.mp4"):
            continue

        match = pattern.match(fname)
        if not match:
            continue

        ep_num = int(match.group(1))
        segment = match.group(2).lower()
        size = int(f.get("size", 0))
        md5 = f.get("md5")

        season = min(6, max(1, ((ep_num - 1) // 100) + 1))

        episodes.append(
            EpisodeFile(
                name=fname,
                size=size,
                md5=md5,
                episode_number=ep_num,
                segment=segment,
                season=season,
            )
        )

    episodes.sort(key=lambda x: (x.episode_number, x.segment))
    return episodes


def ensure_hardlink(source_path: Path, target_path: Path) -> bool:
    """Create a hard link at target_path pointing to source_path if not already linked."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        if os.stat(source_path).st_ino == os.stat(target_path).st_ino:
            return False  # Already linked
        target_path.unlink()  # Different file, re-link

    os.link(source_path, target_path)
    return True


def compute_file_md5(file_path: Path) -> str:
    """Compute MD5 hash of a file by streaming 1MB blocks."""
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        while chunk := f.read(1048576):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def load_anpanman_metadata() -> dict[str, Any]:
    """Load episode titles and metadata from local json cache if available."""
    candidates = [
        Path(__file__).parent / "anpanman_metadata.json",
        Path.home() / "dotfiles/homelab/scripts/anpanman_metadata.json",
        Path("/home/ehtesh/dotfiles/homelab/scripts/anpanman_metadata.json"),
    ]
    for p in candidates:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def format_media_filename(file_info: EpisodeFile, metadata: dict[str, Any]) -> str:
    """Format filename using Option A standard: Soreike! Anpanman - S01E01 - Title.mp4."""
    key = f"{file_info.episode_number:04d}{file_info.segment or 'a'}"
    entry = metadata.get(key)
    title = entry.get("title_ro", "") if entry else ""
    seg_str = file_info.segment if file_info.segment else ""
    if title:
        return f"Soreike! Anpanman - S{file_info.season:02d}E{file_info.episode_number:02d}{seg_str} - {title}.mp4"
    return f"Soreike! Anpanman - S{file_info.season:02d}E{file_info.episode_number:02d}{seg_str}.mp4"


def ensure_media_link_and_nfo(
    source_path: Path,
    media_dir: Path,
    file_info: EpisodeFile,
    metadata: dict[str, Any],
) -> str:
    """Create hard link and accompanying NFO metadata file in Jellyfin media directory."""
    media_season_dir = media_dir / f"Season {file_info.season:02d}"
    link_filename = format_media_filename(file_info, metadata)
    link_path = media_season_dir / link_filename
    ensure_hardlink(source_path, link_path)

    key = f"{file_info.episode_number:04d}{file_info.segment or 'a'}"
    entry = metadata.get(key)
    title = entry.get("title_ro", "") if entry else ""
    title_ja = entry.get("title_ja", "") if entry else ""

    nfo_path = media_season_dir / link_filename.replace(".mp4", ".nfo")
    if not nfo_path.exists() or nfo_path.stat().st_size == 0:
        nfo_content = f"""<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<episodedetails>
  <title>{title or link_filename.removesuffix('.mp4')}</title>
  <originaltitle>{title_ja}</originaltitle>
  <season>{file_info.season}</season>
  <episode>{file_info.episode_number}</episode>
</episodedetails>
"""
        nfo_path.write_text(nfo_content, encoding="utf-8")

    return link_filename


async def download_episode_with_retry(
    client: httpx.AsyncClient,
    file_info: EpisodeFile,
    dest_dir: Path,
    media_dir: Path | None,
    progress: Progress,
    overall_task_id: TaskID,
    metadata: dict[str, Any],
    progress_tag: str = "",
    verify_checksum: bool = False,
    max_retries: int = 3,
) -> DownloadResult:
    """Download an episode with auto-retry on transient errors and rich live reporting."""
    season_dir = dest_dir / f"Season {file_info.season:02d}"
    season_dir.mkdir(parents=True, exist_ok=True)

    final_path = season_dir / file_info.name
    part_path = season_dir / f"{file_info.name}.part"

    # 1. Check for NO-OP: File already completely downloaded
    if final_path.exists():
        actual_size = final_path.stat().st_size
        if actual_size == file_info.size:
            checksum_note = ""
            if verify_checksum and file_info.md5:
                actual_md5 = compute_file_md5(final_path)
                if actual_md5 != file_info.md5.lower():
                    progress.console.print(
                        f"[dim]{progress_tag}[/dim][bold red]⚠ [CORRUPT][/bold red] "
                        f"[yellow]{file_info.name} MD5 {actual_md5} != expected {file_info.md5}. Re-downloading.[/yellow]"
                    )
                    final_path.unlink()
                else:
                    checksum_note = " [dim green](MD5 OK)[/dim green]"

            if final_path.exists():
                link_display = ""
                if media_dir:
                    link_filename = ensure_media_link_and_nfo(final_path, media_dir, file_info, metadata)
                    link_display = f" • [dim cyan]🔗 {link_filename}[/dim cyan]"

                progress.console.print(
                    f"[dim]{progress_tag}[/dim][bold blue]• [NO-OP][/bold blue] "
                    f"[white]{file_info.name}[/white] [dim]({actual_size / (1024**2):.1f} MB already complete)[/dim]{checksum_note}{link_display}"
                )
                progress.advance(overall_task_id, advance=file_info.size)
                return DownloadResult(
                    file=file_info,
                    status=DownloadStatus.NO_OP,
                    bytes_downloaded=0,
                    duration_seconds=0.0,
                )
        else:
            progress.console.print(
                f"[dim]{progress_tag}[/dim][yellow]⚠ [MISMATCH] {file_info.name} size {actual_size} != expected {file_info.size}. Re-downloading.[/yellow]"
            )
            final_path.unlink()

    # 2. Check if .part file is already complete from a previous interrupted rename
    if part_path.exists() and part_path.stat().st_size == file_info.size:
        # Check MD5 if available
        if file_info.md5:
            part_md5 = compute_file_md5(part_path)
            if part_md5 != file_info.md5.lower():
                part_path.unlink()
            else:
                part_path.rename(final_path)
        else:
            part_path.rename(final_path)

        if final_path.exists():
            link_display = ""
            if media_dir:
                link_filename = ensure_media_link_and_nfo(final_path, media_dir, file_info, metadata)
                link_display = f" • [dim cyan]🔗 {link_filename}[/dim cyan]"

            progress.console.print(
                f"[dim]{progress_tag}[/dim][bold green]✔ [RECOVERED][/bold green] [white]{file_info.name}[/white] .part file promoted.{link_display}"
            )
            progress.advance(overall_task_id, advance=file_info.size)
            return DownloadResult(
                file=file_info,
                status=DownloadStatus.COMPLETED,
                bytes_downloaded=0,
                duration_seconds=0.0,
            )

    last_error: Exception | None = None
    start_time = time.perf_counter()

    for attempt in range(1, max_retries + 1):
        resume_offset = 0
        if part_path.exists():
            part_size = part_path.stat().st_size
            if part_size < file_info.size:
                resume_offset = part_size
            else:
                part_path.unlink()
                resume_offset = 0

        headers: dict[str, str] = {}
        is_resume = resume_offset > 0

        if is_resume:
            headers["Range"] = f"bytes={resume_offset}-"

        file_task = progress.add_task(
            f"  [cyan]⬇ {file_info.name}[/cyan]",
            total=file_info.size,
            completed=resume_offset,
        )

        try:
            async with client.stream("GET", file_info.download_url, headers=headers) as resp:
                if is_resume and resp.status_code == 206:
                    open_mode = "ab"
                elif resp.status_code == 200:
                    open_mode = "wb"
                    resume_offset = 0
                elif resp.status_code == 416:
                    if part_path.exists():
                        part_path.unlink()
                    open_mode = "wb"
                    resume_offset = 0
                else:
                    resp.raise_for_status()

                bytes_streamed = 0
                async with await anyio.open_file(part_path, open_mode) as f:
                    async for chunk in resp.aiter_bytes(chunk_size=131072):
                        await f.write(chunk)
                        chunk_len = len(chunk)
                        bytes_streamed += chunk_len
                        progress.advance(file_task, advance=chunk_len)
                        progress.advance(overall_task_id, advance=chunk_len)

            final_part_size = part_path.stat().st_size
            if final_part_size != file_info.size:
                raise IOError(f"Downloaded size {final_part_size} != expected {file_info.size}")

            # Verify MD5 on freshly completed download before promotion
            if file_info.md5:
                actual_md5 = compute_file_md5(part_path)
                if actual_md5 != file_info.md5.lower():
                    part_path.unlink()
                    raise IOError(f"MD5 mismatch: computed {actual_md5} != expected {file_info.md5}")

            part_path.rename(final_path)
            progress.remove_task(file_task)

            duration = time.perf_counter() - start_time
            speed_mb = (bytes_streamed / (1024**2)) / duration if duration > 0 else 0

            link_display = ""
            if media_dir:
                link_filename = ensure_media_link_and_nfo(final_path, media_dir, file_info, metadata)
                link_display = f" • [dim cyan]🔗 {link_filename}[/dim cyan]"

            status_text = "RESUMED & COMPLETED" if is_resume else "DONE"
            progress.console.print(
                f"[dim]{progress_tag}[/dim][bold green]✔ [{status_text}][/bold green] "
                f"[bold white]{file_info.name}[/bold white] "
                f"[green]({file_info.size / (1024**2):.1f} MB in {duration:.1f}s, {speed_mb:.2f} MB/s)[/green]{link_display}"
            )

            return DownloadResult(
                file=file_info,
                status=DownloadStatus.RESUMED_AND_COMPLETED if is_resume else DownloadStatus.COMPLETED,
                bytes_downloaded=bytes_streamed,
                duration_seconds=duration,
            )

        except Exception as exc:
            progress.remove_task(file_task)
            last_error = exc
            progress.console.print(
                f"[dim]{progress_tag}[/dim][bold red]⚠ [RETRY {attempt}/{max_retries}][/bold red] "
                f"[yellow]{file_info.name}: {exc}[/yellow]"
            )
            if attempt < max_retries:
                await anyio.sleep(2**attempt)

    progress.console.print(
        f"[dim]{progress_tag}[/dim][bold red]✖ [FAILED][/bold red] [red]{file_info.name} after {max_retries} attempts: {last_error}[/red]"
    )
    return DownloadResult(
        file=file_info,
        status=DownloadStatus.FAILED,
        bytes_downloaded=0,
        duration_seconds=time.perf_counter() - start_time,
        error_message=str(last_error),
    )


def print_summary_and_stats(
    results: list[DownloadResult],
    dest_dir: Path,
    media_dir: Path | None,
    total_elapsed: float,
) -> None:
    """Print a rich summary panel, stats table, and itemized breakdown of downloaded vs skipped files."""
    completed_results = [r for r in results if r.status in (DownloadStatus.COMPLETED, DownloadStatus.RESUMED_AND_COMPLETED)]
    noop_results = [r for r in results if r.status == DownloadStatus.NO_OP]
    failed_results = [r for r in results if r.status == DownloadStatus.FAILED]

    total_files = len(results)
    total_downloaded_bytes = sum(r.bytes_downloaded for r in completed_results)
    total_noop_bytes = sum(r.file.size for r in noop_results)
    avg_speed = (total_downloaded_bytes / (1024**2)) / total_elapsed if total_elapsed > 0 else 0

    # 1. Summary Statistics Table
    summary_table = Table(
        title="[bold magenta]Soreike! Anpanman Download Summary[/bold magenta]",
        box=None,
        show_header=True,
        header_style="bold cyan",
        expand=True,
    )
    summary_table.add_column("Category", style="bold white", width=22)
    summary_table.add_column("Files", justify="right", style="bold", width=7)
    summary_table.add_column("Data Volume", justify="right", style="green", width=14)
    summary_table.add_column("Details", style="dim", ratio=1)

    summary_table.add_row(
        "[green]✔ Downloaded & Linked[/green]",
        str(len(completed_results)),
        f"{total_downloaded_bytes / (1024**2):.1f} MB",
        f"Avg speed: {avg_speed:.2f} MB/s",
    )
    summary_table.add_row(
        "[blue]• Already Present (No-Op)[/blue]",
        str(len(noop_results)),
        f"{total_noop_bytes / (1024**2):.1f} MB",
        "Verified & skipped without re-downloading",
    )
    if failed_results:
        summary_table.add_row(
            "[red]✖ Failed[/red]",
            str(len(failed_results)),
            f"{sum(r.file.size for r in failed_results) / (1024**2):.1f} MB",
            f"{len(failed_results)} files require re-trying",
        )

    summary_table.add_section()
    summary_table.add_row(
        "[bold]Total Processed[/bold]",
        f"[bold]{total_files}[/bold]",
        f"[bold]{(total_downloaded_bytes + total_noop_bytes) / (1024**2):.1f} MB[/bold]",
        f"Total duration: {total_elapsed:.1f}s",
    )

    console.print()
    console.print(Panel(summary_table, border_style="cyan", padding=(1, 2)))

    # 2. Itemized Status Table (What was downloaded and what was not)
    manifest_table = Table(
        title="[bold]Episode Manifest (Status Breakdown)[/bold]",
        show_header=True,
        header_style="bold blue",
    )
    manifest_table.add_column("Tag", style="cyan", no_wrap=True)
    manifest_table.add_column("Filename", style="white", no_wrap=True)
    manifest_table.add_column("Size", justify="right", style="yellow", no_wrap=True)
    manifest_table.add_column("Status", justify="center", no_wrap=True)
    manifest_table.add_column("Metrics / Notes", style="dim")

    # Sort results by episode number and segment
    for r in sorted(results, key=lambda x: (x.file.episode_number, x.file.segment)):
        size_str = f"{r.file.size / (1024**2):.1f} MB"
        if r.status == DownloadStatus.COMPLETED:
            status_badge = "[bold green]✔ Downloaded[/bold green]"
            speed = (r.bytes_downloaded / (1024**2)) / r.duration_seconds if r.duration_seconds > 0 else 0
            metrics = f"{r.duration_seconds:.1f}s @ {speed:.1f} MB/s"
        elif r.status == DownloadStatus.RESUMED_AND_COMPLETED:
            status_badge = "[bold yellow]↻ Resumed[/bold yellow]"
            metrics = f"Resumed & verified"
        elif r.status == DownloadStatus.NO_OP:
            status_badge = "[bold blue]• Pre-existing[/bold blue]"
            metrics = "Existing copy matched"
        else:
            status_badge = "[bold red]✖ Failed[/bold red]"
            metrics = r.error_message or "Error occurred"

        manifest_table.add_row(r.file.display_tag, r.file.name, size_str, status_badge, metrics)

    console.print(manifest_table)
    console.print()


async def main_async(args: argparse.Namespace) -> int:
    target_seasons = parse_range_spec(args.season)
    target_episodes: set[int] | None = None
    if args.episodes:
        target_episodes = parse_range_spec(args.episodes)

    dest_dir = Path(args.dest_dir).resolve()
    media_dir = Path(args.media_dir).resolve() if args.media_dir else None
    cache_path = dest_dir / ".archive_metadata.json"

    console.print(
        Panel.fit(
            f"[bold cyan]Soreike! Anpanman Downloader & Jellyfin Syncer[/bold cyan]\n"
            f"[dim]Seasons:[/dim] [green]{sorted(target_seasons)}[/green] | "
            f"[dim]Episodes:[/dim] [yellow]{args.episodes or 'All in season'}[/yellow] | "
            f"[dim]Concurrency:[/dim] [magenta]{args.concurrency}[/magenta]\n"
            f"[dim]Dest Directory:[/dim] {dest_dir}\n"
            f"[dim]Media Directory:[/dim] {media_dir or 'None'}",
            border_style="magenta",
        )
    )

    metadata = load_anpanman_metadata()
    limits = httpx.Limits(max_connections=args.concurrency + 2, max_keepalive_connections=5)
    timeout = httpx.Timeout(connect=15.0, read=60.0, write=60.0, pool=15.0)
    overall_start_time = time.perf_counter()

    async with httpx.AsyncClient(
        follow_redirects=True,
        limits=limits,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (compatible; AnpanmanDownloader/1.0)"},
    ) as client:
        all_episodes = await fetch_archive_files(client, cache_path=cache_path)
        selected_episodes = [ep for ep in all_episodes if ep.season in target_seasons]

        if target_episodes is not None:
            selected_episodes = [ep for ep in selected_episodes if ep.episode_number in target_episodes]

        if args.limit and args.limit > 0:
            selected_episodes = selected_episodes[: args.limit]

        total_files = len(selected_episodes)
        total_size_bytes = sum(ep.size for ep in selected_episodes)

        if total_files == 0:
            console.print("[yellow]No files matched the specified season/episode filters.[/yellow]")
            return 0

        # Pre-flight library storage scan
        existing_count = 0
        existing_bytes = 0
        pending_count = 0
        pending_bytes = 0

        for ep in selected_episodes:
            ep_season_dir = dest_dir / f"Season {ep.season:02d}"
            ep_path = ep_season_dir / ep.name
            if ep_path.exists() and ep_path.stat().st_size == ep.size:
                existing_count += 1
                existing_bytes += ep.size
            else:
                pending_count += 1
                pending_bytes += ep.size

        scan_table = Table(box=None, show_header=False, expand=True)
        scan_table.add_column("Category", style="bold cyan", width=25)
        scan_table.add_column("Status", style="white")
        scan_table.add_row(
            "Batch Target",
            f"[bold]{total_files}[/bold] files ({total_size_bytes / (1024**2):.1f} MB / {total_size_bytes / (1024**3):.2f} GB)",
        )
        scan_table.add_row(
            "[green]✔ Already Downloaded[/green]",
            f"[bold green]{existing_count}[/bold green] files ({existing_bytes / (1024**2):.1f} MB) • [dim]0 bytes needed[/dim]",
        )
        scan_table.add_row(
            "[yellow]⬇ Pending Download[/yellow]",
            f"[bold yellow]{pending_count}[/bold yellow] files ({pending_bytes / (1024**2):.1f} MB / {pending_bytes / (1024**3):.2f} GB)",
        )

        console.print(
            Panel(
                scan_table,
                title="[bold]Pre-flight Storage & Cache Scan[/bold]",
                border_style="blue",
                padding=(0, 2),
            )
        )
        console.print()

        # Rich live progress bar
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}[/bold cyan]"),
            BarColumn(bar_width=35),
            TaskProgressColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=False,
        )

        with progress:
            overall_task = progress.add_task(
                f"Batch ({total_files} files)",
                total=total_size_bytes,
            )

            semaphore = asyncio.Semaphore(args.concurrency)
            counter = 0
            counter_lock = asyncio.Lock()

            async def worker(ep: EpisodeFile) -> DownloadResult:
                nonlocal counter
                async with semaphore:
                    async with counter_lock:
                        counter += 1
                        current_idx = counter
                    progress_tag = f"[{current_idx}/{total_files}] "
                    return await download_episode_with_retry(
                        client=client,
                        file_info=ep,
                        dest_dir=dest_dir,
                        media_dir=media_dir,
                        progress=progress,
                        overall_task_id=overall_task,
                        metadata=metadata,
                        progress_tag=progress_tag,
                        verify_checksum=args.verify_checksum,
                    )

            tasks = [asyncio.create_task(worker(ep)) for ep in selected_episodes]
            results: list[DownloadResult] = await asyncio.gather(*tasks)

    total_elapsed = time.perf_counter() - overall_start_time

    # Print summary and itemized stats table
    print_summary_and_stats(
        results=results,
        dest_dir=dest_dir,
        media_dir=media_dir,
        total_elapsed=total_elapsed,
    )

    failed_count = sum(1 for r in results if r.status == DownloadStatus.FAILED)
    if failed_count > 0:
        return 1

    if args.scan and media_dir:
        scan_bin = Path.home() / ".local/bin/jellyfin-scan"
        if scan_bin.exists():
            console.print(f"[bold cyan]Triggering Jellyfin library scan via [white]{scan_bin}[/white]...[/bold cyan]")
            proc = await anyio.run_process([str(scan_bin)], check=False)
            if proc.returncode == 0:
                console.print("[bold green]✔ Jellyfin library scan triggered successfully.[/bold green]")
            else:
                console.print(f"[bold red]✖ Jellyfin scan failed with exit code {proc.returncode}[/bold red]")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and organize Soreike! Anpanman from Internet Archive.")
    parser.add_argument(
        "--season",
        type=str,
        default="1",
        help="Season(s) to download: '1', '1,2', '1-6', or 'all' (Default: 1)",
    )
    parser.add_argument(
        "--episodes",
        type=str,
        default=None,
        help="Episode range within selected season, e.g. '1-20' or '21-60' (Default: all episodes in season)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of files to download (for testing, e.g. --limit 1)",
    )
    parser.add_argument(
        "--dest-dir",
        type=str,
        default="/mnt/mango/torrents/tv/Anpanman (1988)",
        help="Destination directory for downloads (Default: /mnt/mango/torrents/tv/Anpanman (1988))",
    )
    parser.add_argument(
        "--media-dir",
        type=str,
        default="/mnt/mango/media/tv/Soreike! Anpanman (1988)",
        help="Media directory for Jellyfin hardlinks (Default: /mnt/mango/media/tv/Soreike! Anpanman (1988))",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Number of concurrent downloads (Default: 2)",
    )
    parser.add_argument(
        "--verify-checksum",
        action="store_true",
        help="Perform deep MD5 checksum verification on all pre-existing files (Default: false, relies on exact byte size)",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Trigger Jellyfin library scan after download completes",
    )

    args = parser.parse_args()
    exit_code = asyncio.run(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
