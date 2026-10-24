# Sample Project — Web Scraping & Data Cleaning (offline-runnable demo)

> **Sample project — demo data, no client involved.**
> The pages in `mock_pages/` are fictional snapshots I wrote myself. No real website was
> scraped to produce this sample, no client data is shown, and no client results are
> claimed.

**What it does:** takes a saved public product-listing page (HTML or embedded JSON) and
produces a clean, de-duplicated CSV with normalised prices, currencies, availability and
SKUs — plus a machine-readable field-mapping report.

---

## 1. The problem

Public listing pages are almost never structured for reuse. A single "office supplies"
category page typically contains:

- prices as `$24.99`, `€19,90`, `£4.20`, `¥480`, `24.50 EUR`, `1299.00 USD` — six
  different conventions, sometimes on the same page;
- a "was" price next to the current price that is easy to mistake for the real one;
- stock state written as `In stock`, `Out of stock`, `Pre-order`, sometimes with a
  bullet character in front;
- review counts written as `(1,032 reviews)`;
- HTML entities (`&mdash;`) and stray whitespace inside names;
- the same SKU listed twice in the feed;
- and, on many sites, a second copy of the same data as embedded JSON that the HTML
  only hints at.

Copying that into a spreadsheet by hand means: one paste per product, a price parser in
your head, and a duplicate-check pass afterwards. On a 300-item category that is easily
an hour, and the error rate climbs with volume.

## 2. The approach

### Why the demo runs offline

`scrape_offline.py` reads **local copies** of listing pages from `mock_pages/`. That
means:

- it runs in about **2 milliseconds** with no network access at all;
- a reviewer can run it without an internet connection, an API key, or a target site;
- it never touches a live website, so it cannot break, get rate-limited, or violate
  anyone's terms while someone is evaluating it.

The parsing, cleaning and export logic is exactly the logic a live scraper would use —
only the fetch step differs. `live_scraper.py` shows the production-shaped fetch step
(robots.txt check, descriptive User-Agent, polite delay, retry with backoff) and is
**optional**.

### The pipeline

```
mock_pages/*.html , mock_pages/*.json
        │
        ▼
  [1] PARSE
        HTML  → html.parser walks the DOM, one record per .product-card element
        JSON  → alias map (name/product_name/productName → title, …)
        │
        ▼
  [2] MAP      raw label → clean column (FIELD_MAPPING table)
        │
        ▼
  [3] CLEAN
        price     "$24.99" / "19,90 €" / "24.50 EUR" → 24.99 / 19.90 / 24.50 + currency
        currency  symbol or code → ISO (USD, EUR, GBP, JPY)
        stock     "In stock" → in_stock, "Pre-order" → preorder, …
        rating    → 1-decimal string, blanks stay blank
        sku       → upper-cased
        name      → whitespace collapsed, entities decoded
        │
        ▼
  [4] DE-DUPE by SKU (fallback: lowercased product name)
        │
        ▼
  [5] EXPORT   output/products_clean.csv + output/field_mapping.json
```

### Field mapping

This is the part that matters most in a real scraping job — the mapping between what the
page says and what your sheet needs. It is written down in `FIELD_MAPPING` in the code
and dumped to `output/field_mapping.json` on every run so it can be reviewed and
diffed.

| Raw label on page | Clean column | Rule applied |
|---|---|---|
| `.product-title` text | `product_name` | entities decoded, whitespace collapsed |
| `.price` text | `price` | currency symbol stripped, 2-dp decimal, EU comma handled |
| `.was-price` text | `list_price` | same, kept in a separate column |
| `data-currency` | `currency` | ISO code; symbol used if the attribute is missing |
| `data-sku` | `sku` | upper-cased |
| `.stock` text | `availability` | mapped to `in_stock` / `out_of_stock` / `preorder` / `backorder` |
| `data-category` | `category` | lower-cased |
| `data-rating` | `rating` | 1 decimal |
| `.reviews` text | `review_count` | digits only → `214`, `1032` |
| — | `source_page` | which saved page the row came from |

### Compliance stance (built into the code, not just the README)

This is a demo of a *permitted* scrape, and the code enforces that stance:

1. **robots.txt is checked before the first request.** `live_scraper.py` uses
   `urllib.robotparser` and **refuses to run** if the path is disallowed for our user
   agent, or if robots.txt cannot be read at all.
2. **Only publicly accessible pages.** The scraper has no login handling, no cookie
   injection and no paywall bypass, because there is nothing in it that could defeat
   one.
3. **Polite rate.** A configurable delay (default 2 s) between requests, and the
   crawl delay from robots.txt is honoured when the site specifies one.
4. **No access-control circumvention.** No CAPTCHA solving, no header spoofing to hide
   the user agent, no IP rotation. If a site blocks us, the answer is the official API,
   not a workaround.
5. **Descriptive User-Agent** with a contact address, so a site owner can reach me
   instead of guessing who is crawling them.
6. **Data minimisation.** Only business-relevant public fields are collected; no
   personal data beyond what a public listing page already shows, and no copyrighted
   content is copied at scale.

If a target site forbids scraping or offers an official API, I recommend the API route
— it is faster, more stable and explicitly allowed. That is what I tell clients too.

## 3. The result

Actual console output from running the demo:

