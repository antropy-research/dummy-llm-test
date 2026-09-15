# Third-party sources

本项目源代码采用 MIT；下列第三方文件保持其原有许可。完整下载 URL、提交和 SHA-256 位于 `src/dummy_llm_test/data/sources.json`，执行 `dummy-llm-test doctor` 可核验。

| 来源 | 固定提交 | 使用内容 | 许可 |
|---|---|---|---|
| xqy2006/ModelTrace | `60949ef522a84f66b1236b459308b48028d36949` | 未修改的 `fingerprint.py`、`unified_bank.json`，以及由本地适配器复现的挑战模板 | [MIT 原文](src/dummy_llm_test/data/licenses/modeltrace.txt)，Copyright (c) 2026 xqy2006 |
| huggingface/OpenEnv | `da5929566e99c8eb376a47042b316cb13c0aae29` | 未修改的 `tasks.py` 任务目录 | [BSD-3-Clause 原文](src/dummy_llm_test/data/licenses/openenv.txt) |
| simple-bench/SimpleBench | `fbc2e429085bdedad7d1a236d2bc9bc18c95f16e` | 10 题公开 JSON 与 system prompt | [MIT 原文](src/dummy_llm_test/data/licenses/simplebench.txt) |
| petergpt/bullshit-benchmark | `2678ac296fe6e234d391e0f4ab339f6a777ba2a3` | `questions.v2.json` 的 100 题及参考说明 | [MIT 原文](src/dummy_llm_test/data/licenses/bullshitbench.txt) |
| unryuu/idiot | `01070f7854ff5c3b0722060a4e7e51417ebe2eba` | Collatz 原始题目和配套说明 | [MIT 原文](src/dummy_llm_test/data/licenses/collatz.txt) |
| haowang02/codex-candy-eval | `4dde0a9e8043c9f84e5e810c4f7cdd555751a20c` | 从源码静态提取的数学题陈述；本项目自行实现运行与验证 | 上游未声明许可；未复制其脚本，题目来源归属保留，不宣称上游脚本属于本项目 MIT |
| simonw/pelican-bicycle | 调研快照 `a0cfd51f5838613d486f93c24ee77ec2690f3400` | 简短原始绘图提示与作者归属 | 未复制示例 SVG 或脚本；不宣称上游作品属于本项目 MIT |

IFEval、RULER 等项目用于方法参考，没有引入其代码或数据。ModelTrace 的上游参考模型标签和数据来源不等于本项目对身份的独立认证。人工评分结果与原项目的自动裁判分数属于不同协议。
