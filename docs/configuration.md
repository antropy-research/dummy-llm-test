# 配置及扩展

## 文件和优先级

默认读取当前目录的 `config.local.yaml`，不存在时读取 `config.yaml`，再与包内默认配置递归合并。`--config FILE` 显式指定文件；`run` 的 `--level`、`--target`、`--mode`、`--repetitions` 覆盖此次运行设置。相对路径均相对执行命令的当前目录。YAML 不进行环境变量插值，密钥通过 `api_key_env` 间接引用。

仓库配置默认目标为 Codex。安装后的命令即使在空目录也具有 quick/full/fingerprint 默认值；额外的 reasoning 示例档位来自仓库的 `config.yaml`。

## 通用设置

| 字段 | 默认 | 说明 |
|---|---|---|
| `default_target` | `codex` | 未传 `--target` 时使用 |
| `seed` | `42` | 固定本地生成题和三条指纹挑战；不是服务端采样保证 |
| `mode` | `controlled` | CLI 受控答题；`native` 保留本地工具配置 |
| `concurrency` | `1` | 所有目标合计的并发上限；`run --concurrency N` 可覆盖 |
| `progress_interval` | `10` | 在途任务心跳间隔，单位秒；启动和完成时也更新进度 |
| `repetitions` | `1` | 每题重复次数；ModelTrace 每次为一组三条 |
| `timeout` | `300` | API 请求超时/CLI 进程墙钟超时，单位秒 |
| `retries` | `0` | 仅 429/5xx 自动重试，最多配置 5；每次尝试保留 |
| `output_dir` | `runs` | 每次运行建立独立目录 |
| `disabled_suites` | `[]` | 对所有档位禁用指定题集 |
| `disabled_cases` | `[]` | 禁用指定题目；不能只保留部分 ModelTrace 挑战 |
| `custom_cases` | `[]` | 本地 JSON 题目列表的路径 |
| `bank` | 内置快照 | 兼容的 ModelTrace `unified_bank.json` |
| `challenges` | 按 seed 生成 | 重用 `fingerprint export` 或既有运行的三条挑战 |

API 非流式请求的超时由 HTTP 客户端分别施加于连接/读取等阶段；不能将其解释为服务商停止计费的保证。CLI 超时会终止本次子进程组，不终止其他任务或常驻服务。

## 目标配置

```yaml
concurrency: 4
progress_interval: 10
targets:
  codex:
    concurrency: 2
  claude:
    concurrency: 1
```

每个目标的 `concurrency` 可选，默认使用全局上限；实际并发同时受两者约束。
上例只运行这两个目标时合计最多 3 个在途调用。多目标按轮转顺序获得空位，完成
一题即补位，不等待整批最慢题。运行前 `--dry-run` 会显示全局和各目标的有效上限。
并发限制针对单次评测运行；多个独立进程不会共享配额，也不是服务商 RPM/TPM 限流器。
CLI 内部可能有多个模型请求，此处计算的是评测调用数。

并发覆盖示例：`dummy-llm-test run --level full --concurrency 4`。若续跑开始时使用了
这个覆盖值，续跑时也需要提供相同覆盖值，或在所用 YAML 中设置相同的值。

```yaml
default_target: my-api
targets:
  my-api:
    kind: chat_completions
    base_url: https://YOUR-PROVIDER.example/v1
    api_key_env: MY_PROVIDER_API_KEY
    model: YOUR_MODEL_ID
    max_output_tokens: 8192
    chat_token_field: max_completion_tokens
    reasoning_effort: high
```

`kind` 仅接受 `chat_completions`、`responses`、`codex`、`claude`。API 将对应路由追加在 base_url 后：`/chat/completions` 或 `/responses`。例如服务商要求 `/v1/responses` 时，base_url 必须包含 `/v1`。不自动发现、更换协议或重写模型名。

Chat Completions 将 `max_output_tokens` 映射到 `chat_token_field`，该字段只允许 `max_completion_tokens` 或旧式 `max_tokens`。Responses 使用 `max_output_tokens` 并发送 `store:false`。推理参数分别使用 `reasoning_effort` 或 `reasoning.effort`。可配置 `temperature`、`top_p`；`seed` 仅 Chat Completions 支持。服务商若拒绝参数，报告错误，不偷偷删除参数再试。

