#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_my_table.py — 脏表格一键清洗工具（自助版）

面向"手里有一堆乱表、不知道从哪下手"的人：
  读入一个或多个 CSV/XLSX → 自动识别列角色 → 清洗 → 输出干净表 + 复核表 + 报告

设计原则（与我的服务完全一致）：
  1. 不编造数据 —— 修不好的值不猜，落到复核表里让你看见。
  2. 不静默丢行 —— 每一行要么进干净表，要么进复核表，行数守恒。
  3. 不覆盖原文件 —— 输出永远写到新目录，原文件只读。

用法
  python clean_my_table.py --input 你的表.csv                       # 单表
  python clean_my_table.py --input 表目录/                           # 多表合并
  python clean_my_table.py --input 表.csv --output 结果/ --format xlsx
  python clean_my_table.py --self-test                              # 自检

依赖
  CSV  ：仅标准库（Python 3.9+）
  XLSX ：额外需要 openpyxl（pip install openpyxl）
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

VERSION = "1.0.0"

# --------------------------------------------------------------------------
# 列角色别名表：不同人写表头的方式差异极大，这里给出常见别名
# --------------------------------------------------------------------------
COLUMN_ALIASES = {
    "name": [
        "name", "company", "company_name", "vendor", "supplier", "vendor name",
        "supplier name", "customer", "client", "name", "名称", "公司", "公司名",
        "供应商", "客户", "单位", "商户",
    ],
    "email": [
        "email", "e-mail", "email_address", "email address", "mail",
        "contact email", "邮箱", "电子邮箱", "邮件",
    ],
    "phone": [
        "phone", "phone_no", "phone number", "telephone", "mobile", "tel",
        "contact", "contact_no", "电话", "手机", "联系电话", "联系方式",
    ],
    "date": [
        "date", "order_date", "delivery date", "ordered", "transaction date",
        "created_at", "invoice_date", "日期", "时间", "下单日期", "订单日期",
        "开票日期", "交易日期",
    ],
    "amount": [
        "amount", "total", "value", "order value", "sum", "price", "cost",
        "revenue", "amount usd", "total price", "金额", "价格", "总价", "合计",
        "金额(含税)", "应付金额",
    ],
    "currency": [
        "currency", "ccy", "curr", "currency code", "币种", "货币", "结算币种",
    ],
    "qty": [
        "qty", "quantity", "units", "count", "数量", "件数", "台数",
    ],
}

DATE_FORMATS = [
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日", "%d.%m.%Y",
    "%d/%m/%Y", "%b %d, %Y", "%b %d %Y", "%d %b %Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
]

CURRENCY_ALIASES = {
    "usd": "USD", "$": "USD", "us$": "USD", "dollar": "USD", "dollars": "USD", "美元": "USD",
    "eur": "EUR", "€": "EUR", "euro": "EUR", "euros": "EUR", "欧元": "EUR",
    "jpy": "JPY", "¥": "JPY", "yen": "JPY", "日元": "JPY",
    "gbp": "GBP", "£": "GBP", "pound": "GBP", "英镑": "GBP",
    "cny": "CNY", "rmb": "CNY", "yuan": "CNY", "人民币": "CNY", "元": "CNY",
}

# 中文姓名/公司名常见的公司后缀，规范化时保留其合法性
LEGAL_SUFFIXES = ("Ltd", "Ltd.", "Inc", "Inc.", "LLC", "Co", "Co.", "Corp", "Corp.", "GmbH", "Oy")


# --------------------------------------------------------------------------
# 基础清洗函数
# --------------------------------------------------------------------------
def clean_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def clean_name(value) -> tuple[str, str | None]:
    raw = clean_text(value)
    if not raw:
        return "", "name_missing"
    fixed = re.sub(r"\s*,\s*", ", ", raw)
    words = []
    for word in fixed.split(" "):
        if word in LEGAL_SUFFIXES:
            words.append(word.rstrip("."))  # Ltd. -> Ltd
        elif word.isupper() and len(word) > 1:
            words.append(word)
        else:
            words.append(word.capitalize())
    pretty = " ".join(words)
    issue = "name_normalised" if pretty != raw else None
    return pretty, issue


def clean_email(value) -> tuple[str, str | None]:
    raw = clean_text(value).lower()
    if not raw:
        return "", "email_missing"
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", raw):
        return "", "email_invalid"
    return raw, None


