#!/usr/bin/env python3
"""
clean_bookings.py — turn 48 messy monthly sheets into one reliable bookings table.

Business rule from the brief: the room rate is a flat 40 USD per night, so a
correct price = nights * 40. When price and dates disagree we DO NOT silently
pick one - the row is flagged for review.

Date order (day-first vs month-first) is resolved on two levels:

  1. SHEET LEVEL. If any date in the sheet has a first component > 12 the
     sheet is day-first (DMY); if any has a second component > 12 it is
     month-first (MDY). Formats like 2024-05-03 or "5 Mart 2024" are
     unambiguous on their own and never go through this.

  2. ROW LEVEL. For the rows that stay ambiguous (both components <= 12) we
     use the business rule as a second opinion: price / 40 gives the implied
     number of nights. Exactly one interpretation of the two dates yields that
     many nights, so that interpretation is the right one. If both or neither
     fit, the row is flagged as "ambiguous date order" instead of being
     guessed.

Run:  python clean_bookings.py
Out:  output/hotel_bookings_clean.xlsx
      output/needs_review.csv
"""
from __future__ import annotations

import os
import re
import unicodedata
from datetime import date, datetime

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "input", "hotel_bookings_2023_2026.xlsx")
OUT_XLSX = os.path.join(HERE, "output", "hotel_bookings_clean.xlsx")
OUT_REVIEW = os.path.join(HERE, "output", "needs_review.csv")

ROOM_RATE = 40.0
TOTAL_WORDS = {"toplam", "toplam:", "total", "genel toplam", "genel toplam:", "ara toplam"}

FIELD_HINTS = {
    "booking_no": ["rezervasyon", "booking", "kod", "no", "id"],
    "name": ["ad", "ad soyad", "name", "müşteri", "musteri", "guest"],
    "last_name": ["soyad", "surname", "last name", "lastname", "family"],
    "check_in": ["giris", "giriş", "check in", "checkin", "check-in", "arrival"],
    "check_out": ["cikis", "çıkış", "check out", "checkout", "check-out", "departure"],
    "price": ["fiyat", "price", "ucret", "ücret", "tutar", "amount"],
    "note": ["not", "note", "açıklama", "aciklama"],
}

MONTHS_TR = {
    "ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5,
    "haziran": 6, "temmuz": 7, "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9,
    "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
}


# ---------------------------------------------------------------- helpers

_TR_UPPER = {"i": "İ", "ı": "I"}
_TR_LOWER = {"I": "ı", "İ": "i"}


def _tr_upper(ch: str) -> str:
    return _TR_UPPER.get(ch, ch.upper())


def _tr_lower(ch: str) -> str:
    return _TR_LOWER.get(ch, ch.lower())


def turkish_title(s: str) -> str:
    """Title case with Turkish casing rules.

    First letter of every word is capitalised (i -> İ, ı -> I); the rest of the
    word is lower-cased (I -> ı, İ -> i). The result is NFC normalised, so the
    decomposed "Çeli̇k" from a lower-cased "ÇELİK" comes back as "Çelik"
    instead of keeping a stray combining dot.

    The previous version only touched the first letter and left the tail of the
    word alone, which is why ALL CAPS source names (MEHMET, ÇELİK, ÖZTÜRK) and
    mixed-case ones (YiLMAZ) survived into the clean sheet.
    """
    s = unicodedata.normalize("NFC", str(s))
    out = []
    for part in s.split(" "):
        if not part:
            out.append("")
            continue
        chars = []
        cap_next = True
        for ch in part:
            if ch == "-":
                chars.append(ch)
                cap_next = True
                continue
            if cap_next:
                chars.append(_tr_upper(ch))
                cap_next = False
            else:
                chars.append(_tr_lower(ch))
        out.append("".join(chars))
    return unicodedata.normalize("NFC", " ".join(out))


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def norm_header(s: str) -> str:
    s = str(s).strip().lower()
    s = strip_accents(s).replace("ı", "i").replace("ş", "s").replace("ğ", "g")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


