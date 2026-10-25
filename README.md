# data-cleanup-services

四套可运行的真实样品工程：表格清洗与多表合并 / 网页抓取与结构化 / 文档抽取工作流 / 复杂历史表格修复。
每套包含**源码 + 输入 + 输出 + 自检结果**，所有输出都是真实跑出来的。

作品集主页（GitHub Pages）：<https://pp-prog.github.io/data-cleanup-services/>

## 目录

| 样品 | 内容 | 价格（起） |
|---|---|---|
| [`samples/sample-1-python-automation`](samples/sample-1-python-automation) | 4 家供应商 4 种表头/日期/币种 → 干净主表 + 运行摘要 | ¥39 / $15 |
| [`samples/sample-2-web-scraping-cleanup`](samples/sample-2-web-scraping-cleanup) | 抓取 → 按 SKU 去重 → 规范化 CSV + 字段映射 | ¥59 / $25 |
| [`samples/sample-3-ai-agent-api-workflow`](samples/sample-3-ai-agent-api-workflow) | 批量文档 → 抽取 → JSON + 报告（无 Key 自动 MOCK） | ¥49 / $20 |
| [`samples/sample-4-hotel-booking-cleanup`](samples/sample-4-hotel-booking-cleanup) | 48 表 / 6 表头 / 6 日期格式 → 833 清洗 + 571 复核 + 17 项自检 | ¥99 / $30 |

## 看一眼效果（真实运行录屏，非截图拼贴）

<table>
<tr>
<td align="center" width="50%"><img src="https://pp-prog.github.io/data-cleanup-services/demos/demo-1-python-automation.gif" width="420"><br><b>1 · 表格合并清洗</b><br>4 家供应商 4 种表头 → 干净主表</td>
<td align="center" width="50%"><img src="https://pp-prog.github.io/data-cleanup-services/demos/demo-2-web-scraping-cleanup.gif" width="420"><br><b>2 · 网页抓取与清洗</b><br>抓取 → 按 SKU 去重 → 规范化 CSV</td>
</tr>
<tr>
<td align="center"><img src="https://pp-prog.github.io/data-cleanup-services/demos/demo-3-ai-agent-api-workflow.gif" width="420"><br><b>3 · 文档抽取工作流</b><br>批量文档 → 抽取 → JSON + 报告</td>
<td align="center"><img src="https://pp-prog.github.io/data-cleanup-services/demos/demo-4-hotel-booking-cleanup.gif" width="420"><br><b>4 · 历史表格修复</b><br>48 表 → 833 清洗 + 571 复核</td>
</tr>
</table>

全部录屏可用仓库里的脚本原样复现（命令见「本地运行」），原始文件在 [`demos/`](demos)。

## 自己验一遍（30 秒）

README 说"所有输出都是真实跑出来的"——这句话是可以被验证的，不只是承诺。

```bash
git clone https://github.com/pp-prog/data-cleanup-services
cd data-cleanup-services
python tests/reproduce_check.py     # 重跑 4 套样品，逐个比对已提交的输出
```

期望输出：`结论: PASS —— 8 个输出文件全部可复现（已剔除运行时间戳类字段）`
退出码 `0` = 可复现；`1` = 有输出对不上 —— 此时 README 这句话就是假的。
（比对时忽略 `run_at_utc` / `elapsed_seconds` 这类每次必然不同的运行元数据；xlsx 比对的是单元格内容而非字节，因为 zip 元数据每次都不同。）

> 重跑后 `git status` 会显示 3 个输出文件被修改（两个 `.xlsx` 的 zip 时间戳 + `run_summary.csv` 的 `run_at_utc`/`elapsed_seconds`）。这是运行元数据，不是内容变化 —— 上面这个闸门就是用来把两者区分开的。

## 在线表格清洗器（打开网页就能用 · 零下载零安装）

<https://pp-prog.github.io/data-cleanup-services/clean.html>

- 文件**不离开你的电脑**：不上传、不注册、不下载，浏览器本地跑完。
- 干同样的活：中文表头自动识别、欧式数字 `1.234,56 → 1234.56`、合并行识别、脏行进「待复核」而不是悄悄丢掉。
- 想先试手感就用这个；要批量处理或离线跑，用下面的命令行版。

## 脏表格一键清洗工具 v1.0（自助版，MIT）

一条命令把乱表洗成干净表 + 复核表 + 报告。纯标准库，内置 16 项自检。

- 落地页：<https://pp-prog.github.io/data-cleanup-services/toolkit.html>
- 下载（推荐·同源稳定）：<https://pp-prog.github.io/data-cleanup-services/table-cleaner-toolkit-v1.0.0.zip>
- 备用下载（CDN 镜像）：<https://gcore.jsdelivr.net/gh/pp-prog/data-cleanup-services@master/table-cleaner-toolkit-v1.0.0.zip>
- 兜底（GitHub Release，国内可能慢）：<https://github.com/pp-prog/data-cleanup-services/releases/download/v1.0.0-toolkit/table-cleaner-toolkit-v1.0.0.zip>
- 零依赖单文件源码：<https://pp-prog.github.io/data-cleanup-services/clean_my_table.py>
- 自检：`python clean_my_table.py --self-test`

## 两条规矩

1. **不编造数据** —— 无法核实的行不填值，落到 review 表让你看见。
2. **不静默丢行** —— 修不好的行进复核清单，不会悄悄消失。

## 本地运行

```bash
# 样品 1：合并清洗
cd samples/sample-1-python-automation && python make_xlsx_input.py && python merge_clean.py

# 样品 2：抓取 + 清洗（离线 mock，无需联网）
cd samples/sample-2-web-scraping-cleanup && python scrape_offline.py

# 样品 3：文档抽取（默认 MOCK 模式，不调用任何外部 API）
cd samples/sample-3-ai-agent-api-workflow && python workflow.py

# 样品 4：历史表格修复 + 自检
cd samples/sample-4-hotel-booking-cleanup && python clean_bookings.py && python verify_output.py
```

Python 3.10+。除样品 3 的 live 模式需要 `LLM_API_KEY` 环境变量外，其余只依赖标准库与 pandas/openpyxl（见各目录 `requirements.txt`）。

## 联系方式

- **询价 / 需求（推荐，直接在 GitHub 提 issue，标题模板已预填）**：
  <https://github.com/pp-prog/data-cleanup-services/issues/new?title=%E8%AF%A2%E4%BB%B7%EF%BC%9A%E4%BD%A0%E7%9A%84%E9%9C%80%E6%B1%82%20%2B%20%E7%9B%AE%E6%A0%87%E5%AD%97%E6%AE%B5>
- 微信或闲鱼私聊：见 [作品集主页](https://pp-prog.github.io/data-cleanup-services/)

> 本仓库内容全部为演示用合成数据与自建样例，不含任何真实客户数据、凭据或身份信息。