```
[1/4] Reading saved pages from mock_pages
      - page1_office_supplies.html
      - page2_listing_api.json
[2/4] Parsing and cleaning records
      - page1_office_supplies.html: 13 cards parsed
      - page2_listing_api.json: 5 JSON items parsed
[3/4] De-duplicating by SKU
[4/4] Writing clean CSV
      records parsed: 18  |  duplicates removed: 2  |  rows exported: 16
      wrote output\products_clean.csv
      wrote output\field_mapping.json
      finished in 0.002 s
```

And `output/products_clean.csv` (16 rows; first 6 shown):

```
product_name,price,list_price,currency,sku,availability,category,rating,review_count,source_page
Heavy Duty Stapler 65mm,24.99,32.50,USD,DM-1001,in_stock,office supplies,4.6,214,page1_office_supplies.html
A4 Copy Paper — 500 Sheets,6.49,,USD,DM-1002,in_stock,office supplies,4.8,1032,page1_office_supplies.html
Gel Pens Black (Pack of 12),8.99,11.00,USD,DM-1003,out_of_stock,office supplies,4.1,88,page1_office_supplies.html
Ergonomic Mouse,19.90,,EUR,DM-1004,in_stock,office supplies,4.4,57,page1_office_supplies.html
Desk Lamp LED,24.50,,EUR,DM-1005,preorder,office supplies,3.9,12,page1_office_supplies.html
Ring Binder A4 75mm,4.20,5.95,GBP,DM-1007,in_stock,office supplies,4.5,41,page1_office_supplies.html
```

**What the cleaning actually fixed on this data set:**

| Raw value on page | Clean output | Why it needed handling |
|---|---|---|
| `$24.99` | `24.99` + `USD` | symbol → separate currency column |
| `€19,90` | `19.90` + `EUR` | European decimal comma |
| `24.50 EUR` | `24.50` + `EUR` | code suffix instead of symbol |
| `£4.20` / `¥480` | `4.20` / `480.00` + `GBP` / `JPY` | symbol + 2-dp standardisation |
| `$32.50` (was-price) | `32.50` in `list_price` | must not overwrite the current price |
| `In stock` / `Out of stock` / `Pre-order` | `in_stock` / `out_of_stock` / `preorder` | inconsistent label → fixed vocabulary |
| `(1,032 reviews)` | `1032` | digits only |
| `A4 Copy Paper &mdash; 500 Sheets` | `A4 Copy Paper — 500 Sheets` | HTML entity decoded |
| `DM-1006` listed twice | one row | de-duplicated by SKU |
| `dm-1001` / `dm-2002` | `DM-1001` / `DM-2002` | SKU upper-cased for joining |

**Measured result on the demo data set:**

| Metric | Value |
|---|---|
| Source pages | 2 (1 HTML + 1 JSON listing) |
| Records parsed | 18 |
| Duplicates removed | 2 |
| Rows exported | 16 |
| Runtime | **0.002 s** (offline, standard library only) |

## 4. How to run it

### Requirements

- Python 3.9+
- **No third-party packages required** for the demo — standard library only.

### Run the offline demo

```bash
cd sample-2-web-scraping-cleanup
python scrape_offline.py
```

Output lands in `output/`:

- `output/products_clean.csv` — the clean, de-duplicated product table
- `output/field_mapping.json` — the field mapping and normalisation rules used

### Options

```bash
python scrape_offline.py --pages mock_pages --output output --limit 100
```

### Optional: the live scraper

```bash
pip install requests beautifulsoup4
python live_scraper.py --url "https://example.com/public-listings" --delay 2
```

It checks robots.txt first and exits with code 2 if the path is disallowed. Only point
it at pages you are permitted to collect.

### Files in this sample

```
sample-2-web-scraping-cleanup/
├── README.md
├── scrape_offline.py                  # demo entry point (offline, stdlib only)
├── live_scraper.py                    # optional live scraper (robots + delay + retry)
├── mock_pages/
│   ├── page1_office_supplies.html      # fictional saved HTML listing
│   └── page2_listing_api.json         # fictional saved JSON listing
└── output/
    ├── products_clean.csv              # the result
    └── field_mapping.json             # field mapping report
```

## 5. Extending it to a real site

The honest way to describe scraping work: **the parsing is the easy part and the
maintenance is the cost.** A scraper breaks whenever a site changes its HTML. So a real
delivery includes:

1. **Selector centralisation** — one `SELECTORS` dict per page template, so a change is
   a one-line fix, not a code hunt.
2. **A change log** — a note of which selectors map to which part of the page, and what
   breaks when the site re-designs.
3. **Retry with backoff and structured logs** — so a 500 at 2 a.m. is visible rather than
   silently dropped.
4. **Pagination handling** — "next page" links and query-parameter pages, with a cap on
   pages so a bad loop cannot run away.
5. **A re-run check** — compare record counts against the previous run and alert on a
   large drop, which is the usual symptom of a broken selector.
6. **Scheduling** — cron, Windows Task Scheduler, or a GitHub Actions schedule.

Ongoing maintenance after a site change is quoted separately. I do not promise a
scraper will keep working forever, because no honest scraper can.

---

*Sample project. Fictional demo pages, no real site scraped, no client involved.*
