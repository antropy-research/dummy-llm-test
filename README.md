# dummy-llm-test

中文 · [English](README.en.md)

社区验智、模型指纹与能力回归工具。统一运行 API、Codex CLI 和 Claude Code，保存可复查的回答与报告。**开放题全部人工评阅，无模型裁判费用。**

## 从 0 到 1

需要 macOS / Linux、Python 3.11+ 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。CLI 入口需要先安装、登录对应工具。

```bash
git clone git@github.com:antropy-research/dummy-llm-test.git
cd dummy-llm-test
uv sync --frozen

# 默认使用本机 Codex 登录；只读检查不会调用模型。
uv run dummy-llm-test doctor
uv run dummy-llm-test run --level quick

# 查看完整调用计划，再按需要执行。
uv run dummy-llm-test run --level full --dry-run
uv run dummy-llm-test run --level full
uv run dummy-llm-test run --level fingerprint
```

运行结束会打印 HTML 报告的绝对路径。也可打开 `runs/latest/report.html`。本地报告无需服务端或联网，原始运行数据默认不提交 Git。

报告直接展示尝试/样本耗时、TPS、重试、分位数、用量覆盖率、分布图及并发吞吐。
API 目标配置 `stream: true` 可采集正文增量的到达时间；CLI 当前不支持这些流式时间指标。
旧运行可离线分析：`uv run dummy-llm-test performance analyze runs/OLD --output runs/OLD-performance`。
字段、公式和比较条件见[性能说明](docs/performance.md)，缺失指标不会显示为零。

| 档位 | 默认每个目标的评测调用数 | 内容 |
|---|---:|---|
| `quick` | 5 | 糖果、鹈鹕、知识截止日期、小数比较、字符计数 |
| `full` | 189 | 全部启用题目，含 ModelTrace 三条挑战 |
| `fingerprint` | 3 | ModelTrace 候选库内指纹匹配 |
| `reasoning` | 135 | 45 道客观题，各重复 3 次；见配置文件 |

完整题库含糖果 10、SVG 31、知识日期 2、基础易错 12、Collatz 1、SimpleBench 公开集 10、BullshitBench V2 100、指令遵循 12、上下文检索 8、ModelTrace 3。131 道开放题需要人工评阅；`full` 完成调用不等于人工评分已完成。

## 分享与开源协作

```bash
uv run dummy-llm-test share export runs/YOUR_RUN --output shared-report
```

打开输出的 `index.html` 即可分享匿名统计；回答、私有地址、本机路径和模型身份不导出。
[无需密钥的合成示例](examples/shared-report/index.html)可在克隆后本地打开，
[分享说明](docs/sharing.md)列出保留字段与隐私边界。

0.4.0 起新运行拆分实验与运行签名，报告样式变更不影响可比性；续跑可调整并发，
性能条件按样本保留。详见[兼容规则](docs/compatibility.md)和[接入证据矩阵](docs/compatibility-matrix.md)。
[贡献指南](CONTRIBUTING.md)、[安全报告](SECURITY.md)和[版本交付流程](docs/releasing.md)
供持续维护使用；agent 开发约定见 [AGENTS.md](AGENTS.md)。

## 配置 API 或其他 CLI

```bash
cp config.yaml config.local.yaml
# 编辑 config.local.yaml 的 targets.api：填写 base_url、model、api_key_env。
# 在本机环境中设置对应密钥；不要把密钥放进 YAML、命令参数或 Git。
uv run dummy-llm-test doctor --target api
uv run dummy-llm-test run --level quick --target api
uv run dummy-llm-test run --level quick --target claude

# 显式选用 Responses 协议：先填写 targets.responses。
uv run dummy-llm-test run --level fingerprint --target responses

# 保留 CLI 本地设置和工具的日常模式，单独报告。
uv run dummy-llm-test run --level quick --target codex --mode native

# 多目标、重复测试。
uv run dummy-llm-test run --level quick --target codex --target claude --repetitions 3

# 最多 4 个评测调用同时运行，完成一题即补位。
uv run dummy-llm-test run --level full --concurrency 4
```

