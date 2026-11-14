"""
Fetch Anpanman episode metadata from Japanese Wikipedia and generate anpanman_metadata.json.
Scrapes: https://ja.wikipedia.org/wiki/それいけ!アンパンマンのエピソード一覧
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pykakasi
from bs4 import BeautifulSoup

WIKI_PAGE = "それいけ!アンパンマンのエピソード一覧"
API_URL = "https://ja.wikipedia.org/w/api.php"
USER_AGENT = "AnpanmanHomelabIndexer/1.0 (https://github.com/ehteshamz; personal homelab)"


def create_kakasi_converter() -> pykakasi.kakasi:
    return pykakasi.kakasi()


def to_romaji(converter: pykakasi.kakasi, text: str) -> str:
    # Clean footnote links or annotations
    text = re.sub(r"\[.*?\]", "", text).strip()
    text = re.sub(r"\(.*?\)", "", text).strip()

    # Separate common particles attached to names/katakana
    text = re.sub(r"(アンパンマン|ばいきんまん|カレーパンマン|しょくぱんまん)と", r"\1 と ", text)
    text = re.sub(r"([ァ-ンー]+)と([ァ-ンぁ-ん])", r"\1 と \2", text)
    text = re.sub(r"([ァ-ンー]+)の([ァ-ンぁ-ん])", r"\1 の \2", text)

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

    # Sanitize filesystem-unfriendly characters
    return s.replace("/", "-").replace(":", "-").replace("?", "").replace("*", "")


def scrape_sections(start_section: int = 2, end_section: int = 8, delay: float = 1.0) -> dict:
    converter = create_kakasi_converter()
    ep_data = {}
    headers = {"User-Agent": USER_AGENT}

    for sec in range(start_section, end_section + 1):
        print(f"Fetching Wikipedia section {sec}...")
        params = urllib.parse.urlencode(
            {
                "action": "parse",
                "page": WIKI_PAGE,
                "prop": "text",
                "section": sec,
                "format": "json",
            }
        )
        req = urllib.request.Request(f"{API_URL}?{params}", headers=headers)

        try:
            with urllib.request.urlopen(req) as resp:
                data = json.load(resp)
        except Exception as e:
            print(f"Error fetching section {sec}: {e}", file=sys.stderr)
            continue

        html = data.get("parse", {}).get("text", {}).get("*", "")
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.find_all("tr")

        current_ep = None
        for row in rows:
            cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            if not cells or cells[0] in ("話数", "通算話数"):
                continue

            # Standard row with episode number in first cell
            m = re.match(r"^(\d+)", cells[0])
            if m:
                current_ep = int(m.group(1))
                title = cells[2] if len(cells) > 2 else ""
                title = re.sub(r"\[.*?\]", "", title).strip()
                ep_data[f"{current_ep:04d}a"] = {
                    "episode": current_ep,
                    "segment": "a",
                    "title_ja": title,
                    "title_ro": to_romaji(converter, title),
                }
            # Multi-segment second row under same episode number
            elif current_ep is not None and len(cells) > 0:
                title = cells[0]
                title = re.sub(r"\[.*?\]", "", title).strip()
                if title and not title.isdigit():
                    ep_data[f"{current_ep:04d}b"] = {
                        "episode": current_ep,
                        "segment": "b",
                        "title_ja": title,
                        "title_ro": to_romaji(converter, title),
                    }

        time.sleep(delay)

    return ep_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape and build Anpanman episode metadata.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "anpanman_metadata.json",
        help="Output path for anpanman_metadata.json",
    )
    parser.add_argument("--start-sec", type=int, default=2, help="Start section in Wikipedia")
    parser.add_argument("--end-sec", type=int, default=8, help="End section in Wikipedia")
    parser.add_argument("--dry-run", action="store_true", help="Print sample entries without overwriting file")
    args = parser.parse_args()

    print(f"Starting Anpanman metadata scrape (Sections {args.start_sec}-{args.end_sec})...")
    data = scrape_sections(args.start_sec, args.end_sec)
    print(f"Scraped {len(data)} total episode segments.")

    if args.dry_run:
        print("\n[Dry Run] Sample entries:")
        for k in list(data.keys())[:5]:
            print(f"  {k}: {data[k]}")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Saved metadata to {args.output}")


if __name__ == "__main__":
    main()
