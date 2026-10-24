#!/usr/bin/env python3
"""
AI workflow demo — read input records -> extract structured fields -> draft a report.

Sample project for portfolio purposes. Demo data only; no client data involved.

Workflow (3 steps)
------------------
    [1] LOAD      read raw records from input/records.json
    [2] EXTRACT   one LLM call per record -> structured JSON fields (validated)
    [3] REPORT    one LLM call over the extracted data -> markdown report draft

The script talks to any OpenAI-compatible chat-completions endpoint. Credentials come
from environment variables ONLY -- no key is ever hard-coded, printed or written to disk:

    LLM_API_KEY   (required for live mode)
    LLM_BASE_URL  (optional, default https://api.openai.com/v1)
    LLM_MODEL     (optional, default gpt-4o-mini)

If LLM_API_KEY is not set, the script runs in MOCK MODE: it produces a structurally
identical output using deterministic local fixtures, and labels the result as
"SAMPLE OUTPUT - generated offline, no API call was made". This keeps the demo
runnable for a reviewer with no account and no cost.

Usage
-----
    pip install requests
    python workflow.py                       # mock mode (no key needed)
    python workflow.py --mode live           # call the real API
    python workflow.py --input input/records.json --outdir output

Dependencies: requests (live mode only). Mock mode needs nothing but the standard library.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
MAX_RETRIES = 3
TIMEOUT = 60

# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------
EXTRACT_SYSTEM = (
    "You extract structured fields from free-text supplier enquiry messages. "
    "Return ONLY a JSON object with exactly these keys: "
    "company, contact_name, email, country, product_interest, quantity, target_price, "
    "urgency (one of: low, medium, high), summary (one sentence). "
    "Use null for any field that is not stated. Do not invent information. "
    "Do not wrap the JSON in markdown code fences."
)

REPORT_SYSTEM = (
    "You are a business analyst. Given a table of extracted enquiry records, write a "
    "short markdown report with these sections: ## Overview, ## Key numbers, "
    "## Top opportunities, ## Recommended next steps. Use only the data provided. "
    "Do not invent numbers."
)


# --------------------------------------------------------------------------
# Step 1 — load
# --------------------------------------------------------------------------
def load_records(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("records", data.get("items", []))
    if not isinstance(data, list):
        raise ValueError("Input must be a JSON list of records, or an object with a 'records' list.")
    for index, record in enumerate(data):
        if "id" not in record:
            record["id"] = f"REC-{index + 1:03d}"
    return data


# --------------------------------------------------------------------------
# Step 2 — extract (LLM call, validated)
# --------------------------------------------------------------------------
REQUIRED_FIELDS = [
    "company",
    "contact_name",
    "email",
    "country",
    "product_interest",
    "quantity",
    "target_price",
    "urgency",
    "summary",
]
VALID_URGENCY = {"low", "medium", "high"}


def parse_json_object(text: str) -> dict:
    """Pull a JSON object out of a model response, tolerating code fences and prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in model response: {text[:200]}")
    return json.loads(text[start : end + 1])


def validate_extraction(data: dict) -> tuple[dict, list[str]]:
    """Coerce the model output into the schema. Returns (clean, warnings)."""
    warnings: list[str] = []
    clean: dict = {}
    for field in REQUIRED_FIELDS:
        value = data.get(field)
        if isinstance(value, str):
            value = value.strip() or None
        clean[field] = value
    if clean["quantity"] is not None:
        # Accept "400", "400 boxes", "1,200 units" -> 1200
        match = re.search(r"-?\d[\d,]*", str(clean["quantity"]))
        if match:
            try:
                clean["quantity"] = int(match.group(0).replace(",", ""))
            except ValueError:
                warnings.append("quantity was not an integer; dropped")
                clean["quantity"] = None
        else:
            warnings.append("quantity had no number in it; dropped")
            clean["quantity"] = None
    if clean["target_price"] is not None:
        # Accept "$6.20", "6.20 USD", "about 6.20 per box" -> 6.20
        match = re.search(r"-?\d[\d,]*\.?\d*", str(clean["target_price"]))
        if match:
            try:
                clean["target_price"] = round(float(match.group(0).replace(",", "")), 2)
            except ValueError:
                warnings.append("target_price was not a number; dropped")
                clean["target_price"] = None
        else:
            warnings.append("target_price had no number in it; dropped")
            clean["target_price"] = None
    urgency = (clean["urgency"] or "low").lower()
    if urgency not in VALID_URGENCY:
        warnings.append(f"urgency '{urgency}' outside allowed set; mapped to 'low'")
        urgency = "low"
    clean["urgency"] = urgency
    if not clean["email"]:
        warnings.append("no email extracted")
    elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(clean["email"])):
        warnings.append("email format looks invalid")
    return clean, warnings


