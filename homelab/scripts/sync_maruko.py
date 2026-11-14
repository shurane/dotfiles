"""
Sync and hardlink Chibi Maruko-chan (1990) episodes into Jellyfin TV library with .nfo metadata.
"""

import argparse
import json
import os
import re
import subprocess
import xml.sax.saxutils as saxutils
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import jellyfin

console = Console()
METADATA_PATH = Path(__file__).resolve().parent / "maruko_metadata.json"


def load_metadata() -> dict[str, dict]:
    if METADATA_PATH.exists():
        try:
            return json.loads(METADATA_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            console.print(f"[yellow]Warning: Failed to read {METADATA_PATH}: {e}[/yellow]")
    return {}


def parse_range_spec(range_str: str) -> set[int]:
    """Parse comma/hyphen episode string like '1-10', '1,3,5', or '5-15'."""
    result: set[int] = set()
    for part in range_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_str, end_str = part.split("-", 1)
            result.update(range(int(start_str), int(end_str) + 1))
        else:
            result.add(int(part))
    return result


def extract_english_title_from_mkv(mkv_path: Path) -> str | None:
    """Extract translated segment titles from ASS subtitle tracks (EpTitle style)."""
    try:
        cmd = [
            "ffmpeg",
            "-i",
            str(mkv_path),
            "-vn",
            "-an",
            "-c:s",
            "copy",
            "-f",
            "ass",
            "-",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10.0, check=False)  # noqa: S603
        titles: list[str] = []
        for line in res.stdout.splitlines():
            if "EpTitle" in line and line.startswith("Dialogue:"):
                parts = line.split(",", 9)
                if len(parts) == 10:
                    raw_text = parts[9].replace(r"\N", " ").strip()
                    cleaned = re.sub(r"\{.*?\}", "", raw_text).strip()
                    cleaned = re.sub(r"\s+", " ", cleaned)
                    if cleaned and cleaned not in titles:
                        titles.append(cleaned)
        if titles:
            return " & ".join(titles)
    except Exception as e:
        console.print(f"[dim]Subtitle probe note for {mkv_path.name}: {e}[/dim]")
    return None


def generate_nfo_content(
    title: str,
    original_title: str,
    season: int,
    episode: int,
    air_date: str | None = None,
) -> str:
    escaped_title = saxutils.escape(title, {"'": "&apos;", '"': "&quot;"})
    escaped_orig = saxutils.escape(original_title, {"'": "&apos;", '"': "&quot;"})

    lines = [
        '<?xml version="1.0" encoding="utf-8" standalone="yes"?>',
        "<episodedetails>",
        f"  <title>{escaped_title}</title>",
        f"  <originaltitle>{escaped_orig}</originaltitle>",
        f"  <season>{season}</season>",
        f"  <episode>{episode}</episode>",
    ]
    if air_date:
        lines.append(f"  <aired>{air_date}</aired>")
    lines.append("</episodedetails>")
    lines.append("")
    return "\n".join(lines)


def find_source_files(source_dir: Path) -> list[tuple[int, Path]]:
    """Scan source directory for Maruko episodes."""
    results: list[tuple[int, Path]] = []
    pattern = re.compile(r"\(1990\)\s*(\d{2,3})")

    # Look in source_dir and any immediate subdirectories matching Maruko
    candidate_dirs = [source_dir]
    if source_dir.exists():
        candidate_dirs.extend(item for item in source_dir.iterdir() if item.is_dir() and "maruko" in item.name.lower())

    seen_eps: set[int] = set()
    for d in candidate_dirs:
        for f in sorted(d.glob("*.mkv")):
            m = pattern.search(f.name)
            if m:
                ep_num = int(m.group(1))
                if ep_num not in seen_eps:
                    seen_eps.add(ep_num)
                    results.append((ep_num, f))

    return sorted(results, key=lambda x: x[0])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync, hardlink, and generate .nfo sidecars for Chibi Maruko-chan (1990)."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("/mnt/mango/torrents/tv"),
        help="Base directory containing torrent downloads (Default: /mnt/mango/torrents/tv)",
    )
    parser.add_argument(
        "--dest-dir",
        type=Path,
        default=Path("/mnt/mango/media/tv/Chibi Maruko-chan (1990)/Season 01"),
        help="Destination directory for Jellyfin (Default: /mnt/mango/media/tv/Chibi Maruko-chan (1990)/Season 01)",
    )
    parser.add_argument(
        "--episodes",
        type=str,
        default=None,
        help="Episode range to process, e.g. '1-10' or '1,3,5'",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of episodes to process",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate actions without creating links or writing files",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Trigger Jellyfin library scan after sync completes",
    )

    args = parser.parse_args()

    metadata = load_metadata()
    target_episodes = parse_range_spec(args.episodes) if args.episodes else None

    console.print(
        Panel.fit(
            f"[bold cyan]Chibi Maruko-chan (1990) Jellyfin Syncer & NFO Generator[/bold cyan]\n"
            f"[dim]Source Directory:[/dim] {args.source_dir}\n"
            f"[dim]Dest Directory:[/dim] {args.dest_dir}\n"
            f"[dim]Filter Episodes:[/dim] [yellow]{args.episodes or 'All discovered'}[/yellow]"
            f"{' [dim red](DRY RUN)[/dim red]' if args.dry_run else ''}",
            border_style="magenta",
        )
    )

    source_files = find_source_files(args.source_dir)
    if not source_files:
        console.print("[yellow]No Chibi Maruko-chan files found in source directory.[/yellow]")
        return

    # Filter by episode range
    if target_episodes is not None:
        source_files = [item for item in source_files if item[0] in target_episodes]

    # Limit
    if args.limit and args.limit > 0:
        source_files = source_files[: args.limit]

    table = Table(title=f"Processing {len(source_files)} Episodes", show_header=True, header_style="bold cyan")
    table.add_column("Episode", style="green", width=10)
    table.add_column("Link Status", style="white", width=16)
    table.add_column("English Title", style="cyan")
    table.add_column("Japanese Title", style="yellow")
    table.add_column("NFO Status", style="magenta", width=14)

    if not args.dry_run:
        args.dest_dir.mkdir(parents=True, exist_ok=True)

    links_created = 0
    nfos_written = 0

    for ep_num, src_path in source_files:
        dest_mkv = args.dest_dir / f"Chibi Maruko-chan (1990) - S01E{ep_num:02d}.mkv"
        dest_nfo = args.dest_dir / f"Chibi Maruko-chan (1990) - S01E{ep_num:02d}.nfo"

        link_status = "Already linked"
        if not dest_mkv.exists():
            if not args.dry_run:
                try:
                    os.link(src_path, dest_mkv)
                    links_created += 1
                    link_status = "[green]Hardlinked[/green]"
                except OSError as e:
                    link_status = f"[red]Link failed: {e}[/red]"
            else:
                link_status = "[dim]Would link[/dim]"
        elif not args.dry_run and dest_mkv.stat().st_ino != src_path.stat().st_ino:
            link_status = "[yellow]Exists (diff inode)[/yellow]"

        # Resolve titles
        meta_entry = metadata.get(str(ep_num), {})
        title_ja = meta_entry.get("title_ja", "")
        air_date = meta_entry.get("air_date")

        # Extract English title from subtitle track, or fall back to metadata
        title_en = extract_english_title_from_mkv(src_path)
        if not title_en:
            title_en = meta_entry.get("title_ro", f"Episode {ep_num}")

        nfo_status = "Skipped"
        nfo_content = generate_nfo_content(
            title=title_en,
            original_title=title_ja,
            season=1,
            episode=ep_num,
            air_date=air_date,
        )

        needs_write = True
        if dest_nfo.exists() and dest_nfo.read_text(encoding="utf-8") == nfo_content:
            needs_write = False
            nfo_status = "Up to date"

        if needs_write:
            if not args.dry_run:
                try:
                    dest_nfo.write_text(nfo_content, encoding="utf-8")
                    nfos_written += 1
                    nfo_status = "[green]Written[/green]"
                except OSError as e:
                    nfo_status = f"[red]Write failed: {e}[/red]"
            else:
                nfo_status = "[dim]Would write[/dim]"

        table.add_row(
            f"S01E{ep_num:02d}",
            link_status,
            title_en,
            title_ja,
            nfo_status,
        )

    console.print(table)
    console.print(
        f"\n[bold]Summary:[/bold] {links_created} hardlinks created, {nfos_written} NFO sidecars written.\n"
    )

    if args.scan:
        jellyfin.refresh(console=console, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
