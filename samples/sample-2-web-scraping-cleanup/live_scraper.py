#!/usr/bin/env python3
"""
Optional live scraper — the same cleaning logic pointed at a real public URL.

NOT needed to run the demo. `scrape_offline.py` is the demo entry point and works with
no network access at all.

This file exists to show the production-shaped parts of a scraper that the offline demo
deliberately leaves out:
  * a robots.txt check before any request
  * a descriptive User-Agent
  * a polite delay between requests
  * retry with backoff on transient failures
  * the same parse -> clean -> export pipeline

Scope and ethics (read before pointing this at a site):
  * Only scrape content that is publicly accessible without a login.
  * Respect robots.txt. If it disallows the path, this script refuses to run.
  * Do not attempt to bypass CAPTCHAs, paywalls, rate limits or any access control.
  * Prefer the site's official API when one exists -- it is faster, stabler and allowed.
  * Personal data: only collect what is public and business-relevant, and confirm with
    the site owner / your legal advisor that the intended use is appropriate.

Usage
-----
    pip install requests beautifulsoup4
    python live_scraper.py --url "https://example.com/public-listings" --delay 2

API keys are never needed here and none are stored in this repository.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("This optional script needs extra packages:  pip install requests beautifulsoup4")

USER_AGENT = "PortfolioDemoScraper/1.0 (+contact: replace-with-your-email@example.com)"

OUTPUT_FIELDS = [
    "product_name",
    "sku",
    "price",
    "list_price",
    "currency",
    "availability",
    "category",
    "rating",
    "review_count",
    "source_url",
]

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}


def robots_allows(url: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
    except Exception as exc:  # network error, missing file, etc.
        print(f"  ! Could not read {robots_url}: {exc}")
        print("  ! Refusing to continue. Check the site's robots.txt manually first.")
        return False
    if not parser.can_fetch(USER_AGENT, url):
        print(f"  ! robots.txt disallows fetching {url} for this user agent.")
        return False
    delay = parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*")
    print(f"  robots.txt OK (crawl delay: {delay if delay else 'not specified'})")
    return True


def fetch(url: str, timeout: int = 20, retries: int = 3) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.text
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            wait = 2 ** attempt
            print(f"  ! attempt {attempt}/{retries} failed ({exc}); retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Could not fetch {url}: {last_error}")


def parse_price(text: str) -> tuple[str, str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return "", ""
    currency = ""
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in text:
            currency = code
            text = text.replace(symbol, " ")
            break
    match = re.search(r"([\d][\d.,\s]*)\s*([A-Z]{3})", text)
    if match:
        currency = currency or match.group(2)
        text = match.group(1)
    if "," in text and "." not in text:
        tail = text.rsplit(",", 1)[1].strip()
        text = text.rsplit(",", 1)[0] + "." + tail if len(tail) in (1, 2) and tail.isdigit() else text.replace(",", "")
    number = re.sub(r"[^\d.]", "", text)
    return (f"{float(number):.2f}" if number else ""), currency


def parse_listing(html: str, base_url: str, selectors: dict) -> list[dict]:
    """Selectors are passed in so they can be tuned when the site changes."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for node in soup.select(selectors["item"]):
        def text_of(selector: str) -> str:
            found = node.select_one(selector)
            return found.get_text(" ", strip=True) if found else ""

        price, currency = parse_price(text_of(selectors.get("price", ".price")))
        list_price, list_currency = parse_price(text_of(selectors.get("list_price", ".was-price")))
        rows.append(
            {
                "product_name": text_of(selectors.get("title", ".product-title")),
                "sku": (node.get("data-sku") or text_of(selectors.get("sku", ".sku")) or "").upper(),
                "price": price,
                "list_price": list_price,
                "currency": currency or list_currency,
                "availability": re.sub(r"\s+", "_", text_of(selectors.get("availability", ".stock")).lower()),
                "category": text_of(selectors.get("category", ".category")),
                "rating": text_of(selectors.get("rating", ".rating")),
                "review_count": re.sub(r"\D", "", text_of(selectors.get("reviews", ".reviews"))),
                "source_url": urljoin(base_url, node.get("href", base_url)),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Optional live scraper. Use only on public, permitted pages.")
    parser.add_argument("--url", required=True, help="public listing page URL")
    parser.add_argument("--delay", type=float, default=2.0, help="seconds between requests")
    parser.add_argument("--output", default="output/live_products.csv")
    parser.add_argument("--max-pages", type=int, default=1)
    args = parser.parse_args()

    print(f"Checking robots.txt for {args.url}")
    if not robots_allows(args.url):
        print("Stopped. Use the official API instead, or pick a page that permits crawling.")
        return 2

    print("Fetching page")
    html = fetch(args.url)
    rows = parse_listing(
        html,
        args.url,
        {
            "item": ".product-card",
            "title": ".product-title",
            "price": ".price",
            "list_price": ".was-price",
            "availability": ".stock",
            "reviews": ".reviews",
        },
    )
    print(f"Parsed {len(rows)} records")

    print(f"Sleeping {args.delay}s before finishing (polite rate)")
    time.sleep(args.delay)

    with open(args.output, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {args.output}")
    print("Reminder: if the site updates its HTML, update the selectors in parse_listing().")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