def call_llm(system_prompt: str, user_prompt: str, config: dict) -> str:
    """One chat-completions call with retry + exponential backoff."""
    if requests is None:
        raise RuntimeError("requests is not installed. Run: pip install requests")
    base_url = config["base_url"].rstrip("/")
    url = f"{base_url}/chat/completions"
    payload = {
        "model": config["model"],
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    headers = {"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"}

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
            if response.status_code == 429:
                wait = float(response.headers.get("Retry-After", 2 ** attempt))
                print(f"      rate limited, waiting {wait:.0f}s (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == MAX_RETRIES:
                break
            wait = 2 ** attempt
            print(f"      error ({exc}); retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"LLM call failed after {MAX_RETRIES} attempts: {last_error}")


def extract_one(record: dict, config: dict) -> tuple[dict, list[str], str]:
    """Returns (clean_fields, warnings, raw_model_output)."""
    user_prompt = (
        "Extract the structured fields from this enquiry message.\n\n"
        f"Subject: {record.get('subject', '')}\n"
        f"Body:\n{record.get('body', '')}\n"
    )
    if config["mode"] == "mock":
        raw = json.dumps(MOCK_EXTRACTIONS.get(record["id"], {}))
    else:
        raw = call_llm(EXTRACT_SYSTEM, user_prompt, config)
    data = parse_json_object(raw)
    clean, warnings = validate_extraction(data)
    return clean, warnings, raw


# --------------------------------------------------------------------------
# Step 3 — report (LLM call over the extracted data)
# --------------------------------------------------------------------------
def build_report(records: list[dict], config: dict) -> str:
    table = json.dumps(
        [
            {
                "company": r["fields"]["company"],
                "country": r["fields"]["country"],
                "product_interest": r["fields"]["product_interest"],
                "quantity": r["fields"]["quantity"],
                "target_price": r["fields"]["target_price"],
                "urgency": r["fields"]["urgency"],
            }
            for r in records
        ],
        ensure_ascii=False,
        indent=2,
    )
    if config["mode"] == "mock":
        return build_mock_report(records)
    return call_llm(REPORT_SYSTEM, f"Extracted records:\n{table}", config)


def build_mock_report(records: list[dict]) -> str:
    total_qty = sum(r["fields"]["quantity"] or 0 for r in records)
    high = [r for r in records if r["fields"]["urgency"] == "high"]
    countries = sorted({r["fields"]["country"] for r in records if r["fields"]["country"]})
    lines = [
        "# SAMPLE OUTPUT - Weekly Enquiry Report (offline mock, no API call was made)",
        "",
        "## Overview",
        f"{len(records)} supplier enquiries were processed. "
        f"{len(high)} are flagged high urgency. "
        f"Countries represented: {', '.join(countries)}.",
        "",
        "## Key numbers",
        f"- Records processed: {len(records)}",
        f"- Total units requested: {total_qty}",
        f"- High-urgency enquiries: {len(high)}",
        f"- Records missing a contact email: {sum(1 for r in records if not r['fields']['email'])}",
        "",
        "## Top opportunities",
    ]
    for record in sorted(records, key=lambda r: (r["fields"]["urgency"] != "high", -(r["fields"]["quantity"] or 0)))[:3]:
        lines.append(
            f"- **{record['fields']['company']}** ({record['fields']['country']}) - "
            f"{record['fields']['product_interest']}, {record['fields']['quantity']} units, "
            f"target {record['fields']['target_price']}, urgency {record['fields']['urgency']}."
        )
    lines += [
        "",
        "## Recommended next steps",
        "1. Reply to the high-urgency enquiries within one business day.",
        "2. Confirm unit prices and shipping terms with the remaining companies.",
        "3. Chase the records where the contact email could not be extracted.",
        "",
        "---",
        "_This report was produced by the offline mock generator so the demo runs with no "
        "API key. A live run against an LLM API produces the same structure._",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Mock fixtures (offline mode only)
# --------------------------------------------------------------------------
MOCK_EXTRACTIONS = {
    "REC-001": {
        "company": "Northwind Office Supply",
        "contact_name": "Marta Kowalski",
        "email": "m.kowalski@northwind-office.example",
        "country": "United States",
        "product_interest": "A4 copy paper, 500 sheets per box",
        "quantity": 400,
        "target_price": "6.20",
        "urgency": "high",
        "summary": "Northwind wants a quarterly price for A4 copy paper, 400 boxes.",
    },
    "REC-002": {
        "company": "Blue Harbor Logistics",
        "contact_name": "Devi Anand",
        "email": "devi@blueharbor.example",
        "country": "India",
        "product_interest": "Heavy duty stapler, 65mm",
        "quantity": 120,
        "target_price": "22.00",
        "urgency": "medium",
        "summary": "Blue Harbor is comparing stapler suppliers for 120 units.",
    },
    "REC-003": {
        "company": "Kestrel Media",
        "contact_name": "Sam O'Brien",
        "email": "sam@kestrelmedia.example",
        "country": "United Kingdom",
        "product_interest": "Ergonomic mouse",
        "quantity": 60,
        "target_price": None,
        "urgency": "low",
        "summary": "Kestrel Media asked for a catalogue and a price list for 60 mice.",
    },
    "REC-004": {
        "company": "Pinewood Retail Ltd",
        "contact_name": "Emma Clark",
        "email": "emma.clark@pinewoodretail.example",
        "country": "United States",
        "product_interest": "Desk lamp LED",
        "quantity": 250,
        "target_price": "18.00",
        "urgency": "high",
        "summary": "Pinewood Retail needs 250 LED desk lamps delivered before its store refit.",
    },
    "REC-005": {
        "company": "Lumen Print Works",
        "contact_name": "Yuki Tanaka",
        "email": "yuki@lumenprint.example",
        "country": "Japan",
        "product_interest": "Ballpoint pens, 10-pack",
        "quantity": 900,
        "target_price": "0.45",
        "urgency": "medium",
        "summary": "Lumen Print Works ordered 900 packs of pens and asked about bulk pricing.",
    },
}


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="AI workflow demo: extract -> validate -> report.")
    parser.add_argument("--input", default="input/records.json")
    parser.add_argument("--outdir", default="output")
    parser.add_argument("--mode", choices=["auto", "live", "mock"], default="auto",
                        help="auto = live when LLM_API_KEY is set, otherwise mock")
    args = parser.parse_args()

    started = time.perf_counter()

    api_key = os.environ.get("LLM_API_KEY", "").strip()
    mode = args.mode
    if mode == "auto":
        mode = "live" if api_key else "mock"
    if mode == "live" and not api_key:
        sys.exit("LLM_API_KEY is not set. Export it, or run with --mode mock for the offline demo.")
    if mode == "live" and requests is None:
        sys.exit("requests is not installed. Run:  pip install requests")

    config = {
        "mode": mode,
        "api_key": api_key,
        "base_url": os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
        "model": os.environ.get("LLM_MODEL", DEFAULT_MODEL),
    }
    if mode == "live":
        print(f"Mode: LIVE  (model {config['model']}, endpoint {config['base_url']})")
    else:
        print("Mode: MOCK  (no LLM_API_KEY found - output is a labelled sample, no API call made)")

    input_path = Path(args.input)
    outdir = Path(args.outdir)

    print(f"[1/3] Loading records from {input_path}")
    records = load_records(input_path)
    print(f"      {len(records)} records loaded")

    print("[2/3] Extracting structured fields")
    results = []
    for record in records:
        fields, warnings, raw = extract_one(record, config)
        results.append({"id": record["id"], "subject": record.get("subject", ""), "fields": fields,
                        "warnings": warnings, "raw_model_output": raw})
        flag = "  ! " + "; ".join(warnings) if warnings else ""
        print(f"      {record['id']}: {fields['company']} / {fields['urgency']}{flag}")

    print("[3/3] Drafting report")
    report = build_report(results, config)
    if mode == "mock" and not report.startswith("# SAMPLE OUTPUT"):
        report = "# SAMPLE OUTPUT - offline mock run\n\n" + report

    outdir.mkdir(parents=True, exist_ok=True)
    extracted_path = outdir / "extracted_records.json"
    report_path = outdir / "report_draft.md"

    extracted_path.write_text(
        json.dumps(
            {
                "generated_by": "ai-workflow-demo (sample project)",
                "mode": mode,
                "model": config["model"] if mode == "live" else "mock-fixtures",
                "note": "Sample output generated from fictional demo data. No client data involved.",
                "records": results,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path.write_text(report, encoding="utf-8")

    elapsed = time.perf_counter() - started
    print(f"      wrote {extracted_path}")
    print(f"      wrote {report_path}")
    print(f"      finished in {elapsed:.3f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
