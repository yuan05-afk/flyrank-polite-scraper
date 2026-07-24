# The Polite Scraper

Collects pages from a practice site, extracts and cleans the useful fields, and saves **structured records** — while behaving like a bot the site owner would actually allow.

Target: [`quotes.toscrape.com`](https://quotes.toscrape.com) (a sandbox built for scraping practice).
Output: `data/quotes.json` + `data/quotes.csv` — a clean corpus, ready to become next week's RAG source.

## The pipeline

```
fetch  ->  parse  ->  extract  ->  clean  ->  structure
```

- **fetch** — one `requests` session, rate-limited
- **parse** — BeautifulSoup over the HTML
- **extract** — quote text, author, tags per `div.quote`
- **clean** — normalize whitespace, straighten curly quotes, strip wrapping `"`
- **structure** — one record per quote → JSON + CSV, de-duplicated

## The politeness layer (the actual lesson)

A scraper and an abuser run the same requests — the difference is manners:

| Behaviour | How |
|-----------|-----|
| **Obey robots.txt** | Reads `/robots.txt` and calls `can_fetch()` before every URL; stops if disallowed. |
| **Identify yourself** | Honest, contactable `User-Agent` (name + URL + contact), never a fake browser string. |
| **Rate limit** | Fixed delay between requests so the host is never hammered. |
| **Back off** | Honors `429 Retry-After`; retries `5xx`/network errors with exponential backoff, then gives up. |

## Run

```bash
pip install -r requirements.txt
python scraper.py --max-pages 10 --delay 1.0
```

Flags: `--max-pages` (stop after N pages), `--delay` (seconds between requests — be generous).

## Result

```
Total unique quotes: 100 from 50 authors
Saved 100 records -> quotes.json, quotes.csv
```

Sample record:

```json
{
  "text": "It is our choices, Harry, that show what we truly are, far more than our abilities.",
  "author": "J.K. Rowling",
  "tags": ["abilities", "choices"],
  "length": 82
}
```

## Why this matters

Most "AI applications" are really data-gathering applications with a model attached — and the gathering is the part nobody teaches. A clean, well-structured corpus gathered *politely* is what makes the next step (retrieval, RAG) easy and keeps you welcome on the sites you depend on.

## License

MIT — FlyRank Backend internship.
