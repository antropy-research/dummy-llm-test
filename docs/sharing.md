# 导出可分享报告

```bash
uv run dummy-llm-test share export runs/YOUR_RUN --output shared-report
```

输出目录必须不存在且位于原运行目录之外。导出只读原记录，在新目录生成：

- `index.html`：无需服务器或密钥，直接用浏览器打开。
- `share.json`：版本化的匿名统计数据。
- `README.txt`：分享边界说明。

无需密钥的[合成示例](../examples/shared-report/index.html)已随仓库提供。
GitHub 展示 HTML 源码；克隆后在本地打开即可。可重新生成：

```bash
uv run python scripts/make_performance_example.py --shared --output runs/share-demo
```

示例全部由固定合成数据产生，不是真实模型成绩。

## 保留与排除

保留逐题客观分数、独立人工评分、调用状态、耗时/token/TPS、重试、分位数、覆盖率、
图表、各执行片段吞吐和并发观测。目标、题号、题集、样本、片段重新分配局部别名；
不导出真实名称或反向映射，也不产生跨导出的稳定匿名身份。

采用**字段白名单**重新构造数据，不靠查找密钥样式进行全文替换。自由文本均不复制，
包括原始回答、提示词、SVG、评分解释、评阅备注和评阅者；也不复制地址、模型身份、
路径、配置、原始事件、请求、错误正文、绝对 UTC 时间或原文件哈希。
未知状态变为 `other`，未知人工维度不导出；数值只接受有限非负数，缺失保持 `null`。
HTML 无脚本/外部请求，内置 CSP 限制资源加载。

`share.json` 的 `kind = sanitized_statistics_not_raw_evidence`，不是标准运行目录。
它不能续跑、重判、重新审阅原答案或认证模型身份。知识截止日期原文和 ModelTrace
候选模型名称本版不导出，避免身份信息混入公开统计。

本导出仍会公开成绩、输出长度、故障率、题目数量和性能特征。分享前应检查这些统计
是否适合公开；字段白名单不代表统计本身不存在隐私信息。需要定位具体题目或模型时，
由提交者在问题描述里主动提供适合公开的最小配置和合成复现。

普通 `report.html` 和 `review export` **不是**脱敏分享包，前者包含原始回答，后者
虽隐藏模型身份仍保留题目、回答和评阅材料。不要直接上传整个 `runs/`。