def guess_field(header: str) -> str | None:
    h = norm_header(header)
    if not h:
        return None
    if "not" in h.split() or "aciklama" in h.split():
        return "note"
    for field, hints in FIELD_HINTS.items():
        for hint in hints:
            if re.search(rf"\b{re.escape(hint)}\b", h):
                return field
    return None


def to_number(value) -> float | None:
    """Parse a money cell. Returns None when the cell is not a plain amount."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    neg = s.startswith("-")
    s = s.lstrip("-")
    for token in ("USD", "usd", "TL", "tl", "$", "₺", "€", "£"):
        s = s.replace(token, "")
    s = s.strip()
    if re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]", s):
        return None                      # e.g. "5 gecelik" - not an amount
    if re.match(r"^\d{1,3}(\.\d{3})+(,\d+)?$", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "").replace(",", "")
    s = re.sub(r"[^\d.]", "", s)
    if not s:
        return None
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


NUM_RE = re.compile(r"(\d{1,4})\D{1,3}(\d{1,2})\D{1,3}(\d{2,4})")


def parse_date_candidates(raw) -> list:
    """Return list of (date, order) candidates; order in {'DMY','MDY','ISO','TR'}."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    if isinstance(raw, datetime):
        return [(raw.date(), "ISO")]
    if isinstance(raw, date):
        return [(raw, "ISO")]

    s = str(raw).strip()
    if not s:
        return []

    # ISO 2024-05-03 - unambiguous, must be parsed before the numeric regex
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        try:
            return [(date(int(m.group(1)), int(m.group(2)), int(m.group(3))), "ISO")]
        except ValueError:
            return []

    # 5 Mart 2024  -> unambiguous
    m = re.match(r"^(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(\d{4})$", s)
    if m:
        day, mon, yr = int(m.group(1)), MONTHS_TR.get(strip_accents(m.group(2)).lower()), int(m.group(3))
        if mon:
            try:
                return [(date(yr, mon, day), "TR")]
            except ValueError:
                return []

    m = NUM_RE.search(s)
    if not m:
        return []
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    out = []
    for order, (d, mth) in (("DMY", (a, b)), ("MDY", (b, a))):
        try:
            out.append((date(y, mth, d), order))
        except ValueError:
            pass
    return out


def order_votes(votes: list) -> str | None:
    """Vote on the sheet's dominant date order.

    Only UNAMBIGUOUS dates vote - a date like 08.02.2023 could be read both
    ways, so it must not count for either side. A handful of rows typed in a
    different format must not make a whole sheet unreadable, but a genuinely
    mixed sheet returns None so its ambiguous rows get flagged, not guessed.
    """
    dm = md = 0
    for o in votes:
        if o == "DMY":
            dm += 1
        elif o == "MDY":
            md += 1
    total = dm + md
    if total < 3:
        return None
    if dm >= 3 * md and dm >= 3:
        return "DMY"
    if md >= 3 * dm and md >= 3:
        return "MDY"
    return None


def date_parts(raw) -> tuple[int, int] | None:
    """Return (first, second) numeric parts of a numeric date, if it has them."""
    if raw is None or isinstance(raw, (datetime, date)):
        return None
    m = NUM_RE.search(str(raw))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


# ---------------------------------------------------------------- pipeline

def find_header_row(df: pd.DataFrame) -> int:
    """Header is the first row where at least 3 cells look like known fields."""
    for i in range(min(6, len(df))):
        found = [guess_field(c) for c in df.iloc[i].tolist()]
        if sum(1 for f in found if f) >= 3:
            return i
    return 0


def normalise_sheet(df: pd.DataFrame) -> pd.DataFrame:
    """Find the real header row, use it as column names, map columns to fields."""
    h = find_header_row(df)
    body = df.iloc[h + 1:].copy()            # data starts under the header row
    body.columns = [str(c) for c in df.iloc[h].tolist()]

    mapping = {}
    for col in body.columns:
        f = guess_field(col)
        if f and f not in mapping.values():
            mapping[col] = f
    out = pd.DataFrame()
    for col, field in mapping.items():
        out[field] = body[col].values
    for field in ("booking_no", "name", "last_name", "check_in", "check_out", "price", "note"):
        if field not in out.columns:
            out[field] = None
    out = out[["booking_no", "name", "last_name", "check_in", "check_out", "price", "note"]]
    return out.reset_index(drop=True)


