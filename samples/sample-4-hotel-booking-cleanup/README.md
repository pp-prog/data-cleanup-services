# Sample Project — Messy Hotel Booking Sheets → One Clean Bookings Table (Python)

> **Sample project — demo data, no client involved.**
> This is a self-built demonstration built for my Upwork portfolio. The workbook, the
> hotel, the guest names and the amounts are fictional and were generated on purpose
> (see `make_xlsx_input.py`) to exercise the script. No client work, no client data and
> no client results are shown here.

**What it does:** turns a workbook of 48 monthly booking sheets — each one laid out
differently, in a mix of Turkish and English, with dates written in six different
formats and prices typed in six different ways — into **one clean table of 833 verified
bookings**, plus **571 rows flagged for human review** instead of silently guessed.

---

## 1. The problem

The source workbook (`input/hotel_bookings_2023_2026.xlsx`) contains **49 sheets**: 48
monthly booking sheets (2023 Ocak … 2026 Aralık) and one `Notlar` (notes) sheet that
holds no bookings.

Every month was typed by a different person, and it shows:

| What varies | Examples in the source |
|---|---|
| Header layout | `Rezervasyon No / Ad Soyad / Giriş / Çıkış / Fiyat / Not` vs `Booking ID / Name / Check-in / Check-out / Price / Notes` vs `no / ad_soyad / giris_tarihi / cikis_tarihi / ucret / not` — and two layouts where the columns are in a **different order**, plus one with **separate first/last name columns** and an extra `Oda Tipi` column |
| Title row | Some sheets have a merged title row (`OTEL REZERVASYON KAYITLARI - 2023 Ocak`) above the header |
| Date format | `31.01.2023`, `2023-01-31`, `01/31/2023` (month-first), `31/01/2023` (day-first), `31 Ocak 2023`, `31-01-2023` |
| Date order | Mostly day-first (Turkish habit), but a few sheets are month-first — **per sheet**, not per file |
| Price format | `120`, `120 USD`, `$120`, `-$120`, `1,200.00`, `3 gecelik` (the *number of nights* typed where the amount belongs), and blank |
| Names | `ayşe`, `MEHMET`, `Ahmet ` (trailing space), `fatma  ` (double space), `İbrahim`, `ÇELİK`, `ÖZTÜRK`, `YiLMAZ` |
| Junk rows | Hand-typed `TOPLAM` total rows, fully blank rows, and accidental duplicates of an earlier row |
| Real problems | Check-in/check-out pairs typed **reversed**, missing check-out dates, and prices that don't match the number of nights |

Doing this by hand means opening 48 sheets, guessing which of `03/04/2024` is March 4th
or April 3rd, retyping every price, and then hoping you didn't silently turn a
$120/night booking into a $12 booking.

## 2. The business rule that makes it solvable

> **The room rate is a flat 40 USD per night, so a correct price = nights × 40.**

This one rule does most of the work. When two dates are ambiguous (`03/04/2024` could be
either order), the price tells you which one is right: `price / 40` gives the implied
number of nights, and exactly one of the two readings produces that many nights.

That's why the script never has to *guess* a date order — it can *derive* it, and when
it can't, it says so.

## 3. How the date-order decision is made

Three tiers, strongest evidence first:

1. **Unambiguous on its own** — `2024-05-03`, `5 Mart 2024`. Nothing to decide.
2. **The business rule** — both readings are valid dates, but only one of them matches
   `price / 40`. Used only when the price is present and gives a whole number of nights.
3. **The sheet-level vote** — if a whole sheet is consistently day-first or month-first
   (detected from the rows that *are* unambiguous), that order is used as a tie-breaker.

**If none of the three resolves it, the row is flagged — never guessed.** 62 rows are
flagged for exactly this reason.

## 4. What comes out

`output/hotel_bookings_clean.xlsx`, four sheets:

| Sheet | Contents |
|---|---|
| `clean` | 833 verified bookings: `booking_number, first_name, last_name, check_in, check_out, nights, price_usd, notes` |
| `needs_review` | 571 flagged rows with `source_sheet, excel_row, booking_no, reason` — enough to find the cell in the original file and fix it |
| `summary_monthly` | Bookings and revenue per month |
| `summary_yearly` | Bookings and revenue per year |

Plus `output/needs_review.csv` for quick inspection outside Excel.

**The headline numbers (all asserted by `verify_output.py`, not typed by hand):**

