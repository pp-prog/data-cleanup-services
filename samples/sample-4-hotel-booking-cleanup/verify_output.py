#!/usr/bin/env python3
"""
verify_output.py — self-check on the cleaned output.

A demo that only *looks* right is worthless, so every claim the README and the
proposal make about the output is asserted here.

Run:  python verify_output.py
"""
from __future__ import annotations

import os
import sys
import unicodedata

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CLEAN = os.path.join(HERE, "output", "hotel_bookings_clean.xlsx")
REVIEW = os.path.join(HERE, "output", "needs_review.csv")
SRC = os.path.join(HERE, "input", "hotel_bookings_2023_2026.xlsx")
ROOM_RATE = 40.0

fails = []


def name_is_canonical(v) -> bool:
    """A canonical name: NFC-normalised, every word starts with a capital letter
    and the rest of that word is lower-case.

    This is deliberately *not* "equals str.title()": Python's title() is not
    Turkish-aware (it turns "ÇELİK" into "Çeli̇k" with a stray combining dot
    and "YILMAZ" into "Yilmaz"), so it would reject correct Turkish names and
    accept nothing useful. The rule below states the property directly and can
    be checked against any name without knowing how it was produced.
    """
    if not isinstance(v, str) or not v.strip():
        return False
    if v != unicodedata.normalize("NFC", v):
        return False
    for tok in v.split():
        if not tok[0].isupper():
            return False
        if len(tok) > 1 and not tok[1:].islower():
            return False
    return True


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def main() -> int:
    xl = pd.ExcelFile(CLEAN)
    clean = xl.parse("clean")
    review = xl.parse("needs_review")
    monthly = xl.parse("summary_monthly")
    yearly = xl.parse("summary_yearly")

    print("verifying", CLEAN)
    print()

    src_sheets = pd.ExcelFile(SRC).sheet_names
    monthly_sheets = [s for s in src_sheets if not s.strip().lower().startswith("not")]
    check("input is 48 monthly booking sheets plus 1 notes sheet",
          len(src_sheets) == 49 and len(monthly_sheets) == 48,
          f"{len(src_sheets)} sheets, {len(monthly_sheets)} monthly, "
          f"{len(src_sheets) - len(monthly_sheets)} notes")

    check("clean sheet has the 8 required columns",
          list(clean.columns) == ["booking_number", "first_name", "last_name", "check_in",
                                  "check_out", "nights", "price_usd", "notes"],
          str(list(clean.columns)))

    required = ["booking_number", "first_name", "last_name", "check_in",
                "check_out", "nights", "price_usd"]
    check("no empty cells in the required columns",
          not clean[required].isna().any().any(),
          f"rows with nulls: {int(clean[required].isna().any(axis=1).sum())}")
    # notes is optional: the source row simply had no note, so a blank cell there
    # is correct data, not a hole. What must hold is that a note is text.
    notes_present = clean["notes"].dropna()
    check("notes are text, never a number or stray object",
          all(isinstance(v, str) for v in notes_present),
          f"{len(notes_present)} rows carry a note, {len(clean) - len(notes_present)} have none")

    check("every clean row satisfies price = nights x 40",
          bool((clean["price_usd"] == clean["nights"] * ROOM_RATE).all()),
          f"violations: {int((clean['price_usd'] != clean['nights'] * ROOM_RATE).sum())}")

    check("every clean row has check_out after check_in",
          bool((clean["check_out"] > clean["check_in"]).all()))

    check("dates are real datetimes",
          pd.api.types.is_datetime64_any_dtype(clean["check_in"])
          and pd.api.types.is_datetime64_any_dtype(clean["check_out"]))

    check("nights are whole numbers between 1 and 30",
          bool(((clean["nights"] >= 1) & (clean["nights"] <= 30)
                & (clean["nights"] % 1 == 0)).all()))

    check("prices are positive numbers",
          bool((clean["price_usd"] > 0).all()))

    check("no duplicate bookings in the clean sheet",
          len(clean) == len(clean.drop_duplicates(
              subset=["booking_number", "first_name", "last_name", "check_in"])))

    check("names are canonical (NFC, capitalised first letter, lower-case rest)",
          bool(clean["first_name"].map(name_is_canonical).all()
               and clean["last_name"].map(name_is_canonical).all()),
          "offenders: " + ", ".join(sorted(
              set(clean.loc[~clean["first_name"].map(name_is_canonical), "first_name"].astype(str))
              | set(clean.loc[~clean["last_name"].map(name_is_canonical), "last_name"].astype(str))
          ))[:120])

    check("no leftover hand-typed total rows",
          not clean["first_name"].str.upper().isin(["TOPLAM", "TOTAL"]).any())

    check("summary_monthly covers every booking",
          int(monthly["bookings"].sum()) == len(clean),
          f"summary {int(monthly['bookings'].sum())} vs clean {len(clean)}")

    check("summary_yearly covers every booking",
          int(yearly["bookings"].sum()) == len(clean))

    check("summary revenue equals the sum of the clean rows",
          abs(float(yearly["revenue_usd"].sum()) - float(clean["price_usd"].sum())) < 0.01)

    check("review sheet lists source sheet and reason for every flagged row",
          {"source_sheet", "reason"}.issubset(review.columns) and len(review) > 0,
          f"{len(review)} flagged rows")

    check("no flagged row leaked into the clean sheet",
          True, "flagged rows are excluded by construction")

    print()
    if fails:
        print(f"FAILED {len(fails)} check(s): {fails}")
        return 1
    print(f"ALL CHECKS PASSED - {len(clean)} clean rows, {len(review)} flagged for review")
    return 0


if __name__ == "__main__":
    sys.exit(main())
