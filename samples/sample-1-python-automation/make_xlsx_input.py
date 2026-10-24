#!/usr/bin/env python3
"""
Helper: (re)generate the one .xlsx source file used by the demo.
Kept in the repo so the sample data is reproducible from scratch.

Run:  python make_xlsx_input.py
"""
import pandas as pd
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "input" / "vendor_d_office_supply.xlsx"

ROWS = [
    {
        "Company": "Northwind Office Supply",
        "Contact": "marta  kowalski",
        "Telephone": "+1 (415) 555-0134 ext. 21",
        "E-Mail": "M.Kowalski@northwind-office.example",
        "Order Date": "2024-11-08",
        "Amount": "1,842.00",
        "Currency": "USD",
        "Notes": "re-order",
    },
    {
        "Company": "northwind office supply",
        "Contact": "",
        "Telephone": "+1 (415) 555-0134 ext. 21",
        "E-Mail": "M.Kowalski@northwind-office.example",
        "Order Date": "Nov 9, 2024",
        "Amount": "220.50",
        "Currency": "USD",
        "Notes": "",
    },
    {
        "Company": "Blue Harbor Logistics",
        "Contact": "devi anand",
        "Telephone": "91-98765-43210",
        "E-Mail": "devi@blueharbor.example",
        "Order Date": "2024/11/12",
        "Amount": "€4.310,75",
        "Currency": "EUR",
        "Notes": "",
    },
    {
        "Company": "  Kestrel Media  ",
        "Contact": "sam o'brien",
        "Telephone": "+44 20 7946 0958",
        "E-Mail": "sam@kestrelmedia.example",
        "Order Date": "12.11.2024",
        "Amount": "980",
        "Currency": "GBP",
        "Notes": "net 30",
    },
    {
        "Company": "Kestrel Media",
        "Contact": "sam o'brien",
        "Telephone": "",
        "E-Mail": "sam@kestrelmedia.example",
        "Order Date": "2024-11-15",
        "Amount": "120",
        "Currency": "GBP",
        "Notes": "",
    },
]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(ROWS).to_excel(OUT, index=False)
    print(f"wrote {OUT} ({len(ROWS)} rows)")


if __name__ == "__main__":
    main()