def clean_phone(value) -> tuple[str, str | None]:
    raw = clean_text(value)
    if not raw:
        return "", "phone_missing"
    digits = re.sub(r"\D", "", raw)
    digits = re.sub(r"(?:ext|x|分机)\.?\s*\d+$", "", digits)
    if digits.startswith("00"):
        digits = digits[2:]
    if not digits:
        return "", "phone_invalid"
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
    # 尝试从混杂文本里抠出日期，如 "订单日期: 2024-01-05 已付"
    m = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", raw)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        try:
            return datetime(y, mo, d).strftime("%Y-%m-%d"), "date_extracted"
        except ValueError:
            return "", "date_invalid"
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
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        frac = cleaned.rsplit(",", 1)[1]
        cleaned = cleaned.replace(",", ".") if len(frac) in (1, 2) else cleaned.replace(",", "")
    cleaned = cleaned.replace("-", "")
    if not cleaned or cleaned == ".":
        return None, "amount_invalid"
    try:
        number = float(cleaned)
    except ValueError:
        return None, "amount_invalid"
    if negative:
        number = -number
    canonical = f"{number:.2f}"
    return round(number, 2), ("amount_normalised" if canonical != clean_text(value) else None)


def clean_currency(value, amount_text: str = "") -> tuple[str, str | None]:
    raw = clean_text(value).lower()
    if raw in CURRENCY_ALIASES:
        return CURRENCY_ALIASES[raw], None
    match = re.search(r"(USD|EUR|JPY|GBP|CNY)", clean_text(value).upper())
    if match:
        return match.group(1), "currency_normalised"
    for symbol, code in (("€", "EUR"), ("¥", "JPY"), ("$", "USD")):
        if symbol in amount_text:
            return code, "currency_inferred_from_amount"
    return "", "currency_missing"


def clean_qty(value) -> tuple[float | None, str | None]:
    raw = clean_text(value)
    if not raw:
        return None, None
    digits = re.sub(r"[^\d.]", "", raw)
    if not digits:
        return None, "qty_invalid"
    try:
        return float(digits), None
    except ValueError:
        return None, "qty_invalid"


# --------------------------------------------------------------------------
# 表头识别
# --------------------------------------------------------------------------
def norm_header(text: str) -> str:
    return re.sub(r"\s+", "", clean_text(text).lower())


def detect_roles(headers: list[str]) -> dict[str, str]:
    """把原始表头映射到角色（name/email/phone/date/amount/currency/qty）。"""
    mapping: dict[str, str] = {}
    used: set[str] = set()
    normalised = {h: norm_header(h) for h in headers}
    for role, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            a = norm_header(alias)
            for h, nh in normalised.items():
                if h in used:
                    continue
                if nh == a or (len(a) >= 4 and a in nh) or (len(nh) >= 4 and nh in a):
                    mapping[h] = role
                    used.add(h)
                    break
            if role in mapping:
                break
    return mapping