API 的 input/output/reasoning/cache 用量只采用响应中实际提供的字段，缺失记为 null。`reasoning_tokens` 不重复加到输出计费 token 上。端到端输出 TPS = output_tokens / 整次耗时，包含思考、启动、排队和网络，**不是纯生成速度**。

CLI 的 `executable` 可指定安装路径，`model:null` 使用 CLI 默认模型；建议长期对比时显式锁定模型。CLI 不支持此适配器的 temperature/top_p/seed，配置后会提前报错。`reasoning_effort` 必须被当前 CLI 支持。

Codex 受控模式使用 `--ignore-user-config`，仅从当前 Codex 配置继承模型与连接字段；可用 `codex_provider` 指定其中的连接。它不复制固定 `http_headers` 凭据，应使用现有登录或 provider 的 `env_key`。Codex 没有可验证的每次输出上限，此参数在请求证据中记录为 null，不宣称生效。Claude 使用 `CLAUDE_CODE_MAX_OUTPUT_TOKENS` 设置上限。

## 自定义档位

```yaml
levels:
  daily:
    suites: [candy, basic, instruction]
    repetitions: 3
  visual:
    suites: [svg]
  selected:
    cases: [candy.original, collatz.original, simplebench.1]
```

`cases` 与 `suites` 取并集；`suites: ['*']` 包含全部已注册题目，再应用禁用列表。没有默认题数上限。使用 `list --level full` 或 `run --dry-run` 检查最终清单。三个 ModelTrace case 必须成组选取。

## 费用限制

```yaml
cost_limit_usd: 2
targets:
  my-api:
    # 另填写 kind / base_url / model / api_key_env
    input_price_per_million: 2
    output_price_per_million: 10
```

价格由使用者明确提供，不内置会过期的报价。调度器在发起每个请求前，用输入 UTF-8 字节上界加协议余量、输出上限及最大尝试次数预留预算并持久化。预留不回收，因此可能在实际账单远低于上限时提前停止；下一题预留超出上限即停止派发，不跳过昂贵题选择便宜题。收到缺失用量的回答后停止补位，已经发出的其他调用仍会完成并保存。相同配置续跑也不会绕过用量缺失或预算不足。报告同时保留预留预算和已知用量的估算费用。

这依赖端点遵守输出限制和所配价格，无法保证第三方实际账单。CLI 无法验证计费上限，启用此字段会提前报错。订阅额度、服务端缓存优惠、失败请求收费等不做猜测。

## 新增题目

```json
[
  {
    "id": "custom.addition",
    "suite": "custom",
    "prompt": "17 加 28 是多少？只输出答案。",
    "kind": "exact",
    "expected": "45",
    "metadata": {"source": "local", "version": "1"}
  }
]
```

YAML 加 `custom_cases: [my-cases.json]`。题号全局唯一。支持 exact、choice、rules、svg、manual、diagnostic；fingerprint 保留给三条 ModelTrace 挑战。规则题支持 JSON 精确对象、固定行、单词次数、禁止字符、最少词数、首尾标签及内部词数，参见内置 instruction 题。

答案和 metadata 只用于本地判分和人工评阅，不发送给目标。自定义开放题的 manual 使用 BullshitBench 三级标准；新维度评分标准需要扩展评分器和人工评阅注册表。

## 退出码与续跑

- `0`：调用正常完成；客观题答错、开放题待评本身不导致失败。
- `1`：配置、文件或入口检查失败。
- `2`：存在运行故障、预算停止或不完整 ModelTrace 组；报告仍保留。
- `130`：Ctrl+C 优雅中断，已收齐在途结果并保存报告。

Ctrl+C 停止新题派发及后续错误重试，当前已经发起的调用等待返回或原有超时，
可能仍需等待较久。重复 Ctrl+C 不强制杀死子进程。这不是撤销远端请求或计费；
外部强制终止、系统崩溃仍可能导致未落盘响应。中断状态写入 manifest、summary 和
HTML 报告；未发起题目不记为答错。输出中的耗时是本次启动时长，续跑时重新计时。

续跑校验完整配置、题目、CLI 身份信息及源码校验值；版本/参数发生变化应开始新运行。它只补缺失的完成记录，已完成错误样本不重试。若进程在响应落盘前崩溃，该次可能已经被服务商计费，续跑无法保证远端 exactly-once；attempts 日志和保守预算保留这条证据边界。

离线 `regrade` 写入新目录，保留原始评分与来源哈希，不能直接续跑。比较结果同时检查评分器版本，避免把评分器修复误认为模型进步。