自动优先读取 `config.local.yaml`；否则读取 `config.yaml`。显式配置选项放在子命令前：`dummy-llm-test --config my.yaml run --level quick`。完整字段、协议差异、预算与自定义题见 [配置说明](docs/configuration.md)。

顶层 `concurrency` 默认 1；每个目标还可配置自己的 `concurrency` 上限，多个目标轮转派发。
运行期间会显示已完成数、在途题目和耗时。按 Ctrl+C 后停止新派发，等待在途请求返回或超时，
保存结果及报告后退出；保持相同配置和并发参数即可续跑。原始运行不会因中断而自动重试答错。

## 人工评阅与历史对比

```bash
uv run dummy-llm-test review export runs/RUN_ID --output runs/review-pack
# 打开 runs/review-pack/index.html；填写评阅者及分数，下载 review-scored.json。
uv run dummy-llm-test review import runs/RUN_ID /path/to/review-scored.json

uv run dummy-llm-test compare --baseline runs/OLD_ID --current runs/NEW_ID
uv run dummy-llm-test run --resume runs/RUN_ID

# 升级评分器后只重判已有回答，不再调用模型，也不覆盖原记录。
uv run dummy-llm-test regrade runs/RUN_ID --output runs/REGRADED_ID
```

续跑只补齐未完成记录，已记录的超时、拒答和错误不会自动重跑。若需要新样本，开始新运行。重新判分保存来源、原始分数及新评分器校验值；派生运行不能继续调用模型。

## 单独使用 ModelTrace

```bash
uv run dummy-llm-test fingerprint export --seed 42 --output runs/challenges.json
# 把三条 prompt 分别发给同一模型的新会话；填写相邻 challenges-answers.json。
uv run dummy-llm-test fingerprint analyze \
  --challenges runs/challenges.json \
  --answers runs/challenges-answers.json \
  --output runs/fingerprint-analysis.json
```

可用 `--bank` 指定兼容的本地指纹库。API/CLI 自动采集使用 `run --level fingerprint`；导入回答时工具使用情况由导入者声明。结果是**当前候选库内的匹配概率**，未收录模型也会匹配已有候选，不能充当身份认证。

## 如何读结果

- 客观题：严格最终答案或明确的程序化规则；糖果额外显示上游宽松兼容分。
- SVG / BullshitBench：待人工评阅；合法 SVG 不等于画得正确。
- 知识截止日期：只记录自述，无统一正确答案。
- ModelTrace：独立的身份线索，不进入能力正确率。
- 超时、截断、认证失败、拒答、工具违规：分别记录；没有评分不代表零分。

快速档只用于筛查。单题、自报日期、响应速度和指纹概率都不能独立证明模型“降智”。测试模式、系统提示、推理参数及题库版本不同的结果不能直接作回归结论。

## 文档与验证

- [综合调研与选型](docs/research.md)
- [配置及扩展](docs/configuration.md)
- [方法、判分与证据边界](docs/methodology.md)
- [0.4.0 P1 验证](docs/validation-0.4.md) · [0.3.0 性能验证](docs/validation-0.3.md) · [0.2.0 验证记录](docs/validation-0.2.md) · [首次交付真实调用记录](docs/validation.md)
- [第三方来源及许可](THIRD_PARTY_NOTICES.md)
- [Agent 开发约定与任务模板](docs/agent-development.md)
- [性能字段、支持矩阵与公式](docs/performance.md)
- [贡献指南](CONTRIBUTING.md) · [变更记录](CHANGELOG.md)

```bash
uv run --frozen python scripts/check_repo.py
```

自动测试使用固定数据和模拟响应，不需要 API key，不进行付费调用。源代码采用 MIT；第三方内容保持各自许可和来源说明。
