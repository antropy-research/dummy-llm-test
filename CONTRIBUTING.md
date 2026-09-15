# Contributing

欢迎问题报告、适配器修复、评测来源研究和文档改进。使用 agent coding 时先读
[AGENTS.md](AGENTS.md)；工作流及提示模板见[开发指南](docs/agent-development.md)。

1. 报告问题时给出版本、目标协议/CLI 版本、controlled/native、最小配置和实际状态。
   用环境变量名替代密钥，使用合成回答复现；不要上传私有 `runs/` 或个人配置。
2. 修改实现时保留原题与变体的区别、人工评分边界及原始运行证据。新题注明来源、
   固定版本、许可、判分依据和独立答案核验；新增数据不自动代表可以重新分发。
3. 提交前运行 `uv run python scripts/check_repo.py`。更新改变的 CLI/YAML 行为说明，
   对兼容性变化给出迁移建议。测试不得使用维护者机器上的模型凭据。
4. PR 描述说明问题、修改后的行为、实际验证与已知限制。真实调用、模拟测试、
   人工评分与离线重判分别描述；不要用测试通过代替模型能力结论。

项目当前以 macOS / Linux、Python 3.11+ 为开发基线。Windows 原生进程与锁管理
尚未适配。开发者无需 API key 即可运行自动测试。


## English contributor guide

Start with [AGENTS.md](AGENTS.md) and the [module/test map](docs/agent-development.md).
Install with `uv sync --frozen`; run `uv run python scripts/check_repo.py` before
submitting. Tests require no model credentials. Use synthetic data and never call
paid providers without explicit task authorization.

For new questions, supply the original source, fixed revision, redistribution
terms, prompt, independent answer verification, and scoring boundaries. Preserve
original-versus-variant distinctions. Open-ended answers use human review. The
[new case template](.github/ISSUE_TEMPLATE/new_case.yml) captures these details.

For runtime changes, retain every attempt, budget reservations, completed answers,
and compatible resume behavior. Do not retry incorrect answers to select a better
score. Update [compatibility rules](docs/compatibility.md) for protocol changes.
Keep source snapshots and raw runs immutable; regrades are derived evidence.

Describe the concrete problem and resulting behavior in a PR, followed by checks
actually run and remaining limits. Report offline tests, real requests, human
reviews, and regrades separately. Do not attach a whole private run; inspect a
[share export](docs/sharing.md) or provide a minimal synthetic reproduction.

See [SECURITY.md](SECURITY.md) for private vulnerability reports and
[release preparation](docs/releasing.md) for distribution checks. A source commit,
a tested artifact, a GitHub Release, and a PyPI publication are separate steps.