| Metric | Value |
|---|---|
| Sheets in the source workbook | 49 (48 monthly + 1 notes sheet) |
| Booking rows kept | 833 (844 found, 11 duplicates removed) |
| Rows flagged for review | 571 |
| Revenue 2023 / 2024 / 2025 / 2026 | $27,480 / $29,480 / $29,280 / $28,320 |
| Rows carrying a note | 33 (the other 800 rows had no note in the source) |

**Why the flagged rows are a feature, not a failure:** a 571-row review list is honest
about what a human still has to decide; 1,404 confident-looking rows with 200 quietly
wrong dates is not. The rule in this script is simple — *if the data contradicts itself,
it gets flagged, it does not get guessed.*

Top reasons flagged:

| Count | Reason |
|---|---|
| 263 | price missing or not a number (includes prices typed as `3 gecelik`, i.e. nights instead of an amount) |
| 210 | price ≠ nights × 40 |
| 62 | ambiguous day-first/month-first — not resolvable |
| 36 | check-out missing |

## 5. Names: Turkish-aware casing

Source names arrive as `MEHMET`, `ÇELİK`, `ÖZTÜRK`, `YiLMAZ`, `ayşe`, `İbrahim`. The
script normalises them with **Turkish casing rules** (`i → İ`, `I → ı`, `İ → i`) and NFC
normalisation, so the output is `Mehmet`, `Çelik`, `Öztürk`, `Yılmaz`, `Ayşe`, `İbrahim`.

This is deliberately not Python's `str.title()`: `str.title()` is not Turkish-aware and
produces `Çeli̇k` — with a stray combining dot — while `"YILMAZ".title()` gives `Yilmaz`.
The verification check therefore states the property directly (NFC-normalised, first
letter of each word capitalised, rest lower-case) instead of comparing to `str.title()`,
so it can fail on a genuinely bad name rather than on a good Turkish one.

## 6. Verification — `verify_output.py`

A demo that only *looks* right is worthless, so every claim above is asserted by a
script rather than claimed in prose. It re-opens the output workbook and checks 17
things, including:

- the clean sheet has exactly the 8 expected columns, and **no empty cell in any of the
  7 required columns** (`notes` is optional — a blank note means the source row had none);
- **every** clean row satisfies `price = nights × 40` — 0 violations;
- every clean row has `check_out > check_in`; every date is a real datetime;
- nights are whole numbers in 1–30; prices are positive;
- no duplicate bookings remain;
- every name is canonical Turkish title case (NFC, capitalised first letter, lower-case
  rest) — 0 offenders;
- no hand-typed `TOPLAM` total row survived into the clean sheet;
- the monthly and yearly summaries cover every booking, and the yearly revenue equals
  the sum of the clean rows;
- every flagged row names its source sheet and its reason, and **no flagged row leaked
  into the clean table**.

Current status: **17/17 PASS — 833 clean rows, 571 flagged for review.**

## 7. How to run it

```bash
python make_xlsx_input.py     # regenerate the messy workbook (deterministic: seed 20261023)
python clean_bookings.py      # clean it -> output/hotel_bookings_clean.xlsx + needs_review.csv
python verify_output.py       # assert all 17 claims -> exit code 0 only if everything passes
```

Requirements: `pandas`, `openpyxl`.

## 8. Files

```
sample-4-hotel-booking-cleanup/
├── make_xlsx_input.py        # generates the messy 49-sheet workbook (seeded, reproducible)
├── clean_bookings.py         # the cleaner: parsing, date-order resolution, flagging
├── verify_output.py          # 17 assertions over the produced output
├── input/
│   └── hotel_bookings_2023_2026.xlsx
└── output/
    ├── hotel_bookings_clean.xlsx    # clean + needs_review + summary_monthly + summary_yearly
    └── needs_review.csv
```

## 9. Honest notes

- This is **my own sample project**. There is no client behind it and no client results
  are shown. The workbook is generated by `make_xlsx_input.py` with a fixed seed, so the
  same messy input produces the same numbers every run.
- The dates, names, amounts and the `TOPLAM`/`gecelik` quirks are all synthetic.
- `notes` is blank for 800 of the 833 rows because those source rows had no note —
  not because anything was lost.
- The 571 flagged rows are deliberately left in the workbook. Removing them would make
  the output look tidier and less trustworthy.

---

*Built as a portfolio sample. Recorded demo: `chenchen/portfolio/demos/demo-4-hotel-booking-cleanup.mp4` (31 s).*


