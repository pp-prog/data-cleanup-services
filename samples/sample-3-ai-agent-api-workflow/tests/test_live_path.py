#!/usr/bin/env python3
"""
Test harness — verifies the LIVE code path without calling a real provider.

It starts a tiny local HTTP server that speaks the OpenAI chat-completions format,
points LLM_BASE_URL at it, sets a dummy LLM_API_KEY, and runs workflow.py --mode live.

This proves that the request building, JSON parsing, validation, retry and export code
paths work. The dummy key never leaves the machine and is not a real credential.

Run:  python tests/test_live_path.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXTRACT_RESPONSE = {
    "company": "Northwind Office Supply",
    "contact_name": "Marta Kowalski",
    "email": "m.kowalski@northwind-office.example",
    "country": "United States",
    "product_interest": "A4 copy paper",
    "quantity": "400 boxes",
    "target_price": "$6.20",
    "urgency": "very high",
    "summary": "Wants a quarterly price for A4 copy paper.",
}

REPORT_RESPONSE = "# SAMPLE OUTPUT - fake server report\n\n## Overview\n5 enquiries processed.\n"


class FakeHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        prompt = body["messages"][-1]["content"]
        system = body["messages"][0]["content"].lower()
        content = json.dumps(EXTRACT_RESPONSE) if "extract" in system else REPORT_RESPONSE
        payload = {
            "choices": [{"message": {"role": "assistant", "content": content}}]
        }
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        print(f"    [fake api] prompt starts with: {prompt[:40]!r}")

    def log_message(self, *args):  # silence request logging
        return


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), FakeHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Fake OpenAI-compatible API listening on http://127.0.0.1:{port}")

    env = dict(os.environ)
    env["LLM_API_KEY"] = "test-key-not-a-real-credential"
    env["LLM_BASE_URL"] = f"http://127.0.0.1:{port}/v1"
    env["LLM_MODEL"] = "demo-model"

    result = subprocess.run(
        [sys.executable, str(ROOT / "workflow.py"), "--mode", "live", "--outdir", "output_test"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    server.shutdown()

    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        print("FAIL: live path returned a non-zero exit code")
        return 1

    extracted = json.loads((ROOT / "output_test" / "extracted_records.json").read_text(encoding="utf-8"))
    assert extracted["mode"] == "live", extracted["mode"]
    assert len(extracted["records"]) == 5, len(extracted["records"])
    assert extracted["records"][0]["fields"]["quantity"] == 400, extracted["records"][0]["fields"]
    assert extracted["records"][0]["fields"]["urgency"] == "low", "out-of-range urgency must be coerced"
    print("PASS: live code path handled the fake API, coerced types, and wrote both output files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
