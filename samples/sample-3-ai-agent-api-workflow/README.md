# Sample Project — AI Workflow Orchestration (multi-step LLM + API pipeline)

> **Sample project — demo data, no client involved.**
> The enquiries, companies and people in `input/records.json` are fictional. No client
> data, no client results, and no client testimonials are shown.
>
> **About the sample output:** the checked-in output files were produced by the
> **offline mock generator**, which is clearly labelled as such in the output itself
> (`# SAMPLE OUTPUT - …`, and `mode: "mock"` in the JSON). The live code path is
> separately verified by `tests/test_live_path.py`, which runs the real request-building
> and validation code against a local fake API server. No real provider account was used
> to produce the checked-in files.

**What it does:** reads free-text supplier enquiries, extracts validated structured
fields from each one with an LLM, and drafts a summary report — with retries, type
coercion, warnings per record, and a schema-checked output.

---

## Demo (real recorded run)

![sample-3-ai-agent-api-workflow demo](https://pp-prog.github.io/data-cleanup-services/demos/demo-3-ai-agent-api-workflow.gif)

---

## 1. The problem

A sales or procurement inbox is full of unstructured enquiries. Every one of them needs
the same handful of facts pulled out — company, contact, country, what they want, how
many, at what target price, how urgent — and then a decision made about who to reply to
first.

Done by hand, each enquiry takes a few minutes of reading and typing, and the risk is
that two people read the same message differently: one records "400 boxes", another
records "about four hundred", and the totals stop matching.

Two failure modes matter:

- **Silent inconsistency.** Every extraction is a judgment call. If it is not validated
  and logged, a wrong value is indistinguishable from a right one until a customer is
  misquoted.
- **Fragile integration.** The moment the workflow has to *act* on the data — write to a
  sheet, fire a webhook, trigger an email — you need a checkpoint, not just a model
  call.

## 2. The approach

### Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │  input/records.json  (raw enquiry messages)  │
                    └────────────────────┬─────────────────────────┘
                                         │
                            ┌────────────▼────────────┐
                            │  STEP 1 — LOAD          │
                            │  read + normalise ids   │
                            └────────────┬────────────┘
                                         │
              for each record (one LLM call per record)
                                         │
                            ┌────────────▼────────────┐
                            │  STEP 2 — EXTRACT       │
                            │  system prompt + record │
                            │  → LLM (chat completion)│
                            │  → parse JSON (tolerant)│
                            │  → VALIDATE + COERCE    │
                            │  → warnings[]           │
                            └────────────┬────────────┘
                                         │
                            ┌────────────▼────────────┐
                            │  STEP 3 — REPORT        │
                            │  extracted fields → LLM  │
                            │  → markdown draft       │
                            └────────────┬────────────┘
                                         │
                    ┌────────────────────┴─────────────────────┐
                    ▼                                          ▼
        output/extracted_records.json              output/report_draft.md
        (structured data + warnings + raw           (human-readable draft)
         model output for auditing)
```

### The three steps in detail

**Step 1 — Load.** Reads the JSON file, accepts either a bare list or an object with a
`records` list, and assigns a stable `id` to any record that lacks one.

**Step 2 — Extract.** One LLM call per record. The system prompt pins the output to
exactly nine keys and instructs the model to return `null` for anything not stated and
to never invent information. The response then goes through three stages:

1. **Tolerant JSON parsing** — strips markdown code fences, and extracts the outermost
   `{ … }` from a response that has prose around it. A model that adds "Sure! Here is
   the JSON:" does not break the pipeline.
2. **Validation** — every one of the nine required keys is checked for presence.
3. **Coercion** — `quantity` becomes an `int` even when the model returns `"400 boxes"`
   or `"1,200"`; `target_price` becomes a `float` even when it returns `"$6.20"` or
   `"about 6.20 per box"`; `urgency` is checked against `{low, medium, high}` and
   anything else is coerced to `low` with a warning.

Every record keeps `warnings[]` and the `raw_model_output`, so a human can audit what
the model actually said before trusting the parsed value. **Nothing is silently
corrected.**

**Step 3 — Report.** The validated fields are handed to a second LLM call with a
report-shaped prompt (Overview / Key numbers / Top opportunities / Recommended next
steps), and the instruction is explicit: use only the data provided, do not invent
numbers.

### Error handling

| Failure | What happens |
|---|---|
| API returns 429 | Waits for `Retry-After` (or exponential backoff), then retries — up to 3 attempts total |
| Network error / 5xx | Same retry-with-backoff loop; the last exception is raised with the attempt count if all attempts fail |
| Model returns prose instead of JSON | Tolerated: code fences stripped, outermost `{…}` extracted |
| Model returns a field of the wrong type | Coerced where a safe coercion exists (`"400 boxes"` → `400`), otherwise dropped with a warning |
| Model invents an urgency value | Coerced to `low` and flagged in `warnings[]` |
| Model returns no JSON at all | `ValueError` with the first 200 characters of the response in the message, so the failure is diagnosable |
| `LLM_API_KEY` missing | Live mode refuses to start with a clear message; auto mode falls back to the offline mock |
| `requests` not installed | Live mode exits with `pip install requests` |

The raw model output is stored next to the parsed fields for every record, so a failed
extraction can be diagnosed without re-running and paying for the call again.

### Extension points

- **A different provider** — any OpenAI-compatible chat-completions endpoint works via
  `LLM_BASE_URL` and `LLM_MODEL`. Nothing in the code is OpenAI-specific.
- **A different task** — swap `EXTRACT_SYSTEM` and `REQUIRED_FIELDS` for a new schema;
  the parse/validate/coerce/report machinery is reusable as-is.
- **A different input source** — replace `load_records()` with a function that reads
  from a mailbox, a database or an API. It only has to return a list of dicts.
- **A different output destination** — replace the two `write_text` calls with a
  Google Sheets, Airtable, Notion or webhook writer.
- **Human-in-the-loop approval** — the natural checkpoint is between Step 2 and Step 3:
  write `extracted_records.json`, exit, let a person approve or edit it, then run the
  report step on the approved file. That is the recommended pattern for anything that
  writes back to a live system.
- **Scheduling** — the script is a plain command, so cron, Windows Task Scheduler or a
  GitHub Actions schedule can run it unattended.
- **Token cost control** — one call per record is the expensive part. For large
  batches, extract several records per call and validate each individually; the
  validator already works per-record.

### Credential handling

- The API key is read **only** from the `LLM_API_KEY` environment variable.
- No key is hard-coded, committed, logged, or written to any output file.
- The key is never printed — the script prints the model name and base URL, not the
  credential.
- The live mode exits immediately if `LLM_API_KEY` is empty.
- The mock mode makes **no network calls at all**, so the demo cannot leak anything.

## 3. The result

Actual console output from the offline run:

```
Mode: MOCK  (no LLM_API_KEY found - output is a labelled sample, no API call made)
[1/3] Loading records from input\records.json
      5 records loaded
[2/3] Extracting structured fields
      REC-001: Northwind Office Supply / high
      REC-002: Blue Harbor Logistics / medium
      REC-003: Kestrel Media / low
      REC-004: Pinewood Retail Ltd / high
      REC-005: Lumen Print Works / medium
[3/3] Drafting report
      wrote output\extracted_records.json
      wrote output\report_draft.md
      finished in 0.001 s
```

`output/report_draft.md` (offline sample output, labelled as such in the file itself):

```markdown
# SAMPLE OUTPUT - Weekly Enquiry Report (offline mock, no API call was made)

## Overview
5 supplier enquiries were processed. 2 are flagged high urgency. Countries represented:
India, Japan, United Kingdom, United States.

## Key numbers
- Records processed: 5
- Total units requested: 1730
- High-urgency enquiries: 2
- Records missing a contact email: 0

## Top opportunities
- **Northwind Office Supply** (United States) - A4 copy paper, 500 sheets per box, 400 units, target 6.2, urgency high.
- **Pinewood Retail Ltd** (United States) - Desk lamp LED, 250 units, target 18.0, urgency high.
- **Lumen Print Works** (Japan) - Ballpoint pens, 10-pack, 900 units, target 0.45, urgency medium.

## Recommended next steps
1. Reply to the high-urgency enquiries within one business day.
2. Confirm unit prices and shipping terms with the remaining companies.
3. Chase the records where the contact email could not be extracted.

---
_This report was produced by the offline mock generator so the demo runs with no
API key. A live run against an LLM API produces the same structure._
```

`output/extracted_records.json` — one record, trimmed for length:

```json
{
  "id": "REC-001",
  "subject": "A4 copy paper - quarterly price request",
  "fields": {
    "company": "Northwind Office Supply",
    "contact_name": "Marta Kowalski",
    "email": "m.kowalski@northwind-office.example",
    "country": "United States",
    "product_interest": "A4 copy paper, 500 sheets per box",
    "quantity": 400,
    "target_price": 6.2,
    "urgency": "high",
    "summary": "Northwind wants a quarterly price for A4 copy paper, 400 boxes."
  },
  "warnings": [],
  "raw_model_output": "{ ... }"
}
```

### The live code path is tested, not assumed

`tests/test_live_path.py` starts a local HTTP server that speaks the OpenAI
chat-completions format, points `LLM_BASE_URL` at it, sets a **dummy** key, and runs the
real `workflow.py --mode live`:

```
Fake OpenAI-compatible API listening on http://127.0.0.1:59791
    [fake api] prompt starts with: 'Extract the structured fields from this '
    ... (5 extraction calls + 1 report call) ...
Mode: LIVE  (model demo-model, endpoint http://127.0.0.1:59791/v1)
[1/3] Loading records from input\records.json
      5 records loaded
[2/3] Extracting structured fields
      REC-001: Northwind Office Supply / low  ! urgency 'very high' outside allowed set; mapped to 'low'
      ...
[3/3] Drafting report
      wrote output_test\extracted_records.json
      wrote output_test\report_draft.md
      finished in 0.008 s

PASS: live code path handled the fake API, coerced types, and wrote both output files.
```

The fake API deliberately returns `"quantity": "400 boxes"`, `"target_price": "$6.20"`
and `"urgency": "very high"` — and the assertions check that quantity became `400`,
price became `6.2`, and the out-of-range urgency was coerced to `low`. The dummy key
never leaves the machine and is not a real credential.

**Measured result on the demo data set:**

| Metric | Value |
|---|---|
| Records processed | 5 |
| LLM calls (mock mode) | 0 |
| LLM calls (live mode) | 6 (5 extractions + 1 report) |
| Fields extracted per record | 9, all schema-checked |
| Runtime, offline mock | **0.001 s** |
| Runtime, live path against local fake API | 0.008 s (excluding provider latency) |

## 4. How to run it

### Requirements

- Python 3.9+
- `requests` — needed only for live mode

```bash
pip install requests
```

### Run the offline demo (no key, no network, no cost)

```bash
cd sample-3-ai-agent-api-workflow
python workflow.py
```

Output lands in `output/`:

- `output/extracted_records.json` — structured fields, per-record warnings, and the raw
  model output for auditing
- `output/report_draft.md` — the report draft, labelled as sample output

### Run against a real API

```bash
export LLM_API_KEY="your-key-here"
export LLM_BASE_URL="https://api.openai.com/v1"   # optional, this is the default
export LLM_MODEL="gpt-4o-mini"                     # optional, this is the default
python workflow.py --mode live
```

Any OpenAI-compatible endpoint works — point `LLM_BASE_URL` at it and set `LLM_MODEL`.

On Windows PowerShell:

```powershell
$env:LLM_API_KEY="your-key-here"
$env:LLM_MODEL="gpt-4o-mini"
python workflow.py --mode live
```

### Verify the live code path without a provider account

```bash
python tests/test_live_path.py
```

### Files in this sample

```
sample-3-ai-agent-api-workflow/
├── README.md
├── workflow.py                       # the pipeline (load → extract/validate → report)
├── input/
│   └── records.json                  # fictional demo enquiries
├── output/
│   ├── extracted_records.json        # structured output + warnings + raw model output
│   └── report_draft.md               # sample report, labelled as a sample
└── tests/
    └── test_live_path.py             # exercises the live path against a local fake API
```

## 5. Scope notes I give clients before starting

- **This integrates an existing model API. It does not train or fine-tune a model.**
- **The workflow is not an unsupervised agent.** Any step that writes back or sends
  something should have an approval switch, and the natural place for it is between
  extraction and report/action.
- **Output quality depends on the model and on how clear the input is.** I will tell you
  what is realistic before you order, and I will tell you when the data — not the model
  — is the problem.
- **I design the workflow, the prompts, the validation and the integration.** Deployment
  into a specific internal network or VPC may need a separate environment review.

---

*Sample project. Fictional demo enquiries. Output files are labelled sample output from
the offline mock generator; the live code path is verified by an automated test against a
local fake API. No client involved.*
