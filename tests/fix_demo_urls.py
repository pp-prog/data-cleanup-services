#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 README 里的演示动图引用从「仓库相对路径」改成「GitHub Pages 绝对地址」。

背景（2026-10-25）：
  README 里写 ![...](demos/x.gif) 时，GitHub 会把图片解析到
  raw.githubusercontent.com —— 这个域名在国内实测不可达（curl http=000），
  也就是「挂上了演示，但国内访客看到的是裂图」。
  同一批文件同时由 GitHub Pages 提供（同源，落地页就在这个域上，实测 3/3 = 200），
  所以改指 Pages 绝对地址，两边都能显示。

只做字面量替换，不碰任何其它空白/内容。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://pp-prog.github.io/data-cleanup-services/demos/"

changed = []

# 1) 主 README：<img src="demos/xxx.gif" ...>  -> 绝对地址
main = ROOT / "README.md"
text = main.read_text(encoding="utf-8")
new_text, n = re.subn(
    r'src="demos/([^"]+\.gif)"',
    lambda m: 'src="%s%s"' % (BASE, m.group(1)),
    text,
)
if n:
    main.write_text(new_text, encoding="utf-8", newline="\n")
    changed.append(("README.md", n))

# 2) 各 sample README：![...](../../demos/xxx.gif) -> 绝对地址
for md in sorted((ROOT / "samples").rglob("README.md")):
    text = md.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r'\]\(\.\./\.\./demos/([^)]+\.gif)\)',
        lambda m: '](%s%s)' % (BASE, m.group(1)),
        text,
    )
    if n:
        md.write_text(new_text, encoding="utf-8", newline="\n")
        changed.append((md.parent.name, n))

for name, n in changed:
    print("updated %-34s %d 处" % (name, n))
if not changed:
    print("无需改动")
    sys.exit(0)

# 3) 校验：不得再有相对引用
bad = []
for md in [main] + sorted((ROOT / "samples").rglob("README.md")):
    t = md.read_text(encoding="utf-8")
    for m in re.finditer(r'(?:src="|\]\()((?:\.\./\.\./)?demos/[^")]+)', t):
        bad.append("%s -> %s" % (md.relative_to(ROOT), m.group(1)))
if bad:
    print("!! 仍有相对引用：")
    for b in bad:
        print("   " + b)
    sys.exit(1)
print("校验通过：所有演示图引用均已指向 Pages 绝对地址")
