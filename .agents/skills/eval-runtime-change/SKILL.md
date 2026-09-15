---
name: eval-runtime-change
description: 修改 dummy-llm-test 的 API/CLI 接入、并发调度、费用预算、中断或续跑时，验证请求生命周期和结果持久化。
---

# 运行可靠性变更

读取 AGENTS.md 与 docs/configuration.md 中相关字段。沿 config → plan → preflight →
scheduler → adapter → attempts/results → summary 追踪一次调用，先定位失败发生在哪一层。

对接入变化检查真实请求参数和原始事件，不仅检查进程退出码或模型列表。
保留显式协议、模型与推理参数；受控 CLI 限制必须有版本能力检查和实际工具事件
检查。新测试使用本地 HTTP 服务、模拟响应或临时可执行文件；不依赖个人登录状态。

对调度变化用事件/屏障验证：慢任务不阻止其他空位补位，全局及各目标上限同时
成立，目标有轮转机会，停止之后不派发后续任务，在途返回不丢失。避免只断言运行
时间更短的脆弱测试。预算在请求前持久化预留；未知用量停止后续派发，但收齐在途
回答。错误重试保持每次尝试，不允许重试答错。

明确中断语义：优雅停止等待在途请求完成或超时，不声称撤销远端请求或计费。
检查 SIGINT 处理器恢复、退出码、停止状态、结果落盘和仅补缺失样本的续跑。
不要在配置或版本变化后绕过已有兼容校验来修复续跑报错。

维护 tests/test_scheduler.py、tests/test_adapters.py、tests/test_runner_review.py
和 tests/test_cli_config.py 中受影响的行为测试。先用最小样本复现，再验证完整调度
路径；模拟 full 不证明真实 full 成绩。若当前任务授权真实调用，限定目标、题目和
次数，脱敏保存证据，不推断其他未测入口也能工作。
