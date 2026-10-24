#!/usr/bin/env python3
"""
Batch Excel/CSV automation demo — merge many messy vendor files into one clean master table.

Sample project for portfolio purposes. Demo data only; no client data involved.

What it does
------------
1. Reads every .csv / .xlsx file in an input folder (one row per vendor order line).
2. Maps different vendor column names onto one canonical schema (alias table below).
3. Cleans each field: trims whitespace, fixes casing, normalizes dates, phone numbers,
   money amounts and currency codes.
4. Merges records that describe the same vendor (fuzzy-ish key: company + email/phone).
5. Writes a clean master CSV plus a run summary (rows in, rows out, issues fixed, timing).

Usage
-----
    python merge_clean.py                      # full run on ./input -> ./output
    python merge_clean.py --dry-run            # show what would change, write nothing
    python merge_clean.py --input data --output results

Dependencies: pandas + openpyxl (pip install pandas openpyxl)
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    sys.exit("This script needs pandas. Install it with:  pip install pandas openpyxl")

# --------------------------------------------------------------------------
# 1. Canonical schema + vendor column aliases
# --------------------------------------------------------------------------
CANONICAL_COLUMNS = [
    "vendor_id",
    "company_name",
    "contact_name",
    "email",
    "phone",
    "order_date",
    "amount",
    "currency",
    "rows_combined",
    "source_files",
    "issues_fixed",
]

COLUMN_ALIASES = {
    "company_name": ["company_name", "company", "vendor", "supplier", "vendor name", "supplier name"],
    "contact_name": ["contact", "contact_name", "contact person", "full_name", "contactname", "name"],
    "email": ["email", "e-mail", "email_address", "email address", "mail"],
    "phone": ["phone", "phone_no", "telephone", "phone number", "mobile", "tel"],
    "order_date": ["order_date", "date", "order date", "delivery date", "ordered"],
    "amount": ["amount", "total", "value", "order value", "sum"],
    "currency": ["currency", "ccy", "curr"],
}

DATE_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y", "%b %d, %Y", "%d %b %Y", "%Y-%m-%dT%H:%M:%S"]

CURRENCY_ALIASES = {
    "usd": "USD", "$": "USD", "us$": "USD", "dollar": "USD", "dollars": "USD",
    "eur": "EUR", "€": "EUR", "euro": "EUR", "euros": "EUR",
    "jpy": "JPY", "¥": "JPY", "yen": "JPY",
    "gbp": "GBP", "£": "GBP", "pound": "GBP",
    "cny": "CNY", "rmb": "CNY", "yuan": "CNY",
}


def normalise_key(text: str) -> str:
    """Lowercase, strip punctuation and collapse spaces -> for fuzzy comparison."""
    text = (text or "").lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonicalise_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Rename vendor-specific headers to the canonical schema. Returns df + rename report."""
    rename = {}
    report = {}
    lowered = {str(c).strip().lower(): c for c in df.columns}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                rename[lowered[alias]] = canonical
                report[canonical] = str(lowered[alias])
                break
    out = df.rename(columns=rename)
    for canonical in COLUMN_ALIASES:
        if canonical not in out.columns:
            out[canonical] = None
    return out, report


