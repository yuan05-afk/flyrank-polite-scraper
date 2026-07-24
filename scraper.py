"""
The polite scraper — fetch -> parse -> extract -> clean -> structure.

Politeness layer (what separates a scraper from an abuser):
  * Reads and obeys robots.txt before fetching anything.
  * Identifies itself with an honest, contactable User-Agent.
  * Rate-limits every request (fixed delay) so it never hammers the host.
  * Retries transient errors with backoff, and gives up gracefully.

Target: https://quotes.toscrape.com — a sandbox built for scraping practice.
Output: data/quotes.json + data/quotes.csv — a clean, structured corpus
(the raw material for next week's RAG work).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://quotes.toscrape.com"
USER_AGENT = (
    "FlyRankPoliteScraper/1.0 "
    "(+https://github.com/yuan05-afk; educational; contact: intern@example.com)"
)
DEFAULT_DELAY = 1.0          # seconds between requests
MAX_RETRIES = 3
DATA_DIR = Path(__file__).resolve().parent / "data"


class RobotsGate:
    """Wraps robots.txt so we never fetch a path the site owner disallowed."""

    def __init__(self, base_url: str, user_agent: str) -> None:
        self.user_agent = user_agent
        robots_url = urljoin(base_url, "/robots.txt")
        self.parser = urllib.robotparser.RobotFileParser()
        self.parser.set_url(robots_url)
        try:
            self.parser.read()
            self.loaded = True
        except Exception:
            # If robots.txt can't be read, the safe default is to be conservative.
            self.loaded = False

    def allowed(self, url: str) -> bool:
        if not self.loaded:
            return False
        return self.parser.can_fetch(self.user_agent, url)


class PoliteSession:
    def __init__(self, delay: float, user_agent: str) -> None:
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self._last_request = 0.0

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    def get(self, url: str) -> requests.Response | None:
        for attempt in range(1, MAX_RETRIES + 1):
            self._throttle()
            try:
                resp = self.session.get(url, timeout=15)
                self._last_request = time.time()
                if resp.status_code == 200:
                    return resp
                if resp.status_code == 429:
                    wait = float(resp.headers.get("Retry-After", self.delay * 2))
                    print(f"  429 rate-limited, backing off {wait:.1f}s")
                    time.sleep(wait)
                    continue
                if 500 <= resp.status_code < 600:
                    backoff = self.delay * (2 ** (attempt - 1))
                    print(f"  {resp.status_code} server error, retry in {backoff:.1f}s")
                    time.sleep(backoff)
                    continue
                print(f"  {resp.status_code} for {url} — skipping")
                return None
            except requests.RequestException as exc:
                backoff = self.delay * (2 ** (attempt - 1))
                print(f"  network error ({exc}); retry {attempt}/{MAX_RETRIES} in {backoff:.1f}s")
                time.sleep(backoff)
        return None


def clean_text(text: str) -> str:
    """Normalize whitespace and curly quotes so records are model-ready."""
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_quotes(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for block in soup.select("div.quote"):
        text_el = block.select_one("span.text")
        author_el = block.select_one("small.author")
        tags = [clean_text(t.get_text()) for t in block.select("div.tags a.tag")]
        if not text_el or not author_el:
            continue
        raw = clean_text(text_el.get_text())
        records.append(
            {
                "text": raw.strip('"'),
                "author": clean_text(author_el.get_text()),
                "tags": tags,
                "length": len(raw.strip('"')),
            }
        )
    return records


def next_page_url(html: str, current_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    nxt = soup.select_one("li.next a")
    if nxt and nxt.get("href"):
        return urljoin(current_url, nxt["href"])
    return None


def scrape(max_pages: int, delay: float) -> list[dict]:
    gate = RobotsGate(BASE_URL, USER_AGENT)
    session = PoliteSession(delay=delay, user_agent=USER_AGENT)

    all_records: list[dict] = []
    url = urljoin(BASE_URL, "/")
    page = 0

    while url and page < max_pages:
        page += 1
        if not gate.allowed(url):
            print(f"robots.txt disallows {url} — stopping politely.")
            break

        print(f"[page {page}] GET {url}")
        resp = session.get(url)
        if resp is None:
            print("  giving up on this page")
            break

        records = extract_quotes(resp.text)
        print(f"  extracted {len(records)} quotes")
        all_records.extend(records)

        url = next_page_url(resp.text, url)

    return all_records


def deduplicate(records: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for r in records:
        key = (r["text"], r["author"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def save(records: list[dict]) -> None:
    DATA_DIR.mkdir(exist_ok=True)

    json_path = DATA_DIR / "quotes.json"
    json_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

    csv_path = DATA_DIR / "quotes.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "author", "tags", "length"])
        for r in records:
            writer.writerow([r["text"], r["author"], ";".join(r["tags"]), r["length"]])

    print(f"\nSaved {len(records)} records -> {json_path.name}, {csv_path.name}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Polite scraper for quotes.toscrape.com")
    ap.add_argument("--max-pages", type=int, default=10)
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    args = ap.parse_args()

    print(f"User-Agent: {USER_AGENT}")
    print(f"Rate limit: {args.delay}s between requests\n")

    records = scrape(max_pages=args.max_pages, delay=args.delay)
    records = deduplicate(records)

    authors = sorted({r["author"] for r in records})
    print(f"\nTotal unique quotes: {len(records)} from {len(authors)} authors")
    save(records)


if __name__ == "__main__":
    main()
