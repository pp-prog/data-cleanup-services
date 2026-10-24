#!/usr/bin/env python3
"""
Offline web-scraping demo — parse a saved public directory page into a clean CSV.

Sample project for portfolio purposes. Demo data only; no client data involved.

Why offline?
------------
The demo entry point (`scrape_offline.py`) reads a local copy of public listing pages
(`mock_pages/`) so that anyone can run it in seconds, with no network access, no rate
limits and no risk of hitting a live site. The parsing / cleaning / export logic is
exactly the logic a live scraper would use.

`live_scraper.py` shows the same logic against a real URL (requests + robots.txt check +
polite delay). It is optional and NOT required to run the demo.

What the demo does
------------------
1. Parses product cards out of a messy HTML page (prices with symbols, "was" prices,
   missing currency, HTML entities, whitespace, stock flags).
2. Applies a field-mapping table: raw label -> clean column name.
3. Normalises price, currency, availability, rating and SKU.
4. De-duplicates by SKU (the same product appears twice in the mock feed).
5. Writes a clean CSV + a field-mapping report.

Usage
-----
    python scrape_offline.py
    python scrape_offline.py --pages mock_pages --output output --limit 100

Dependencies: none beyond the Python standard library (no pip install needed).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

# --------------------------------------------------------------------------
# Field mapping: raw HTML label -> clean CSV column
# --------------------------------------------------------------------------
FIELD_MAPPING = {
    "title": "product_name",
    "price": "price",
    "was_price": "list_price",
    "currency": "currency",
    "sku": "sku",
    "availability": "availability",
    "category": "category",
    "rating": "rating",
    "reviews": "review_count",
}

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}

AVAILABILITY_MAP = {
    "in stock": "in_stock",
    "instock": "in_stock",
    "available": "in_stock",
    "out of stock": "out_of_stock",
    "outofstock": "out_of_stock",
    "pre-order": "preorder",
    "preorder": "preorder",
    "backorder": "backorder",
}

TEXT_CLASS_MAP = {
    "product-title": "title",
    "product_title": "title",
    "price": "price",
    "was-price": "was_price",
    "sale-price": "price",
    "stock": "availability",
    "availability": "availability",
    "reviews": "reviews",
}

# Fills in every key clean_record() expects, even when the page omits a field.
RAW_FIELDS = ["title", "price", "was_price", "currency", "sku", "availability", "category", "rating", "reviews"]


# --------------------------------------------------------------------------
# HTML parsing
# --------------------------------------------------------------------------
class ProductCardParser(HTMLParser):
    """Collects one raw field dict per .product-card element."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict] = []
        self._card: dict | None = None
        self._card_depth = 0
        self._capture_field: str | None = None
        self._capture_depth = 0
        self._buffer: list[str] = []

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _classes(attrs: dict) -> list[str]:
        return (attrs.get("class") or "").split()

    # -- HTMLParser API --------------------------------------------------
    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = self._classes(attributes)

        if self._card is None:
            if "product-card" in classes:
                self._card = {field: "" for field in RAW_FIELDS}
                self._card["sku"] = attributes.get("data-sku", "").strip()
                self._card["currency"] = attributes.get("data-currency", "").strip()
                self._card["category"] = attributes.get("data-category", "").strip()
                self._card["rating"] = attributes.get("data-rating", "").strip()
                self._card_depth = 1
            return

        self._card_depth += 1

        # rating may live on a child element as data-rating
        if "data-rating" in attributes and not self._card.get("rating"):
            self._card["rating"] = attributes.get("data-rating", "").strip()

        for class_name in classes:
            if class_name in TEXT_CLASS_MAP:
                self._capture_field = TEXT_CLASS_MAP[class_name]
                self._capture_depth = self._card_depth
                self._buffer = []
                break

    def handle_endtag(self, tag):
        if self._card is None:
            return
        if self._capture_field and self._card_depth == self._capture_depth:
            text = re.sub(r"\s+", " ", "".join(self._buffer)).strip()
            if text and not self._card.get(self._capture_field):
                self._card[self._capture_field] = text
            self._capture_field = None
            self._buffer = []
        self._card_depth -= 1
        if self._card_depth == 0:
            if self._card.get("title"):
                self.cards.append(self._card)
            self._card = None

    def handle_data(self, data):
        if self._capture_field:
            self._buffer.append(data)


def parse_price(raw: str) -> tuple[str, str]:
    """'$1,299.00' -> ('1299.00', 'USD'); '1299.00 USD' -> ('1299.00', 'USD')."""
    raw = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not raw:
        return "", ""
    currency = ""
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in raw:
            currency = code
            raw = raw.replace(symbol, " ")
            break
    match = re.search(r"([\d][\d,\s]*\.?\d*)\s*([A-Z]{3})", raw)
    if match:
        currency = currency or match.group(2)
        raw = match.group(1)
    # European decimal comma: "19,90" -> 19.90 ; "1,299.00" -> 1299.00
    if "," in raw and "." not in raw:
        tail = raw.rsplit(",", 1)[1].strip()
        if len(tail) in (1, 2) and tail.isdigit():
            raw = raw.rsplit(",", 1)[0] + "." + tail
        else:
            raw = raw.replace(",", "")
    number = re.sub(r"[^\d.]", "", raw)
    if not number:
        return "", currency
    return f"{float(number):.2f}", currency


