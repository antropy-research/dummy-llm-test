# 使用 agent 持续开发

本项目把评测协议作为产品契约。开发 agent 可以重构实现，但不能为了修复测试、
提高分数或加速运行而悄悄改变问题、答案、模型参数或实验条件。

## 指令入口与技能

- [AGENTS.md](../AGENTS.md)：短小的共享约定、模块入口和代码审查重点。
- [CLAUDE.md](../CLAUDE.md)：引导 Claude Code 读取同一套约定，避免维护两套冲突规则。
- [.agents/skills](../.agents/skills)：三个按任务加载的技能，分别负责评测协议、运行可靠性、发布证据检查。

Codex 官方约定是从仓库的 `.agents/skills` 发现技能，并读取项目 `AGENTS.md`。
因此这些文件随仓库分发，不依赖维护者的个人全局配置；具体发现行为取决于客户端版本。
若当前客户端尚未展示新技能，可重启会话，或要求 agent 直接读取对应 SKILL.md。
参见 [官方技能说明](https://learn.chatgpt.com/docs/build-skills)及
[AGENTS.md 说明](https://learn.chatgpt.com/docs/agent-configuration/agents-md)。

其他编码 agent 可以直接读取 AGENTS.md 和被引用的技能，不要求安装某个插件。
这些文件约束的是**维护仓库的 agent**，不会被评测运行器拼入被测提示词。被测 CLI
仍在仓库外的独立临时目录中运行；不在机器全局安装这些开发技能，以减少实验污染。
技能和文档链接检查只能证明格式及文件有效，不能证明所有客户端都已正确加载指令。

## 修改入口与验证

| 任务 | 主要实现 | 有意义的验证 |
|---|---|---|
| 新题、答案、提示词 | `catalog.py`、`scoring.py`、`data/` | `test_catalog_scoring.py`：独立 oracle、严格答案、原题/变体区分、提示词泄漏 |
| ModelTrace | `fingerprint.py`、固定 `vendor/modeltrace.py` 和指纹库 | `test_fingerprint.py`：同库上游差分、0–3 有效回答、不兼容库 |
| API / CLI | `adapters.py` | `test_adapters.py`：实际协议、拒答/截断/工具事件、隔离目录、超时 |
| 并发 / 中断 / 预算 | `scheduler.py`、`runner.py` | `test_scheduler.py` + `test_runner_review.py`：同步事件控制的慢请求、并发上限、SIGINT、落盘与续跑 |
| 配置 / 命令 | `config.py`、`cli.py` | `test_cli_config.py`：配置优先级、非法参数、dry-run 与退出码 |
| 报告 / 人工评阅 / 比较 | `report.py`、`core.py` | `test_runner_review.py`：评分往返、盲评、来源、不兼容基线不产生误导比较 |
| 兼容签名 / 分享 / 分发 | `contracts.py`、`sharing.py`、`scripts/check_dist.py`（仓库根目录下） | `test_contracts_sharing.py`：续跑条件、旧协议、私密字段排除；发行包实际构建与仓库外安装 |
| 性能 / 流式观测 | `performance.py`、`performance_report.py`、`streaming.py` | `test_performance.py`、`test_streaming.py`：单调时钟、SSE 到达、部分响应、重试等待、片段并发、比较条件 |

路径相对于 `src/dummy_llm_test/`；测试相对于 `tests/`。当某次变更跨多个模块，
组合相关验证，不把这张表理解成只能运行单个测试文件。

```bash
uv sync --frozen
uv run python scripts/check_repo.py
# 仅文档/技能/来源契约检查，不运行 lint 和 pytest：
uv run python scripts/check_repo.py --contracts-only
```

完整检查运行本地文档链接、技能元数据、第三方校验值、包版本一致性、Ruff 和
自动测试，**不调用任何模型**。CI 使用同一入口，避免“文档建议做、实际无人做”。
源文件更新必须有可追溯的固定版本；不要顺手执行全部来源下载来消除校验差异。
发布构建另用 `uv build`，保持测试与发布动作分离。

## 可复用的任务提示

以下是任务起点，实际用户请求优先；不要求每次任务都填满模板。

**修复问题：**

> 阅读 AGENTS.md，复现以下问题并修复：[现象/最小命令]。先判断是请求、调度、
> 解析、判分还是报告的问题。保留现有评测条件及原始记录，用最小离线样例验证；
> 说明改动、兼容性和实际执行的检查。[如已授权真实验证，填写目标与调用范围。]

**新增评测：**

> 使用 $eval-protocol-change 集成 [来源/任务]。区分原题复现与扩展，核验许可、
> 固定版本、原始提示词及独立答案。开放题保持人工评阅。说明题库覆盖、各档位
> 调用数及与历史结果的可比性，避免为了加题而改变旧题含义。

**优化运行：**

> 使用 $eval-runtime-change 实现 [目标行为]。保留每次尝试、先预留预算后派发、
> 已返回结果持久化和仅补缺失样本。用可控慢请求、异常与中断测试验证，不用一次
> 真实模型响应快慢作为并发正确性的证据。

**交付审查：**

> 使用 $eval-release-check 审查当前变更。重点检查证据可信性、安装后可用性、
> 私有信息、来源许可和兼容性。给出可以复现的问题及验证结果。
> [根据本次需要明确是否提交、推送或发布；未授权的外部动作不要推断。]

## 让约定保持有效

新增规范应对应可复现的问题或稳定产品约束。优先把可机械验证的规则写进测试
或检查脚本，把判断标准写进技能；不要不断增加“任何改动都必须……”的全局规则。
一次性实验过程放在对应验证记录中，不永久塞进 AGENTS.md。

修改这些指令时检查任务触发范围、与其他指令的冲突及是否引入了额外授权要求。
小改动可直接审查；复杂技能可在明确授权的隔离环境中验证真实使用行为，不把
frontmatter 校验通过等同于行为验证。已授权的正常开发不需要再因技能重复求确认。