def clean_text(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def clean_company(value) -> tuple[str, str | None]:
    """'  ACME  Ltd. ' -> 'Acme Ltd' ; also reports when the raw form was messy."""
    raw = clean_text(value)
    if not raw:
        return "", "company_missing"
    fixed = re.sub(r"\s+", " ", raw)
    fixed = re.sub(r"\s*,\s*", ", ", fixed)
    # Title case, but keep all-caps acronyms (IBM, BMW) and mixed-case legal suffixes
    # (GmbH, LLC-style tokens) intact.
    words = []
    for word in fixed.split(" "):
        if word.isupper() and len(word) > 1:
            words.append(word)
        elif re.fullmatch(r"[A-Z][a-z]+[A-Z]", word):  # GmbH, OyAb, ...
            words.append(word)
        else:
            words.append(word.capitalize())
    pretty = " ".join(words)
    pretty = pretty.replace("Ltd.", "Ltd").replace("Inc.", "Inc").replace("Co.", "Co")
    issue = None
    if pretty != raw:
        issue = "company_normalised"
    return pretty, issue


def clean_contact(value) -> str:
    raw = clean_text(value)
    if not raw:
        return ""
    return " ".join(part.capitalize() if not part.isupper() else part for part in raw.split(" "))


def clean_email(value) -> tuple[str, str | None]:
    raw = clean_text(value).lower()
    if not raw:
        return "", "email_missing"
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", raw):
        return "", "email_invalid"
    return raw, None


def clean_phone(value) -> tuple[str, str | None]:
    """Keep digits only, strip extensions, normalise international prefixes."""
    raw = clean_text(value)
    if not raw:
        return "", "phone_missing"
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return "", "phone_invalid"
    digits = re.sub(r"(?:ext|x)\.?\s*\d+$", "", digits)
    if digits.startswith("00"):
        digits = digits[2:]
    return digits, ("phone_normalised" if raw != digits else None)


def clean_date(value) -> tuple[str, str | None]:
    raw = clean_text(value)
    if not raw:
        return "", "date_missing"
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d"), (
                "date_format_normalised" if fmt != "%Y-%m-%d" else None
            )
        except ValueError:
            continue
    return "", "date_unparsable"


def clean_amount(value) -> tuple[float | None, str | None]:
    raw = clean_text(value)
    if not raw:
        return None, "amount_missing"
    if raw.startswith("€"):
        raw = "EUR " + raw[1:]
    elif raw.startswith("¥"):
        raw = "JPY " + raw[1:]
    elif raw.startswith("$"):
        raw = "USD " + raw[1:]
    negative = raw.startswith("-") or (raw.startswith("(") and raw.endswith(")"))
    cleaned = re.sub(r"[^\d.,\-]", "", raw)
    # 1.234,56 (EU) vs 1,234.56 (US)
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        frac = cleaned.rsplit(",", 1)[1]
        cleaned = cleaned.replace(",", ".") if len(frac) in (1, 2) else cleaned.replace(",", "")
    number = float(cleaned)
    if negative:
        number = -number
    canonical = f"{number:.2f}"
    return round(number, 2), ("amount_normalised" if canonical != clean_text(value) else None)


def clean_currency(value, amount_text: str) -> tuple[str, str | None]:
    raw = clean_text(value).lower()
    if raw in CURRENCY_ALIASES:
        return CURRENCY_ALIASES[raw], None
    match = re.search(r"(USD|EUR|JPY|GBP|CNY)", clean_text(value).upper())
    if match:
        return match.group(1), ("currency_normalised" if match.group(1) != clean_text(value).upper() else None)
    # Fall back to the symbol embedded in the amount cell.
    for symbol, code in (("€", "EUR"), ("¥", "JPY"), ("$", "USD")):
        if symbol in amount_text:
            return code, "currency_inferred_from_amount"
    return "", "currency_missing"


def merge_key(company: str, email: str, phone: str) -> str:
    """Merge records of the same vendor. Prefer email, fall back to phone."""
    if email:
        return f"{normalise_key(company)}|{email}"
    if phone:
        return f"{normalise_key(company)}|{phone[-9:]}"
    return f"{normalise_key(company)}|{normalise_key(company)}"


def vendor_id(key: str) -> str:
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:6].upper()
    return f"V-{digest}"


