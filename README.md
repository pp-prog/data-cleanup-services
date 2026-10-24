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

演示动图：[`demos/`](demos)

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

需求 / 报价 / 合作：微信或闲鱼私聊（见 [作品集主页](https://pp-prog.github.io/data-cleanup-services/)）。

> 本仓库内容全部为演示用合成数据与自建样例，不含任何真实客户数据、凭据或身份信息。
