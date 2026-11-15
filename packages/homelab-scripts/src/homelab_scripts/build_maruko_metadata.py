"""
Fetch Chibi Maruko-chan (1990) episode metadata from Wikipedia and generate maruko_metadata.json.
Scrapes all 142 episodes of Season 1 (1990-1992):
- Japanese Wikipedia for official Japanese segment titles and broadcast dates
- English Wikipedia for English translated titles and plot synopses
- pykakasi for clean Romaji transliterations
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

USER_AGENT = "HomelabMarukoScraper/1.0 (https://github.com/ehteshamz; personal homelab)"
WIKI_JA_API = "https://ja.wikipedia.org/w/api.php"
WIKI_EN_API = "https://en.wikipedia.org/w/api.php"


def create_kakasi_converter() -> pykakasi.kakasi:
    return pykakasi.kakasi()


def to_romaji(converter: pykakasi.kakasi, text: str) -> str:
    # Strip Japanese brackets
    text = text.replace("「", "").replace("」", "").strip()
    is_maki = text.endswith("の巻")
    if is_maki:
        text = text[:-2]

    # Pre-segment common names/words in Maruko
    text = text.replace("まるちゃん", "まるちゃん ")
    text = text.replace("まる子ちゃん", "まる子ちゃん ")
    text = text.replace("まる子", "まる子 ")
    text = text.replace("お母さん", "お母さん ")
    text = text.replace("お父さん", "お父さん ")
    text = text.replace("花輪君", "花輪君 ")
    text = text.replace("丸尾君", "丸尾君 ")

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
    s = re.sub(r"\bDe\b", "de", s)
    s = re.sub(r"\bWo\b", "o", s)

    if is_maki:
        s = f"{s} no Maki"
    return s.strip()


def scrape_japanese_wikipedia(delay: float = 1.0) -> dict[int, dict]:
    converter = create_kakasi_converter()
    ep_data: dict[int, dict] = {}
    headers = {"User-Agent": USER_AGENT}

    # Section 2: 1990 (Eps 1-52), Section 3: 1991 (Eps 53-103), Section 4: 1992 (Eps 104-142)
    sections = [(2, "1990"), (3, "1991"), (4, "1992")]

    for sec, year in sections:
        print(f"Fetching Japanese Wikipedia section {sec} ({year})...")
        params = {
            "action": "parse",
            "page": "ちびまる子ちゃんのエピソード一覧",
            "prop": "text",
            "section": str(sec),
            "format": "json",
        }

        try:
            resp = httpx.get(WIKI_JA_API, params=params, headers=headers, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            print(f"Error fetching JA section {sec}: {e}", file=sys.stderr)
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
                ep_data[current_ep] = {
                    "episode": current_ep,
                    "season": 1,
                    "air_date": air_date,
                    "titles_ja": [title],
                    "title_ja": title,
                    "title_ro": to_romaji(converter, title),
                }
            elif current_ep is not None and cells and cells[0].startswith("「"):
                sub_title = cells[0]
                ep_data[current_ep]["titles_ja"].append(sub_title)
                all_ja = "／".join(ep_data[current_ep]["titles_ja"])  # noqa: RUF001
                ep_data[current_ep]["title_ja"] = all_ja
                ep_data[current_ep]["title_ro"] = " / ".join(
                    to_romaji(converter, t) for t in ep_data[current_ep]["titles_ja"]
                )

        time.sleep(delay)

    return ep_data


def scrape_english_wikipedia(delay: float = 1.0) -> dict[int, dict]:
    en_data: dict[int, dict] = {}
    headers = {"User-Agent": USER_AGENT}

    # Section 2: 1990, Section 3: 1991, Section 4: 1992
    for sec_id in [2, 3, 4]:
        print(f"Fetching English Wikipedia section {sec_id}...")
        params = {
            "action": "parse",
            "page": "List_of_Chibi_Maruko-chan_episodes",
            "prop": "text",
            "section": str(sec_id),
            "format": "json",
        }

        try:
            resp = httpx.get(WIKI_EN_API, params=params, headers=headers, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            print(f"Error fetching EN section {sec_id}: {e}", file=sys.stderr)
            continue

        html = data.get("parse", {}).get("text", {}).get("*", "")
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.find_all("tr")

        current_ep: int | None = None
        for tr in rows:
            cells = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
            if not cells:
                continue

            if cells[0].isdigit():
                current_ep = int(cells[0])
                sum_td = tr.find("td", class_="summary")
                sum_text = sum_td.get_text(strip=True) if sum_td else (cells[1] if len(cells) > 1 else "")
                en_title = clean_en_title(sum_text)

                en_data[current_ep] = {
                    "titles_en": [en_title] if en_title else [],
                    "title_en": en_title,
                    "plot": "",
                }
            elif current_ep and (sum_td := tr.find("td", class_="summary")):
                sum_text = sum_td.get_text(strip=True)
                en_title = clean_en_title(sum_text)
                if en_title:
                    en_data[current_ep]["titles_en"].append(en_title)
                    en_data[current_ep]["title_en"] = " & ".join(en_data[current_ep]["titles_en"])
            elif current_ep and (desc_td := tr.find("td", class_="description")):
                desc = desc_td.get_text(strip=True)
                desc = re.sub(r"\[\d+\]", "", desc).strip()
                en_data[current_ep]["plot"] = desc

        time.sleep(delay)

    return en_data


def clean_en_title(text: str) -> str:
    # Format: "English Title"(Japanese:日本語)
    m = re.match(r'^"?(.*?)"?\s*(?:\(Japanese:.*?\))?$', text)
    if m:
        return m.group(1).strip().strip('"')
    return text.strip().strip('"')


def build_metadata() -> dict[str, dict]:
    ja_data = scrape_japanese_wikipedia(delay=1.0)
    en_data = scrape_english_wikipedia(delay=1.0)

    combined: dict[str, dict] = {}
    for ep_num in sorted(ja_data.keys()):
        ja = ja_data[ep_num]
        en = en_data.get(ep_num, {})

        title_en = en.get("title_en") or ja["title_ro"]
        plot = en.get("plot", "")

        combined[str(ep_num)] = {
            "episode": ep_num,
            "season": 1,
            "air_date": ja["air_date"],
            "title_en": title_en,
            "titles_en": en.get("titles_en", []),
            "title_ja": ja["title_ja"],
            "titles_ja": ja["titles_ja"],
            "title_ro": ja["title_ro"],
            "plot": plot,
        }

    return combined


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

    print("Building comprehensive Chibi Maruko-chan Season 1 metadata (142 episodes)...")
    data = build_metadata()
    print(f"Compiled metadata for {len(data)} total episodes.")

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
