# 接入验证矩阵

核对日期：2026-09-15。离线模拟、历史真实调用与当前真实接入分别记录。
本轮没有发起模型调用，不能由历史记录推断当前供应商健康状态。

| 接入条件 | 离线覆盖 | 已有真实证据 | 本轮尚未验证 |
|---|---|---|---|
| Chat Completions，非流式 | 请求字段、实际模型、用量、429/5xx、超时、空输出、截断、拒答 | 0.1.0 历史单题 `protocol_error`，非 JSON 响应；无成功证据 | 当前真实成功请求 |
| Responses，非流式 | 独立协议与参数、状态和用量解析、工具、错误 | 0.1.0 历史单题 `api_error`，HTTP 401；无成功证据 | 当前真实成功请求 |
| 两种 API，`stream:true` | 本地 SSE 事件顺序、正文增量、推理/工具排除、截断、终态、部分回答超时 | 无 | 真实 HTTP/SSE 供应商行为与延迟 |
| Codex CLI 0.153.4，controlled | 新会话/临时目录、限制参数、工具事件、进程组超时 | 0.1.0 首次 quick 4 ok/1 timeout；后续 quick 5 ok；ModelTrace 3 条返回 | 新版完整真实回归、增量正文时间 |
| Claude Code 2.1.270，controlled | 同上，Claude 事件解析、输出限制 | 0.1.0 quick 5 ok；ModelTrace 原记录 2 ok/1 cli_error（旧解析）；开放 SVG 单题 ok | 新版完整真实回归、增量正文时间 |
| Codex CLI 0.153.4，native | 保留本地工具配置，独立比较；指纹仍检查工具 | 历史单题 timeout | 成功 native 调用 |
| Claude Code 2.1.270，native | 同上 | 历史单题 ok | 新版完整真实回归 |

CLI 版本来自原 manifest。`ok` 仅表示调用返回，不代表答对、SVG 画得好或指纹准确。
CLI 当前均不提供可验证增量正文时间，`stream:true` 会拒绝，不把最终事件当作首 token。

新增复核的用户运行 `20260915T091840Z-a476bb86`：harness 0.1.0、Codex CLI 0.153.4、
controlled、quick、并发 1，5/5 `ok`。只读取配置中的协议/版本以及结果状态；未公开
地址、模型私有标识或回答。该记录证明的是该次 CLI 调用，**不是 API 成功实测**。
其他历史记录见[最初验证](validation.md)与[脱敏观察清单](../examples/validation-observations.json)。

## 调度与取消证据

专项测试使用本地线程、事件屏障和可控时钟：全局/目标上限、目标轮转、慢题不阻塞
空位补充、先预留预算后发起、完成先落盘、未知用量停止补位、SIGINT 停止派发并收齐
在途回答。另覆盖重试、超时、中断等待、执行片段重叠和续跑只补缺失题。
这些证明 harness 的离线行为，不能保证第三方远端取消或计费。

配置起点：[API 双协议/不同并发](../examples/config-api.yaml)、[双 CLI](../examples/config-cli.yaml)。
先把例子复制到 `config.local.yaml` 再填自己的配置。`doctor` 不发出模型请求；真实验证
需要完整 completion 及事件/状态证据，`/models` 列表和配置存在都不算成功调用。
