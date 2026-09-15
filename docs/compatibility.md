# 实验参数、运行参数与版本边界

从 0.4.0 起，新运行使用 `contract_versions.schema = 2`。包版本及整包 `code_hash`
继续记录用于审计，但不再直接决定新记录能否比较。题库、提示词、判分规则本轮没有改变。

## 签名各自负责什么

| 字段 / 组件 | 内容 | 用途 |
|---|---|---|
| `case_hash` | 完整 Case：题号、题集、原始提示词、system、答案、metadata | 精确匹配题目和本地评分材料；材料不发送给模型 |
| `contract_versions.question` | catalog、fingerprint、core 源码哈希 | 题目生成、选择、序列化版本；续跑检查 |
| `contract_versions.scorer` / `grader_signature` | scoring、core 源码哈希 | 分数可比性；评分器改变应离线重判 |
| `contract_versions.adapter` | adapters、streaming、core 源码哈希 | 请求构造、协议、原始事件解析及类型边界 |
| `contract_versions.scheduler` | scheduler、runner 源码哈希 | 派发、重试、预算、落盘的实现版本 |
| `contract_versions.measurement` | performance 源码哈希 | 性能计算与条件匹配实现版本 |
| `contract_versions.compatibility` | contracts 源码哈希 | 本文签名策略本身的实现版本 |
| `target_signature` | 接入/模型配置、preflight 身份、模式、adapter、compatibility | 能力比较条件；不包含并发和价格 |
| `resume_hash` | 选中目标、计划、案例、组件、身份、指纹库内容、其余受约束配置 | 只补缺失样本时的兼容门槛 |
| 样本 `performance_conditions` | 实际本次启动的目标配置/身份、全局及各目标并发、共用目标列表、重试、超时、adapter/scheduler/measurement/compatibility | 性能比较；另外核对 Case、模式、实际模型和实际输出限制 |

源码哈希自动变化，不依赖维护者记得手动加版本号。`report.py`、`performance_report.py`、
`sharing.py`、README 和包版本不在上述组件内，单独改报告不会阻断新协议运行的续跑或比较。
当前 runner 仍包含汇总调度，因此修改 runner 内部会保守地改变 scheduler 组件。
这套边界不保证任意重构后都兼容，也不证明服务商后台权重、机器负载或网络相同。

## 续跑允许和拒绝的变化

```bash
uv run dummy-llm-test run --resume runs/YOUR_RUN --concurrency 4
```

可以调整全局/目标并发、进度刷新间隔、输出目录，以及未选中的目标/档位配置。
目标模型、地址、协议、stream、输出限制、重试、超时、价格/预算、种子、选中题目、
重复次数、CLI 身份和组件版本必须一致。外部题目/挑战文件按加载后的 Case 内容
检查，指纹库按解析内容检查；仅换文件位置不会绕过内容校验。

原始 manifest 的计划和配置继续表示首次启动。每次启动写入新执行片段，记录并发、
超时、重试、预算、刷新间隔和组件版本；每个新样本记录当时的 `performance_conditions`。
续跑不会把原样本的并发改成当前值，统计不会把离线间隔计入执行时长。

并发变化通常不使客观答案失去比较资格，但性能比较会标为 `conditions_differ`，
并显示具体差异。不能自动把不同条件下的速度变化称为性能回归。长度、故障率和
小样本边界继续展示，速度不是能力分数。

## 旧记录与重判

0.1–0.3 的旧记录没有分组件签名，继续走原来的完整配置和源码哈希检查；不伪造
新签名或自动迁移成可比记录。可使用对应旧版本续跑，或开始新运行。旧/新协议之间
能力比较会不兼容，性能比较显示条件差异；旧记录仍可阅读、分享或派生性能分析。

`regrade` 生成新目录并保留来源；更新评分器签名不改变原始模型请求条件。
派生记录不能续跑。仅重判不能把一次旧实验转换成按新版适配器重新执行的实验。