def clean_record(raw: dict) -> dict:
    raw = {field: ("" if raw.get(field) is None else str(raw.get(field, ""))) for field in RAW_FIELDS}
    price, currency = parse_price(raw["price"])
    list_price, list_currency = parse_price(raw["was_price"])
    if not currency:
        currency = list_currency
    if not currency:
        currency = raw["currency"].strip().upper()
    availability_raw = re.sub(r"\s+", " ", raw["availability"].lower().replace("•", " ")).strip()
    availability = AVAILABILITY_MAP.get(availability_raw, availability_raw.replace(" ", "_") or "unknown")
    try:
        rating = f"{float(raw['rating']):.1f}"
    except (TypeError, ValueError):
        rating = ""
    return {
        "product_name": re.sub(r"\s+", " ", raw["title"]).strip(),
        "sku": raw["sku"].strip().upper(),
        "price": price,
        "list_price": list_price,
        "currency": currency,
        "availability": availability,
        "category": raw["category"].strip().lower(),
        "rating": rating,
        "review_count": re.sub(r"\D", "", raw["reviews"]),
    }


def parse_page(page_html: str, source_name: str) -> list[dict]:
    parser = ProductCardParser()
    parser.feed(page_html)
    records = []
    for raw in parser.cards:
        record = clean_record(raw)
        record["source_page"] = source_name
        records.append(record)
    return records


# --------------------------------------------------------------------------
# JSON listing shape (some public pages expose their data as embedded JSON)
# --------------------------------------------------------------------------
JSON_KEY_ALIASES = {
    "name": "title",
    "product_name": "title",
    "productName": "title",
    "price": "price",
    "sale_price": "price",
    "list_price": "was_price",
    "was_price": "was_price",
    "curr": "currency",
    "currency_code": "currency",
    "identifier": "sku",
    "stock_status": "availability",
    "category_name": "category",
    "stars": "rating",
    "review_count": "reviews",
}


def parse_json_page(payload: str, source_name: str) -> list[dict]:
    data = json.loads(payload)
    items = data.get("items", data) if isinstance(data, dict) else data
    records = []
    for item in items:
        raw = {field: "" for field in RAW_FIELDS}
        for key, value in item.items():
            canonical = JSON_KEY_ALIASES.get(key)
            if canonical:
                raw[canonical] = value
        if not raw["title"]:
            continue
        record = clean_record(raw)
        record["source_page"] = source_name
        records.append(record)
    return records


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Offline demo: HTML/JSON listing page -> clean CSV.")
    parser.add_argument("--pages", default="mock_pages", help="folder with saved pages")
    parser.add_argument("--output", default="output", help="output folder")
    parser.add_argument("--limit", type=int, default=0, help="max records to export (0 = all)")
    args = parser.parse_args()

    started = time.perf_counter()
    pages_dir = Path(args.pages)
    output_dir = Path(args.output)
    if not pages_dir.exists():
        sys.exit(f"Pages folder not found: {pages_dir}")

    print(f"[1/4] Reading saved pages from {pages_dir}")
    html_pages, json_pages = [], []
    for path in sorted(pages_dir.iterdir()):
        if path.suffix.lower() in (".html", ".htm"):
            html_pages.append((path.name, path.read_text(encoding="utf-8")))
        elif path.suffix.lower() == ".json":
            json_pages.append((path.name, path.read_text(encoding="utf-8")))
    if not html_pages and not json_pages:
        sys.exit("No .html or .json files found.")
    for name, _ in html_pages + json_pages:
        print(f"      - {name}")

    print("[2/4] Parsing and cleaning records")
    records: list[dict] = []
    for name, html_text in html_pages:
        page_records = parse_page(html_text, name)
        print(f"      - {name}: {len(page_records)} cards parsed")
        records.extend(page_records)
    for name, payload in json_pages:
        page_records = parse_json_page(payload, name)
        print(f"      - {name}: {len(page_records)} JSON items parsed")
        records.extend(page_records)

    print("[3/4] De-duplicating by SKU")
    seen: dict[str, dict] = {}
    duplicates = 0
    for record in records:
        key = record["sku"] or record["product_name"].lower()
        if key in seen:
            duplicates += 1
            continue
        seen[key] = record
    unique = list(seen.values())
    if args.limit:
        unique = unique[: args.limit]

    print("[4/4] Writing clean CSV")
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "products_clean.csv"
    fieldnames = list(FIELD_MAPPING.values()) + ["source_page"]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unique)

    mapping_path = output_dir / "field_mapping.json"
    mapping_path.write_text(
        json.dumps(
            {
                "raw_label_to_column": FIELD_MAPPING,
                "availability_normalisation": AVAILABILITY_MAP,
                "price_rule": "strip currency symbols and thousands separators -> 2dp decimal",
                "dedupe_key": "sku (fallback: lowercased product name)",
                "source_pages": [name for name, _ in html_pages + json_pages],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    elapsed = time.perf_counter() - started
    print(f"      records parsed: {len(records)}  |  duplicates removed: {duplicates}  |  rows exported: {len(unique)}")
    print(f"      wrote {csv_path}")
    print(f"      wrote {mapping_path}")
    print(f"      finished in {elapsed:.3f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
