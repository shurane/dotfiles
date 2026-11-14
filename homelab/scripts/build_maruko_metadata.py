"""
Fetch Chibi Maruko-chan (1990) episode metadata from Japanese Wikipedia and generate maruko_metadata.json.
Scrapes: https://ja.wikipedia.org/wiki/ちびまる子ちゃんのエピソード一覧 (第1期: 1990-1992, 142 episodes)
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx
import pykakasi
from bs4 import BeautifulSoup

WIKI_PAGE = "ちびまる子ちゃんのエピソード一覧"
API_URL = "https://ja.wikipedia.org/w/api.php"
USER_AGENT = "MarukoHomelabIndexer/1.0 (https://github.com/ehteshamz; personal homelab)"


def create_kakasi_converter() -> pykakasi.kakasi:
    return pykakasi.kakasi()


def to_romaji(converter: pykakasi.kakasi, text: str) -> str:
    # Clean footnote links or annotations
    text = re.sub(r"\[.*?\]", "", text).strip()
    text = re.sub(r"\(.*?\)", "", text).strip()

    conv = converter.convert(text)
    words = [x["hepburn"] for x in conv if x["hepburn"]]
    s = " ".join(words)
    s = " ".join(w.capitalize() for w in s.split())

    # Fix lowercase grammatical particles
    s = re.sub(r"\bTo\b", "to", s)
    s = re.sub(r"\bNo\b", "no", s)
    s = re.sub(r"\bNi\b", "ni", s)
    s = re.sub(r"\bHe\b", "e", s)
    s = re.sub(r"\bWa\b", "wa", s)
    s = re.sub(r"\bGa\b", "ga", s)
    s = re.sub(r"\bO\b", "o", s)

    return s.replace("/", "-").replace(":", "-").replace("?", "").replace("*", "")


def scrape_season_one(delay: float = 1.0) -> dict[str, dict]:
    converter = create_kakasi_converter()
    ep_data: dict[str, dict] = {}
    headers = {"User-Agent": USER_AGENT}

    # Section 2: 1990 (Eps 1-52), Section 3: 1991 (Eps 53-103), Section 4: 1992 (Eps 104-142)
    sections = [(2, "1990"), (3, "1991"), (4, "1992")]

    for sec, year in sections:
        print(f"Fetching Wikipedia section {sec} ({year})...")
        params = {
            "action": "parse",
            "page": WIKI_PAGE,
            "prop": "text",
            "section": str(sec),
            "format": "json",
        }

        try:
            resp = httpx.get(API_URL, params=params, headers=headers, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            print(f"Error fetching section {sec}: {e}", file=sys.stderr)
            continue

        html = data.get("parse", {}).get("text", {}).get("*", "")
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.find_all("tr")

        current_ep: int | None = None
        for row in rows:
            cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            if not cells or cells[0] == "話数":
                continue

            m = re.match(r"^第(\d+)話", cells[0])
            if m:
                current_ep = int(m.group(1))
                air_date_raw = cells[-1] if len(cells) > 2 else ""
                dm = re.search(r"(\d+)月(\d+)日", air_date_raw)
                air_date = f"{year}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}" if dm else ""
                title = cells[1]
                ep_data[str(current_ep)] = {
                    "episode": current_ep,
                    "season": 1,
                    "air_date": air_date,
                    "titles_ja": [title],
                    "title_ja": title,
                    "title_ro": to_romaji(converter, title),
                }
            elif current_ep is not None and cells and cells[0].startswith("「"):
                sub_title = cells[0]
                ep_data[str(current_ep)]["titles_ja"].append(sub_title)
                all_ja = "／".join(ep_data[str(current_ep)]["titles_ja"])  # noqa: RUF001
                ep_data[str(current_ep)]["title_ja"] = all_ja
                ep_data[str(current_ep)]["title_ro"] = " / ".join(
                    to_romaji(converter, t) for t in ep_data[str(current_ep)]["titles_ja"]
                )

        time.sleep(delay)

    return ep_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape and build Chibi Maruko-chan (1990) episode metadata.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "maruko_metadata.json",
        help="Output path for maruko_metadata.json",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print sample entries without overwriting file")
    args = parser.parse_args()

    print("Starting Chibi Maruko-chan metadata scrape (Season 1, 142 episodes)...")
    data = scrape_season_one()
    print(f"Scraped {len(data)} total episodes.")

    if args.dry_run:
        print("\n[Dry Run] Sample entries:")
        for k in ["1", "2", "6", "142"]:
            if k in data:
                print(f"  Ep {k}: {data[k]}")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Saved metadata to {args.output}")


if __name__ == "__main__":
    main()
