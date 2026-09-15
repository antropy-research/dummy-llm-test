# 运行性能：字段、公式与证据边界

性能观测版本 `schema_version: 1`，随 0.3.0 引入。题目、答案与人工评阅协议不变。
性能“成功”指最终 `status: ok` 且回答非空，**不要求答题正确**。不把速度变化称为
能力下降，也不根据单次运行自动作性能回归判断。

## 开启与查看

默认所有 API 仍非流式。要观察流式正文到达，显式配置目标：

```yaml
concurrency: 4
targets:
  api:
    kind: chat_completions
    stream: true
    # 继续配置 base_url、model、api_key_env 等原有字段。
  responses:
    kind: responses
    stream: true
```

```bash
uv run dummy-llm-test run --level quick --target api --concurrency 4
uv run dummy-llm-test compare --baseline runs/OLD --current runs/NEW
# 完全离线，输出目录必须不存在；原记录保持不变。
uv run dummy-llm-test performance analyze runs/OLD --output runs/OLD-performance
```

正常运行在 `report.html` 直接显示性能；`summary.json.performance` 提供结构化数据。
离线派生分析输出 `performance.json` 与 `report.html`，附来源文件校验值。0.3.0 之前的
记录可以重算有用量和正耗时的最终尝试 TPS，但不能从最终回答倒推出首段正文时间、
完整样本单调时钟跨度或执行片段。缺失字段保持 `null`，HTML 显示“未提供／不支持”。

## 支持矩阵

| 入口 | 尝试/样本耗时、重试、调度等待 | 首段正文延迟/正文接收时长 | 事件顺序与到达时间 | 纯生成 TPS |
|---|---|---|---|---|
| Chat Completions 非流式 | 支持 | 不支持 | 无 SSE 记录 | 不支持 |
| Chat Completions `stream: true` | 支持 | `choices[0].delta.content` 的非空可见正文 | 支持，含 usage、角色和心跳 | 不支持 |
| Responses 非流式 | 支持 | 不支持 | 无 SSE 记录 | 不支持 |
| Responses `stream: true` | 支持 | `response.output_text.delta` 的非空可见正文 | 支持，含推理、工具和终态 | 不支持 |
| Codex / Claude CLI | 支持 | 当前不支持 | 保留原有原始 CLI 事件，未逐条捕获增量到达时间 | 不支持 |
| 旧版记录离线分析 | 仅已有证据支持的字段 | 无原始到达记录则不支持 | 不补造时间 | 不支持 |

CLI 的 `stream-json` 输出格式本身不证明有增量正文时间；当前通过整次进程收集输出，
因此显式拒绝 CLI 的 `stream: true`。最终回答事件不能充当首 token 事件。受控/native
隔离和工具使用检查不因加入性能记录而放宽。

Chat Completions 流式请求发送 `stream_options.include_usage: true`，但流中仍可能没有
用量；缺失不估算。Responses 使用终态 response 的 usage。流式请求遇到非 SSE 响应
会报协议错误，不改用 JSON 请求重跑。原始事件和部分正文在超时或异常时仍保留。
读到终态事件即结束，不等待连接后续关闭。角色、工具、推理、心跳、done/full-text
事件均不建立正文时间边界；仅空白的增量保留文本，但不作为可见正文边界。