def split_name(raw) -> tuple[str, str, str]:
    """Return (first, last, problem)."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return "", "", "missing name"
    s = re.sub(r"\s+", " ", str(raw)).strip()
    if not s:
        return "", "", "missing name"
    parts = s.split(" ")
    if len(parts) == 1:
        return turkish_title(parts[0]), "", "single token name - last name missing"
    first, last = parts[0], " ".join(parts[1:])
    return turkish_title(first), turkish_title(last), ""


def main() -> None:
    os.makedirs(os.path.dirname(OUT_XLSX), exist_ok=True)
    xl = pd.ExcelFile(SRC)
    clean_rows, review_rows = [], []
    sheets_done, sheets_empty = 0, 0
    sheet_rows: dict[str, int] = {}

    for sheet in xl.sheet_names:
        raw = xl.parse(sheet, header=None, dtype=object)
        if raw.empty:
            sheets_empty += 1
            continue
        df = normalise_sheet(raw)
        if df.empty:
            sheets_empty += 1
            continue
        sheets_done += 1

        # --- sheet level date-order inference ---
        votes = []
        for col in ("check_in", "check_out"):
            for v in df[col].tolist():
                cands = parse_date_candidates(v)
                if len(cands) == 1:          # only unambiguous dates get a vote
                    votes.append(cands[0][1])
        sheet_order = order_votes(votes)

        for idx, row in df.iterrows():
            excel_row = idx + 3     # title row + header row offset
            name_raw = row["name"]
            if name_raw is not None and str(name_raw).strip().lower().strip(":") in TOTAL_WORDS:
                continue             # hand typed total row
            if all(pd.isna(row[c]) or str(row[c]).strip() == "" for c in ("name", "check_in", "check_out", "price")):
                continue             # blank row

            first, last, nprob = split_name(name_raw)
            has_last_col = row.get("last_name") is not None and str(row["last_name"]).strip() != ""
            if has_last_col:
                last = turkish_title(re.sub(r"\s+", " ", str(row["last_name"])).strip())
            problems = []
            if nprob and not has_last_col:
                problems.append(nprob)

            price = to_number(row["price"])
            if price is None:
                problems.append("price missing or not a number")
                price = None

            # --- resolve the two dates ---
            # Tier 1: unambiguous readings (ISO, "5 Mart 2024", or only one valid order)
            # Tier 2: the business rule (price = nights x 40) breaks a remaining tie
            # Tier 3: the sheet-level order vote is used when price cannot help
            # Anything still unresolved is FLAGGED, never guessed.
            ci_c = parse_date_candidates(row["check_in"])
            co_c = parse_date_candidates(row["check_out"])
            dp = []
            ci = co = None

            if not ci_c:
                dp.append("check-in missing")
            if not co_c:
                dp.append("check-out missing")

            if ci_c and co_c:
                combos = []
                for a, oa in ci_c:
                    for b, ob in co_c:
                        n = (b - a).days
                        if 0 < n <= 30:
                            combos.append((a, b, n, oa, ob))

                implied = None
                if price is not None and price > 0:
                    q = price / ROOM_RATE
                    if abs(q - round(q)) < 1e-6:
                        implied = round(q)

                chosen = None
                if implied is not None:
                    matched = [c for c in combos if c[2] == implied]
                    if len(matched) == 1:
                        chosen = matched[0]
                if chosen is None and sheet_order:
                    same = [c for c in combos if c[3] == sheet_order and c[4] == sheet_order]
                    if len(same) == 1:
                        chosen = same[0]
                if chosen is None and len(combos) == 1:
                    chosen = combos[0]
                if chosen is None:
                    dp.append("ambiguous day-first/month-first - not resolvable")
                else:
                    ci, co = chosen[0], chosen[1]

            nights = None
            if ci and co:
                nights = (co - ci).days
                if nights <= 0:
                    problems.append("check-out is not after check-in")
                    nights = None
            elif ci or co:
                problems.append("one of the dates is missing")

            # --- business rule check ---
            if price is not None and nights is not None:
                expected = nights * ROOM_RATE
                if abs(price - expected) > 0.01:
                    problems.append(f"price {price:.0f} != {nights} nights x 40 = {expected:.0f}")
            if price is not None and price < 0:
                problems.append("negative price")

            if problems or dp:
                for p in problems:
                    review_rows.append({"source_sheet": sheet, "excel_row": excel_row,
                                        "booking_no": row["booking_no"], "reason": p})
                for p in dp:
                    review_rows.append({"source_sheet": sheet, "excel_row": excel_row,
                                        "booking_no": row["booking_no"], "reason": p})
                continue

            clean_rows.append({
                "booking_number": row["booking_no"] or "",
                "first_name": first, "last_name": last,
                "check_in": ci, "check_out": co, "nights": nights,
                "price_usd": price,
                "notes": row["note"] if row["note"] is not None and not pd.isna(row["note"]) else "",
                "source_sheet": sheet,
            })
            sheet_rows[sheet] = sheet_rows.get(sheet, 0) + 1

    clean = pd.DataFrame(clean_rows)
    before = len(clean)
    clean = clean.drop_duplicates(subset=["booking_number", "first_name", "last_name", "check_in"])
    dupes = before - len(clean)

    clean_out = clean[["booking_number", "first_name", "last_name", "check_in", "check_out",
                       "nights", "price_usd", "notes"]].copy()
    clean_out["check_in"] = pd.to_datetime(clean_out["check_in"])
    clean_out["check_out"] = pd.to_datetime(clean_out["check_out"])
    clean_out = clean_out.sort_values("check_in")

    monthly = clean_out.assign(month=clean_out["check_in"].dt.strftime("%Y-%m")).groupby("month").agg(
        bookings=("price_usd", "size"), revenue_usd=("price_usd", "sum")).reset_index()
    yearly = clean_out.assign(year=clean_out["check_in"].dt.year).groupby("year").agg(
        bookings=("price_usd", "size"), revenue_usd=("price_usd", "sum")).reset_index()

    review = pd.DataFrame(review_rows)
    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as xw:
        clean_out.to_excel(xw, sheet_name="clean", index=False)
        review.to_excel(xw, sheet_name="needs_review", index=False)
        monthly.to_excel(xw, sheet_name="summary_monthly", index=False)
        yearly.to_excel(xw, sheet_name="summary_yearly", index=False)
    review.to_csv(OUT_REVIEW, index=False, encoding="utf-8-sig")

    print(f"source        : input/hotel_bookings_2023_2026.xlsx  (relative to this folder)")
    print(f"sheets read   : {len(xl.sheet_names)} total "
          f"({sheets_done} with a booking table, {sheets_empty} empty/skipped)")
    print(f"bookings found in {len(sheet_rows)} sheets ({sum(sheet_rows.values())} rows kept)")
    print(f"rows cleaned  : {len(clean_out)}   (duplicates removed: {dupes})")
    print(f"flagged       : {len(review)} rows -> output/needs_review.csv")
    print()
    print("--- summary by year ---")
    for _, r in yearly.iterrows():
        print(f"  {int(r['year'])}: {int(r['bookings']):4d} bookings   revenue ${r['revenue_usd']:,.0f}")
    print()
    print("--- top reasons flagged ---")
    if len(review):
        counts = review["reason"].str.replace(r"[0-9]+", "N", regex=True).value_counts().head(6)
        for reason, n in counts.items():
            print(f"  {n:4d}  {reason}")
    print()
    print(f"written       : output/hotel_bookings_clean.xlsx")
    print(f"flagged csv   : output/needs_review.csv")


if __name__ == "__main__":
    main()