def read_inputs(input_dir: Path) -> list[tuple[Path, pd.DataFrame]]:
    files = []
    for path in sorted(input_dir.iterdir()):
        if path.suffix.lower() == ".csv":
            files.append((path, pd.read_csv(path, dtype=str, keep_default_na=False)))
        elif path.suffix.lower() in (".xlsx", ".xlsm"):
            files.append((path, pd.read_excel(path, dtype=str, keep_default_na=False)))
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge and clean vendor spreadsheets.")
    parser.add_argument("--input", default="input", help="input folder (default: ./input)")
    parser.add_argument("--output", default="output", help="output folder (default: ./output)")
    parser.add_argument("--dry-run", action="store_true", help="do not write files")
    args = parser.parse_args()

    started = time.perf_counter()
    input_dir = Path(args.input)
    output_dir = Path(args.output)
    if not input_dir.exists():
        sys.exit(f"Input folder not found: {input_dir}")

    print(f"[1/4] Reading source files from {input_dir}")
    sources = read_inputs(input_dir)
    if not sources:
        sys.exit("No .csv or .xlsx files found in the input folder.")
    for path, df in sources:
        print(f"      - {path.name}: {len(df)} rows, columns: {list(df.columns)}")

    print("[2/4] Normalising columns and cleaning fields")
    cleaned_rows = []
    issues_total: dict[str, int] = {}
    for path, df in sources:
        canon, rename_report = canonicalise_columns(df)
        print(f"      - {path.name}: renamed {rename_report}")
        for _, row in canon.iterrows():
            issues: list[str] = []
            company, issue = clean_company(row["company_name"])
            if issue:
                issues.append(issue)
            contact = clean_contact(row["contact_name"])
            email, issue = clean_email(row["email"])
            if issue:
                issues.append(issue)
            phone, issue = clean_phone(row["phone"])
            if issue:
                issues.append(issue)
            order_date, issue = clean_date(row["order_date"])
            if issue:
                issues.append(issue)
            amount, issue = clean_amount(row["amount"])
            if issue:
                issues.append(issue)
            currency, issue = clean_currency(row["currency"], clean_text(row["amount"]))
            if issue:
                issues.append(issue)
            for issue in issues:
                issues_total[issue] = issues_total.get(issue, 0) + 1
            cleaned_rows.append(
                {
                    "company_name": company,
                    "contact_name": contact,
                    "email": email,
                    "phone": phone,
                    "order_date": order_date,
                    "amount": amount,
                    "currency": currency,
                    "source_file": path.name,
                    "issues_fixed": issues,
                }
            )

    print("[3/4] Merging duplicate vendor records")
    merged: dict[str, dict] = {}
    for row in cleaned_rows:
        key = merge_key(row["company_name"], row["email"], row["phone"])
        if key not in merged:
            merged[key] = {**row, "rows_combined": 1, "source_files": {row["source_file"]}}
        else:
            current = merged[key]
            current["rows_combined"] += 1
            current["source_files"].add(row["source_file"])
            for field in ("contact_name", "email", "phone", "order_date", "amount", "currency"):
                if not current[field] and row[field]:
                    current[field] = row[field]
            current["issues_fixed"] = sorted(set(current["issues_fixed"]) | set(row["issues_fixed"]))

    result = pd.DataFrame(
        [
            {
                "vendor_id": vendor_id(key),
                "company_name": row["company_name"],
                "contact_name": row["contact_name"],
                "email": row["email"],
                "phone": row["phone"],
                "order_date": row["order_date"],
                "amount": row["amount"],
                "currency": row["currency"],
                "rows_combined": row["rows_combined"],
                "source_files": ", ".join(sorted(row["source_files"])),
                "issues_fixed": "; ".join(row["issues_fixed"]),
            }
            for key, row in merged.items()
        ]
    ).sort_values(["company_name", "order_date"], na_position="last")

    elapsed = time.perf_counter() - started
    print(f"[4/4] Finished in {elapsed:.3f} s")
    print(
        f"      rows in: {sum(len(df) for _, df in sources)}  ->  "
        f"unique vendors out: {len(result)}  (merged {sum(len(df) for _, df in sources) - len(result)})"
    )
    print(f"      issues fixed: {issues_total}")

    if args.dry_run:
        print("Dry run: no files written.")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "clean_master.csv"
    result.to_csv(csv_path, index=False, encoding="utf-8")

    summary = [
        "run_at_utc," + datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        f"source_files,{len(sources)}",
        f"rows_in,{sum(len(df) for _, df in sources)}",
        f"unique_vendors_out,{len(result)}",
        f"rows_merged_away,{sum(len(df) for _, df in sources) - len(result)}",
        f"elapsed_seconds,{elapsed:.3f}",
        "",
        "issue,count",
    ]
    summary += [f"{issue},{count}" for issue, count in sorted(issues_total.items())]
    (output_dir / "run_summary.csv").write_text("\n".join(summary) + "\n", encoding="utf-8")

    print(f"      wrote {csv_path}")
    print(f"      wrote {output_dir / 'run_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