实现参考官方 [Streaming responses](https://developers.openai.com/api/docs/guides/streaming-responses)
及 [Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。
本轮使用本地模拟事件验证，**没有付费实测，真实服务商的流式兼容性尚未验证**。

## 每次尝试与样本

所有时长使用本机单调时钟计算，UTC ISO 8601 时间仅供审计，不通过 UTC 相减计算时长。
测量包含客户端/CLI 启动及本地观测开销；不是模型内部纯推理耗时。服务端排队、网络、
工具及推理阶段无法仅凭这些观测完整拆分。

| JSON 路径 | 含义 / 公式 |
|---|---|
| `results.jsonl` 每行 `sample_id,target,case_id,repeat` | 样本定位；重复从 0 开始 |
| `attempts[].attempt` | 尝试序号，从 1 开始；每次尝试也含上述定位字段及 `fragment_id` |
| `attempts[].elapsed` / `response.elapsed` | 该次 API/CLI 调用耗时；response 是最终尝试，不是样本总耗时 |
| `attempts[].timing.started_at,finished_at,elapsed_seconds` | UTC 审计与单调耗时；最终尝试同样位于 `response.timing` |
| `timing.sample_started_at,sample_finished_at,sample_seconds` | 从开始首次尝试到样本结束，含失败尝试、重试等待及本地记录开销；不含调度等待及最终判分/报告生成 |
| `timing.retry_waits[]` | 带样本身份、前一尝试序号、UTC 起止、实际等待 seconds 和 interrupted；被中断的等待也计入样本总耗时 |
| `timing.queued_at,dispatched_at,queue_wait_seconds` | 本次启动加入待执行队列到首次派发；不是服务端排队时间，续跑重新入队测量 |
| `timing.fragment_id` | 关联本次启动的执行片段 |
| `performance.observations[].attempt_seconds` | 最终尝试耗时 |
| `performance.observations[].final_attempt_tps` | 最终尝试 output_tokens / 最终尝试耗时；保留现有端到端口径，失败记录的该值仅作原始描述 |
| `performance.observations[].effective_tps` | 最终成功回答 output_tokens / sample_seconds；最终失败则 null，不汇总失败尝试输出 |
| `performance.observations[].retry_count` | 尝试数减 1；没有尝试记录时未知，非 0 |

`performance.observations` 的每行都保留 sample_id、target、case_id、suite、repeat、最终
attempt、timing、逐次 attempts、状态和 `missing_reasons`。不存在仅保留一组无法定位
题目的 TPS 数值列表。分组统计通过 sample_ids 对应这些观测。

最终尝试/样本 TPS 使用服务端总输出 token，可能包含 reasoning_tokens；只把它们称为
“最终尝试 TPS”和“样本有效 TPS”。分母缺失/非正、用量缺失/非法时不计算。实际报告
的零输出 token 可以得到零 TPS；旧版默认 elapsed=0 且没有时间观测时按未知处理。

## 流式字段

`attempts[].stream`（最终尝试也在 `response.stream`）保存：

| 字段 | 含义 |
|---|---|
| `request_started_at` | 客户端开始流式请求的 UTC；在 HTTP client 初始化后、开始发送请求前记录，不是服务端接收时间 |
| `first_visible_text_seconds` | 请求开始到第一帧非空白正文增量到达的单调时钟差 |
| `visible_text_receive_seconds` | 最后一帧正文到达减第一帧正文到达；只有一帧时为实际观测的 0 |
| `events[].index,type,offset_seconds,received_at,data` | 顺序、类型、相对请求开始的秒数、UTC 到达时间、原始 SSE 数据；data 解析失败时保留原文 |
| `generation_tokens_per_second` | 当前始终 null |
| `generation_rate_reason` | `token_range_and_generation_time_boundaries_unavailable` |
| `reason` | 非流式、CLI 无增量到达观测、没有正文增量等缺失原因 |

到达时间是客户端解码完整 SSE 帧时的观测，受缓冲和网络影响，不是服务器生成时间。
总输出 token 可能包含推理，分块也不等于 token，因此不能除以“首段到末段时长”
宣称纯生成 TPS。即使服务端提供 reasoning_tokens，也不推测剩余 token 的生成时间。
终态原始响应位于 `response.raw.assembled`，原始事件还在 `response.raw.stream_events`；
汇总 usage 与回答可以复查，事件本身不作为开发指令执行。

## 执行片段与并发吞吐

每次启动（含续跑）新增 `segments/<fragment_id>.json`，不会覆盖前一次片段；空续跑也
保留启动记录，但没有调用时的时长与速率为空。每个片段保存 created_at、finished_at、
stop_reason、全局/各目标并发、超时与重试策略，以及带身份的事件。

事件类型为 `sample_dispatched`、`attempt_started`、`attempt_finished`，保存相对片段
单调时钟原点的 offset_seconds 和 UTC at。尝试事件有 attempt；派发事件发生在首次
尝试前，只关联 sample_id/target/case_id/repeat。片段初始化和每次事件均更新文件；
进程硬崩溃留下未关闭的片段时，不把它当完整测量。

| 汇总字段（`performance.fragments[]`） | 定义 |
|---|---|
| `duration_seconds` | 最后一个在途尝试结束 − 首次派发；不含启动准备、最终报告生成、跨次启动间隔 |
| `first_dispatched_at,last_attempt_finished_at` | 上述端点的 UTC 审计时间；不同于整个片段文件的创建/最终写入时间 |
| `effective_output_tokens_per_second` | 本片段成功样本最终 output_tokens 总和 / duration；有任何成功样本用量缺失则 null |
| `known_output_tokens_per_second` | 仅已有用量部分 / duration；全部缺失时为空，`throughput_scope: known_partial` |
| `output_usage_coverage` | 提供有效最终输出用量的成功样本数 / 成功样本数；没有成功样本则为空 |
| `attempts_per_minute` | 完成尝试数 × 60 / duration，包含失败尝试 |
| `successful_samples_per_minute` | 成功样本数 × 60 / duration，与上项分开 |
| `concurrency_events` | 尝试开始/结束事件及该时刻的在途尝试数 |
| `peak_inflight_attempts` | 实测在途尝试数最大值，不是配置并发上限 |
| `average_inflight_attempts` | 在途尝试数的时间积分 / duration，重试等待不算正在请求 |

全局调度槽位可能包含等待重试的样本，因此其占用数与“在途尝试数”不同。CLI 只观测
外部一次进程调用，不推断其内部模型请求数。每个片段分别报告速率，不相加请求 TPS，
也不把多个片段的首尾 UTC 差作为一次运行时长。

## 汇总、图表与比较

`performance.targets` 按目标、`performance.groups` 按目标和题集汇总。每个指标的
success_metrics 保存 n、P5、P50、P95，排除缺失值；不同指标可能有不同 n。百分位
使用排序后 `(n−1)×p` 的线性插值。成功样本用量覆盖率单独展示，不能由 n 猜测。
故障率分母是全部完成样本，分子是非成功最终状态；status_rates 区分超时、截断、
拒答等。attempt_statuses 保留失败后重试成功的尝试；retry_rate 分母是有尝试记录
的样本，另保留 retry_observation_coverage。

耗时越低越好，TPS 的 P95 表示较快样本、P5 表示慢端。HTML 提供成功样本总耗时
直方图、带状态颜色及样本身份提示的“输出 token—最终尝试耗时”散点图，以及每片段
并发曲线。缺失值不绘制为零；图形是本地生成 SVG，不执行被测返回内容。

`compare` 的 `performance.pairs` 先按 target/case_id/repeat 对齐，再检查题目哈希、
模型参数、实际模型字段、模式、入口身份/版本、全局与目标并发、重试、超时、stream、
实际输出限制及对应组件签名。0.4.0 的新协议不依赖整包版本/代码哈希；旧记录仍保留原来的保守检查，不自动迁移为可比。
条件不同标为 conditions_differ，仍显示双方数值，但不给出自动回归判断或差值结论。

条件一致且双侧成功时，绝对变化 = after−before；百分比 = (after−before)/before×100，
before=0 时百分比为空。题集统计对每个指标采用双侧都有值的配对样本，比较其 P50；
同时报告输出 token、回答字符数和故障率变化。双侧成功的筛选本身会遗漏失败样本，
所以不能脱离全部样本故障率解读“变快”。小于 30 道不同题标为小样本描述，不提供
性能显著性或能力降智结论。原有能力分数、人工评阅与指纹比较独立保留。

比较还展示两次运行的计划/完成数，以及基线存在但当前缺失的样本清单；未产生记录
不能当作成功或变快。`performance.coverage` 保留全部已完成样本的故障率，题集的
before_all/after_all 仅是可对齐题集的并排描述，条件不同仍不能据此下回归结论。

片段有已派发但没有完成样本记录时，`unresolved_sample_ids` 明确列出这些样本，
完整输出吞吐量保持为空。若在途开始/结束事件未闭合，片段时长及依赖它的速率为空。
已有流式事件时，离线分析重新计算正文时间边界，不修改原始记录中的计算结果。


## 0.4.0 的比较条件存储

新样本的 `performance_conditions` 记录产生该回答时的并发、各目标上限、共用目标列表、
重试、超时、目标参数及组件版本。比较优先读取样本快照，不用首次 manifest 配置覆盖
续跑的新条件。每片段增加 `contract_versions` 和 `runtime_config`；旧片段和原样本不改写。

包版本、整包源码哈希保留审计，新协议比较使用独立组件哈希；报告样式变更不影响
新记录匹配。新旧协议不会自动判为兼容。完整字段与允许的续跑变更见
[兼容规则](compatibility.md)，公开分享时使用[统计导出](sharing.md)。