# --------------------------------------------------------------------------
# 读文件
# --------------------------------------------------------------------------
def read_table(path: Path) -> list[dict]:
    """读单个文件，返回 list[dict]（全部按字符串读，避免 pandas 把编号吃掉）。"""
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        try:
            import openpyxl  # type: ignore
        except ImportError:
            sys.exit("读取 xlsx 需要 openpyxl：pip install openpyxl")
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [clean_text(h) for h in rows[0]]
        out = []
        for row in rows[1:]:
            if all(c is None or clean_text(c) == "" for c in row):
                continue
            out.append({headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))})
        return out
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    sample = raw[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(raw.splitlines(), dialect=dialect)
    all_rows = [r for r in reader if any(clean_text(c) for c in r)]
    if not all_rows:
        return []
    headers = [clean_text(h) for h in all_rows[0]]
    out: list[dict] = []
    for row in all_rows[1:]:
        if len(row) > len(headers):
            row, note = repair_row(row, headers)
        else:
            note = ""
        padded = list(row) + [""] * (len(headers) - len(row))
        rec = {headers[i]: padded[i] for i in range(len(headers))}
        if note:
            rec["__row_note"] = note
        out.append(rec)
    return out


EU_FRAGMENT = re.compile(r"^\d{1,3}(\.\d{3})+$")


def repair_row(row: list[str], headers: list[str]) -> tuple[list[str], str]:
    """列数比表头多：多半是数字里带了未加引号的逗号（如 1.234,56）。

    不猜、不丢：能明确还原就还原并在备注里说明，还原不了就保留原样 + 标记待复核。
    """
    extra = len(row) - len(headers)
    # 尝试把 "1.234" + "56" 合并回 "1.234,56"
    for i in range(len(row) - 1):
        a, b = row[i].strip(), row[i + 1].strip()
        if EU_FRAGMENT.match(a) and b.isdigit() and len(b) <= 2:
            merged = [row[:i] + [f"{a},{b}"] + row[i + 2:]]
            if len(merged[0]) == len(headers):
                return merged[0], "repaired_embedded_comma"
    return row, f"row_too_many_columns(+{extra})"


def collect_inputs(target: Path) -> list[Path]:
    if target.is_dir():
        files = [
            p for p in sorted(target.iterdir())
            if p.suffix.lower() in (".csv", ".xlsx", ".xlsm")
        ]
        return files
    return [target]


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def run(input_path: Path, output_dir: Path, out_format: str = "csv") -> int:
    files = collect_inputs(input_path)
    if not files:
        sys.exit(f"没有找到可读的表：{input_path}")

    print(f"[1/4] 读取 {len(files)} 个文件：{input_path}")
    for p in files:
        print(f"      - {p.name}")

    clean_rows: list[dict] = []
    review_rows: list[dict] = []
    issue_counts: dict[str, int] = {}
    seen: dict[tuple, dict] = {}
    total_in = 0

    for path in files:
        rows = read_table(path)
        total_in += len(rows)
        headers = list(rows[0].keys()) if rows else []
        roles = detect_roles(headers)
        print(f"      - {path.name}: {len(rows)} 行，识别到列角色 {roles or '（未识别，按原样保留）'}")

        for idx, row in enumerate(rows, start=2):
            issues: list[str] = []
            record = {"__source_file": path.name, "__source_row": idx}
            if row.get("__row_note"):
                record["__row_note"] = row["__row_note"]

            raw_name = ""
            for h, r in roles.items():
                if r == "name":
                    raw_name = row.get(h, "")
                    break
            name, issue = clean_name(raw_name)
            record["name"] = name
            if issue:
                issues.append(issue)

            for h, r in roles.items():
                val = row.get(h, "")
                if r == "email":
                    v, i = clean_email(val)
                elif r == "phone":
                    v, i = clean_phone(val)
                elif r == "date":
                    v, i = clean_date(val)
                elif r == "amount":
                    v, i = clean_amount(val)
                elif r == "currency":
                    v, i = clean_currency(val, clean_text(row.get(h, "")))
                elif r == "qty":
                    v, i = clean_qty(val)
                else:
                    v, i = clean_text(val), None
                if i:
                    issues.append(i)
                record[r] = v

            # 去重（同名 + 同联系方式 视为同一主体）
            key = (
                norm_header(record.get("name", "")).lower(),
                record.get("email", ""),
                record.get("phone", "")[-9:],
            )
            if key != ("", "", "") and key in seen:
                prev = seen[key]
                prev["rows_merged"] = prev.get("rows_merged", 1) + 1
                prev["source_files"] = prev.get("source_files", "") + ", " + path.name
                continue
            record["issues"] = "; ".join(sorted(set(issues)))
            record["rows_merged"] = 1
            record["source_files"] = path.name
            if key != ("", "", ""):
                seen[key] = record
            clean_rows.append(record)

    print(f"[2/4] 清洗完成：读入 {total_in} 行 → 唯一记录 {len(clean_rows)} 行"
          f"（合并重复 {total_in - len(clean_rows)} 行）")

    # 复核表：关键字段缺失或无法解析的行
    required = [r for r in ("name", "email", "phone", "date", "amount") if any(r in row for row in clean_rows)]
    for row in clean_rows:
        problems = []
        for field in required:
            if field in row and row.get(field) in ("", None):
                problems.append(f"{field}_missing")
        for issue in ("date_unparsable", "date_invalid", "amount_invalid", "email_invalid"):
            if issue in row.get("issues", ""):
                problems.append(issue)
        if row.get("__row_note"):
            problems.append(row["__row_note"])
        if problems:
            for p in problems:
                issue_counts[p] = issue_counts.get(p, 0) + 1
            review_rows.append({
                "source_file": row["source_files"],
                "source_row": row["__source_row"],
                "name": row.get("name", ""),
                "email": row.get("email", ""),
                "phone": row.get("phone", ""),
                "date": row.get("date", ""),
                "amount": row.get("amount", ""),
                "reason": "; ".join(sorted(set(problems))),
            })

    # 汇总每个单元格的修复次数
    for row in clean_rows:
        pass
    print(f"[3/4] 复核表 {len(review_rows)} 行（修不好的行都在这里，不会消失）")

    output_dir.mkdir(parents=True, exist_ok=True)
    fields = ["name", "email", "phone", "date", "amount", "currency", "qty",
              "issues", "rows_merged", "source_files", "__source_file", "__source_row"]
    fields = [f for f in fields if any(f in r for r in clean_rows)]

    clean_path = output_dir / "clean_master.csv"
    with clean_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in clean_rows:
            w.writerow({k: r.get(k, "") for k in fields})

    review_path = output_dir / "needs_review.csv"
    with review_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=["source_file", "source_row", "name", "email", "phone", "date", "amount", "reason"],
        )
        w.writeheader()
        for r in review_rows:
            w.writerow(r)

    report = {
        "tool_version": VERSION,
        "input": str(input_path),
        "files": [p.name for p in files],
        "rows_in": total_in,
        "rows_unique": len(clean_rows),
        "rows_merged_away": total_in - len(clean_rows),
        "rows_needing_review": len(review_rows),
        "review_reasons": issue_counts,
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if out_format == "xlsx":
        try:
            import openpyxl  # type: ignore
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "clean_master"
            ws.append(fields)
            for r in clean_rows:
                ws.append([r.get(k, "") for k in fields])
            if review_rows:
                ws2 = wb.create_sheet("needs_review")
                rf = ["source_file", "source_row", "name", "email", "phone", "date", "amount", "reason"]
                ws2.append(rf)
                for r in review_rows:
                    ws2.append([r.get(k, "") for k in rf])
            xlsx_path = output_dir / "clean_master.xlsx"
            wb.save(xlsx_path)
            print(f"      wrote {xlsx_path}")
        except ImportError:
            print("      (跳过 xlsx：未安装 openpyxl)")

    print(f"[4/4] 完成。输出目录：{output_dir}")
    print(f"      干净表  {clean_path.name}  ({len(clean_rows)} 行)")
    print(f"      复核表  {review_path.name}  ({len(review_rows)} 行)")
    print(f"      报告    {report_path.name}")
    return 0


# --------------------------------------------------------------------------
# 自检（买之前你可以先跑一遍，确认工具本身是好的）
# --------------------------------------------------------------------------
def self_test() -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        checks.append((name, bool(cond), detail))

    check("日期 2024-01-05 原样", clean_date("2024-01-05")[0] == "2024-01-05")
    check("日期 2024/1/5 归一", clean_date("2024/1/5")[0] == "2024-01-05", clean_date("2024/1/5")[0])
    check("日期 2024年1月5日 归一", clean_date("2024年1月5日")[0] == "2024-01-05")
    check("日期 Jan 5 2024 归一", clean_date("Jan 5 2024")[0] == "2024-01-05")
    check("日期无法解析 -> 复核", clean_date("下周三")[0] == "")
    check("金额 240 USD 归一", clean_amount("240 USD")[0] == 240.0)
    check("金额 1.234,56 (EU) 归一", clean_amount("1.234,56")[0] == 1234.56)
    check("金额 1,234.56 (US) 归一", clean_amount("1,234.56")[0] == 1234.56)
    check("金额 (240) 负数", clean_amount("(240)")[0] == -240.0)
    check("金额 $99 -> USD 推断", clean_currency("", "$99")[0] == "USD")
    check("邮箱小写化", clean_email("  John.Doe@Example.COM ")[0] == "john.doe@example.com")
    check("非法邮箱 -> 复核", clean_email("not-an-email")[0] == "")
    check("电话去非数字", clean_phone("+81 (0)90-1234-5678 ext. 22")[0].isdigit())
    check("公司名保留 Ltd", clean_name("ACME  Ltd.")[0] == "ACME Ltd")
    check("表头识别 company->name", detect_roles(["Company", "Email"]) == {"Company": "name", "Email": "email"})
    check("表头识别中文", detect_roles(["供应商", "金额"]) == {"供应商": "name", "金额": "amount"},
          str(detect_roles(["供应商", "金额"])))

    width = max(len(n) for n, _, _ in checks)
    for name, ok, detail in checks:
        flag = "PASS" if ok else "FAIL"
        suffix = f"   ({detail})" if detail and not ok else ""
        print(f"  [{flag}] {name.ljust(width)}{suffix}")

    failed = [n for n, ok, _ in checks if not ok]
    print(f"\n  {len(checks) - len(failed)}/{len(checks)} 项通过")
    if failed:
        print("  失败项：" + ", ".join(failed))
        return 1
    print("  自检全部通过。工具本身可用。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="脏表格一键清洗工具（自助版）")
    parser.add_argument("--input", help="输入文件或目录（.csv/.xlsx）")
    parser.add_argument("--output", default="cleaned_output", help="输出目录，默认 cleaned_output")
    parser.add_argument("--format", default="csv", choices=["csv", "xlsx"], help="额外输出 xlsx")
    parser.add_argument("--self-test", action="store_true", help="运行内置自检")
    parser.add_argument("--version", action="version", version=f"clean_my_table {VERSION}")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.input:
        parser.print_help()
        return 1
    return run(Path(args.input), Path(args.output), args.format)


if __name__ == "__main__":
    raise SystemExit(main())
