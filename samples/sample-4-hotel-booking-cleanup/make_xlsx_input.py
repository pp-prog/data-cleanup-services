#!/usr/bin/env python3
"""
make_xlsx_input.py — generate a MESSY hotel bookings workbook on purpose.

This mirrors the real brief of the Upwork job "Clean and merge messy hotel
booking data from Excel (48 sheets) into one table":

  * 48 monthly sheets (2023-01 .. 2026-12) + 1 sheet holding no booking data
  * every sheet has a DIFFERENT header layout (column names, column order,
    extra columns, a title row above the header)
  * dates in many formats, some day-first and some month-first
  * prices as plain numbers, currency symbols, text, negative values, blanks
  * names with broken capitalization, extra spaces, missing Turkish letters
  * duplicate rows, blank rows, hand-typed TOTAL rows
  * some check-in / check-out pairs are reversed or missing

Run:  python make_xlsx_input.py
Out:  input/hotel_bookings_2023_2026.xlsx
"""
from __future__ import annotations

import os
import random
from datetime import date, timedelta

from openpyxl import Workbook

random.seed(20261023)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "input", "hotel_bookings_2023_2026.xlsx")

MONTHS_TR = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]

FIRST = [
    "ayşe", "MEHMET", "zeynep", "Ahmet ", "fatma  ", "mustafa",
    "elif", "Hüseyin", "emine", "İbrahim", "hatice", "osman",
    "gülşen", "burak", "şeyma", "kemal",
]
LAST = [
    "yılmaz", "YILMAZ", "kaya", "demir", "şahin", "ÇELİK",
    "ÖZTÜRK", "aydin", "koc", "polat", "erdogan", "aslan",
    "güneş", "taş", "dogan", "aksoy",
]

ROOM_RATE = 40.0  # business rule: price = nights * 40 USD

HEADER_VARIANTS = [
    ["Rezervasyon No", "Ad Soyad", "Giriş", "Çıkış", "Fiyat", "Not"],
    ["Booking ID", "Name", "Check-in", "Check-out", "Price", "Notes"],
    ["no", "ad_soyad", "giris_tarihi", "cikis_tarihi", "ucret", "not"],
    ["Rezervasyon No", "Ad", "Soyad", "Giriş", "Çıkış", "Fiyat", "Oda Tipi", "Not"],
    ["Ad Soyad", "Giriş", "Çıkış", "Fiyat", "Rezervasyon No", "Not"],
    ["REZERVASYON NO", "AD SOYAD", "GİRİŞ TARİHİ", "ÇIKIŞ TARİHİ", "FİYAT", "NOT"],
]
TITLE_ROWS = {1, 5}


def fmt_date(d: date, style: int) -> str:
    """Render a date in one of several formats, mixing day-first and month-first."""
    if style == 0:
        return d.strftime("%d.%m.%Y")
    if style == 1:
        return d.strftime("%Y-%m-%d")
    if style == 2:
        return d.strftime("%m/%d/%Y")          # month-first
    if style == 3:
        return d.strftime("%d/%m/%Y")          # day-first
    if style == 4:
        return f"{d.day} {MONTHS_TR[d.month - 1]} {d.year}"
    return d.strftime("%d-%m-%Y")


def fmt_price(amount: float, style: int):
    if style == 0:
        return amount
    if style == 1:
        return f"{amount:.0f} USD"
    if style == 2:
        return f"{amount:.0f} $" if amount >= 0 else f"-{abs(amount):.0f} $"
    if style == 3:
        return None
    if style == 4:
        return f"{amount / 40:.0f} gecelik"    # wrong unit, typed by hand
    return f"{amount:,.2f}"


def build_rows(year: int, month: int, variant: int, offset: int, sheet_dstyle: int) -> list:
    rows = []
    n = 31 if variant % 3 != 2 else 24
    day0 = date(year, month, 1)

    for i in range(n):
        cin = day0 + timedelta(days=random.randint(0, 25))
        nights = random.randint(1, 6)
        cout = cin + timedelta(days=nights)
        price = nights * ROOM_RATE

        first, last = random.choice(FIRST), random.choice(LAST)
        name = f"{first} {last}"
        if random.random() < 0.12:
            name = f"{last.title()} {first.title()}"

        dstyle = sheet_dstyle
        if random.random() < 0.05:      # a handful of rows typed in another format
            dstyle = random.choice([0, 1, 2, 3, 4, 5])
        pstyle = random.choice([0, 0, 0, 1, 1, 2, 2, 3, 4, 5])

        r = {"_id": f"R{offset + i + 1:05d}", "_name": name,
             "_date_in": fmt_date(cin, dstyle), "_date_out": fmt_date(cout, dstyle),
             "_price": fmt_price(price, pstyle), "_not": ""}

        if random.random() < 0.06:
            r["_price"] = fmt_price(price + random.choice([-40, 40, 80]), pstyle)
        if random.random() < 0.04:
            r["_date_in"], r["_date_out"] = r["_date_out"], r["_date_in"]
        if random.random() < 0.03:
            r["_date_out"] = ""
        if random.random() < 0.04:
            r["_not"] = random.choice(["kapıda ödeme", "geç giriş", "VIP misafir", "iptal edildi"])
        rows.append(r)

    if random.random() < 0.7:                    # hand typed total row
        rows.append({"_id": "", "_name": "TOPLAM", "_date_in": "", "_date_out": "",
                     "_price": "12.400", "_not": ""})
    rows.append({"_id": "", "_name": "", "_date_in": "", "_date_out": "", "_price": "", "_not": ""})
    if random.random() < 0.25:                   # accidental duplicate of an earlier row
        rows.append(dict(rows[0]))
    return rows


def write_sheet(ws, variant: int, rows: list) -> None:
    if variant in TITLE_ROWS:
        ws.append([f"OTEL REZERVASYON KAYITLARI - {ws.title}"])
    ws.append(HEADER_VARIANTS[variant])

    for r in rows:
        name = r["_name"]
        parts = name.split(" ", 1)
        if variant == 3:
            ws.append([r["_id"], parts[0], parts[1] if len(parts) > 1 else "",
                       r["_date_in"], r["_date_out"], r["_price"], "Standart", r["_not"]])
        elif variant == 4:
            ws.append([name, r["_date_in"], r["_date_out"], r["_price"], r["_id"], r["_not"]])
        else:
            ws.append([r["_id"], name, r["_date_in"], r["_date_out"], r["_price"], r["_not"]])


def main() -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)

    sheets = []
    idx = 0
    for year in (2023, 2024, 2025, 2026):
        for month in range(1, 13):
            idx += 1
            sheets.append((f"{year} {MONTHS_TR[month - 1]}", year, month,
                           idx % len(HEADER_VARIANTS), idx))

    for name, year, month, variant, offset in sheets:
        ws = wb.create_sheet(title=name)
        # one typist, one date format per month (mostly day-first, as in Turkey)
        sheet_dstyle = random.choice([0, 0, 0, 3, 1, 4, 2])
        write_sheet(ws, variant, build_rows(year, month, variant, offset * 40, sheet_dstyle))

    ws = wb.create_sheet(title="Notlar")
    ws.append(["Açıklama"])
    ws.append(["Bu sayfa 2023 arşivi için boş bırakılmıştır."])

    wb.save(OUT)
    print(f"wrote {OUT}")
    print(f"sheets: {len(sheets)} monthly + 1 empty 'Notlar'")


if __name__ == "__main__":
    main()
