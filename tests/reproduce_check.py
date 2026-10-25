#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
复现性闸门：把"所有输出都是真实跑出来的"从一句承诺变成一条可执行的不变量。

做法：
  1. 记住仓库里已提交的输出文件（内容 + sha256）
  2. 重新跑一遍 4 套样品
  3. 比对重新生成的输出：
       - 忽略 run_at_utc / elapsed_seconds / 生成时间戳 等"运行元数据"
       - 其余任何差异 = 失败（说明输出不可复现，样品的可信度就是假的）

退出码：
  0 = 全部样品可复现
  1 = 存在差异 / 某套样品运行失败
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"

# 视为"运行元数据"的字段：每次跑必然不同，不参与比对
VOLATILE = re.compile(
    r"(run_at_utc|elapsed_seconds|generated_at|timestamp|_at_utc|run_at)", re.IGNORECASE
)

# 每个样品：(目录, 运行命令, 需要比对的输出文件)
CASES = [
    (
        "sample-1-python-automation",
        [["python", "make_xlsx_input.py"], ["python", "merge_clean.py"]],
        ["output/clean_master.csv", "output/run_summary.csv"],
    ),
    (
        "sample-2-web-scraping-cleanup",
        [["python", "scrape_offline.py"]],
        ["output/products_clean.csv", "output/field_mapping.json"],
    ),
    (
        "sample-3-ai-agent-api-workflow",
        [["python", "workflow.py"]],
        ["output/extracted_records.json", "output/report_draft.md"],
    ),
    (
        "sample-4-hotel-booking-cleanup",
        [["python", "clean_bookings.py"], ["python", "verify_output.py"]],
        ["output/hotel_bookings_clean.xlsx", "output/needs_review.csv"],
    ),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def xlsx_content(path: Path) -> bytes:
    """xlsx 是 zip，条目带时间戳 → 逐字节比对必然不稳定。
    只取单元格内容（worksheets / sharedStrings 的 XML）来比。"""
    import zipfile

    parts = []
    with zipfile.ZipFile(path) as zf:
        for name in sorted(zf.namelist()):
            if name.startswith("xl/worksheets/") or name in (
                "xl/sharedStrings.xml",
                "xl/workbook.xml",
            ):
                parts.append(name.encode("utf-8"))
                parts.append(zf.read(name))
    return b"\x00".join(parts)


def strip_volatile(path: Path) -> bytes:
    """把易变字段剔除后再比对。xlsx 走单元格内容比对，不走字节比对。"""
    if path.suffix.lower() == ".xlsx":
        return xlsx_content(path)
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    lines = []
    for line in text.splitlines():
        if VOLATILE.search(line):
            continue
        lines.append(line)
    return "\n".join(lines).encode("utf-8")


def main() -> int:
    failures = []
    checked = 0

    for folder, commands, outputs in CASES:
        work = SAMPLES / folder
        if not work.is_dir():
            failures.append(f"[SKIP] {folder}: 目录不存在")
            continue

        # 1) 记录当前（已提交状态）的内容
        before = {}
        for rel in outputs:
            p = work / rel
            if p.exists():
                before[rel] = strip_volatile(p)

        # 2) 重跑
        for cmd in commands:
            try:
                proc = subprocess.run(
                    cmd, cwd=work, capture_output=True, text=True, timeout=300
                )
            except subprocess.TimeoutExpired:
                failures.append(f"[FAIL] {folder}: `{cmd}` 超时")
                break
            except FileNotFoundError:
                failures.append(f"[FAIL] {folder}: 找不到可执行文件 {cmd[0]}")
                break
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
                failures.append(
                    f"[FAIL] {folder}: `{' '.join(cmd)}` 退出码 {proc.returncode} :: {' | '.join(tail)}"
                )
                break
        else:
            # 3) 比对
            for rel in outputs:
                p = work / rel
                if not p.exists():
                    failures.append(f"[FAIL] {folder}: 运行后仍缺输出 {rel}")
                    continue
                if rel not in before:
                    failures.append(f"[WARN] {folder}: {rel} 之前不存在，无法比对（已生成）")
                    continue
                after = strip_volatile(p)
                checked += 1
                if after != before[rel]:
                    failures.append(
                        f"[FAIL] {folder}: {rel} 不可复现（内容与已提交版本不一致）"
                    )

    print("=" * 62)
    print("复现性闸门 · reproduce_check")
    print("=" * 62)
    for f in failures:
        print(f)
    print("-" * 62)
    if failures:
        print(f"结论: FAIL —— {len(failures)} 项问题（比对文件数 {checked}）")
        print("含义: 样品的『输出是真实跑出来的』这句话站不住，README 承诺失效。")
        return 1
    print(f"结论: PASS —— {checked} 个输出文件全部可复现（已剔除运行时间戳类字段）")
    print("含义: README 的『所有输出都是真实跑出来的』现在是可执行的不变量，不是承诺。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
