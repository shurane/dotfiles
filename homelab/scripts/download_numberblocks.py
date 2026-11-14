from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

import jellyfin

console = Console()

# Pre-configured season playlists (Official Numberblocks YouTube show)
SEASON_PLAYLISTS: dict[int, str] = {
    1: "https://www.youtube.com/show/VLPL9swKX1PviEr9UfByZqJYiN8KX3AXqyXm?sbp=KgtqVmVZbkNlaEVGRUAB",
    2: "https://www.youtube.com/show/VLPL9swKX1PviEpC7x7ZzmxZTVrwOV2zitcu?sbp=KgtYNVExOFBrdUx0TUAB",
    3: "https://www.youtube.com/show/VLPL9swKX1PviEruaholwotM1lOcNCQuweCl?sbp=Kgt4bkhVZjl6cVVfVUAB",
    4: "https://www.youtube.com/show/VLPL9swKX1PviEqpJgWu9DzINYclNC-rzOiF?sbp=KgtodElEbDBVVlR5SUAB",
    5: "https://www.youtube.com/show/VLPL9swKX1PviEph7heoMnLEfW2y28kwLNZw?sbp=Kgtobk1rZjNadEZmVUAB",
    6: "https://www.youtube.com/show/VLPL9swKX1PviEqUShSKIf5iS99jq1qAFztz?sbp=Kgs5STJUOHpkQjRja0AB",
    7: "https://www.youtube.com/show/VLPL9swKX1PviEovgpCesV8muL-i8RwogKvL?sbp=Kgs1Z2hrb3hST2Nzb0AB",
    8: "https://www.youtube.com/show/VLPL9swKX1PviErV5UKYedc69ITUoipMhr9M?sbp=KgtWclRmbXNJcV9Sa0AB",
}


def get_default_dest_dir() -> Path:
    return Path("/mnt/mango/media/tv/Numberblocks (2017)")


def parse_seasons(season_spec: str) -> list[int]:
    """Parse comma/hyphen season string like '5', '5,6', '5-8', or 'all'."""
    season_spec = season_spec.strip().lower()
    if season_spec in ("all", "*"):
        return sorted(SEASON_PLAYLISTS.keys())

    seasons: set[int] = set()
    for part in season_spec.split(","):
        part = part.strip()
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            seasons.update(range(int(start_s), int(end_s) + 1))
        elif part.isdigit():
            seasons.add(int(part))
        else:
            raise ValueError(f"Invalid season specification: {part}")

    return sorted(seasons)


def download_season(
    season: int,
    playlist_url: str,
    target_dir: Path,
    dry_run: bool = False,
    limit: int | None = None,
    episodes: str | None = None,
) -> int:
    """Download playlist using yt_dlp as an imported library strictly as MKV."""
    import yt_dlp

    outtmpl = str(target_dir / f"Numberblocks S{season}E%(playlist_index)02d %(clean_title)s.%(ext)s")

    args: list[str] = [
        "--parse-metadata",
        "title:(?P<clean_title>[^|]+)",
        "--replace-in-metadata",
        "clean_title",
        r"(?i)\s*-?\s*full episode.*",
        "",
        "--replace-in-metadata",
        "clean_title",
        r"\baka\b.*",
        "",
        "--replace-in-metadata",
        "clean_title",
        r"[^\w\s]",
        "",
        "--replace-in-metadata",
        "clean_title",
        r"^\s+|\s+$",
        "",
        "--format",
        "bestvideo+bestaudio/best",
        "--merge-output-format",
        "mkv",
        "--remux-video",
        "mkv",
        "--output",
        outtmpl,
    ]

    if dry_run:
        args.append("--simulate")
    if limit:
        args.extend(["--playlist-items", f"1-{limit}"])
    elif episodes:
        args.extend(["--playlist-items", episodes])

    args.append(playlist_url)

    _, _, urls, ydl_opts = yt_dlp.parse_options(args)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.download(urls)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download and organize Numberblocks episodes from YouTube using yt-dlp."
    )
    parser.add_argument(
        "--season",
        "-s",
        type=str,
        default="5",
        help="Season(s) to download: '1', '5', '1-8', '5,6', or 'all' (Default: 5)",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="Custom playlist URL override (used when specifying a single season)",
    )
    parser.add_argument(
        "--dest-dir",
        type=Path,
        default=get_default_dest_dir(),
        help=f"Base destination directory (Default: {get_default_dest_dir()})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of items to download per season, e.g. --limit 1 for testing",
    )
    parser.add_argument(
        "--episodes",
        type=str,
        default=None,
        help="Episode item range, e.g. '1-10' or '1,3,5'",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        "--simulate",
        action="store_true",
        help="Simulate downloads without writing files",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Trigger Jellyfin library scan after download completes",
    )

    args = parser.parse_args()

    try:
        seasons = parse_seasons(args.season)
    except ValueError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)

    if args.url and len(seasons) > 1:
        console.print("[bold red]Error:[/bold red] --url can only be used with a single season.")
        sys.exit(1)

    overall_exit_code = 0

    for season in seasons:
        if args.url:
            playlist_url = args.url
        elif season in SEASON_PLAYLISTS:
            playlist_url = SEASON_PLAYLISTS[season]
        else:
            console.print(f"[bold red]Error:[/bold red] No default URL configured for Season {season}. Provide --url.")
            overall_exit_code = 1
            continue

        target_dir = args.dest_dir / f"Season {season:02d}"
        if not args.dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)

        # 1-line ANSI colored status output
        console.print(
            f"[bold cyan]==> [Numberblocks][/bold cyan] "
            f"[bold green]Downloading Season {season}[/bold green] -> "
            f"[yellow]{target_dir}[/yellow]"
        )

        rc = download_season(
            season=season,
            playlist_url=playlist_url,
            target_dir=target_dir,
            dry_run=args.dry_run,
            limit=args.limit,
            episodes=args.episodes,
        )

        if rc != 0:
            console.print(f"[bold red]✖ Failed downloading Season {season} (exit code {rc})[/bold red]")
            overall_exit_code = rc

    if args.scan and overall_exit_code == 0:
        jellyfin.refresh()

    sys.exit(overall_exit_code)


if __name__ == "__main__":
    main()
