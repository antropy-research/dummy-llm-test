# 0.4.0 P1 交付验证

日期：2026-09-15。范围为兼容签名拆分、匿名分享导出、开源贡献文件和构建检查。
题库、原始提示词、答案及判分逻辑未改；新签名协议与旧记录的边界见
[兼容说明](compatibility.md)。本轮没有发起任何模型请求。

## 已完成检查

- Python 3.11.15、3.12.13：各 **149 项离线测试通过**；Ruff、文档链接、技能元数据、
  第三方固定校验值及包版本契约通过。
- 模拟运行验证并发从 1 调为 3 的续跑只补缺失样本：原结果、原执行片段字节不变，
  新样本保存新并发；能力比较仍匹配，性能比较把旧条件样本标为条件不同。
- 评分器、适配器和调度源码变更各自改变对应组件；报告文件和包版本变更不改变
  新实验签名。模型/stream、重试、超时、种子、预算变化继续拒绝续跑。
- 派生记录、旧签名不自动变成可续跑的新实验；性能新旧条件双向比较均不兼容。
- 合成敏感字符串放入回答、错误、模型标识、题号、时间和预览字段，分享文件均未
  包含这些原文；未知状态归为 other，人工评分仅保留注册维度。原始文件字节不变，
  已存在目录和原运行内部目录拒绝作为输出。缺失用量保持空值。
- 保留原有数学独立答案、ModelTrace 上游差分、两种 API/CLI、本地流式事件、
  并发屏障、中断、预算、续跑和完整 189 题模拟调度测试。
- wheel 与 sdist 构建成功，构建过程从 sdist 生成 wheel；归档检查核对版本、元数据、
  所有来源校验值、第三方说明与 5 份上游许可。合成恶意归档测试拒绝 runs、环境
  文件、个人配置及越界路径。
- 仓库外独立 Python 3.11 环境先安装锁定依赖，再安装非 editable wheel，验证 189 题、
  quick 5 题、指纹库、组件签名、完整档 dry-run 和分享命令帮助。直接离线从缓存
  解析未锁定依赖曾因缓存索引不全失败，使用锁定依赖完成安装；没有宣称已验证
  从公共索引全新在线解析全部依赖。
- 本地 Chromium 实际渲染合成分享页，检查统计、空值与合成标记。该页面没有外部
  请求或模型调用，不是真实模型成绩。待提交文件扫描未发现本机用户路径或常见
  凭据模式；模式扫描不等于对任意秘密的完整检测。

## 重现入口

```bash
uv sync --frozen
uv run python scripts/check_repo.py
uv build
uv run python scripts/check_dist.py --dist dist --version 0.4.0
uv run python scripts/make_performance_example.py --shared --output runs/share-demo
uv run dummy-llm-test share export runs/YOUR_RUN --output shared-report
```

最后一条只读取已有运行。合成示例已经随仓库提供，见
[examples/shared-report](../examples/shared-report/index.html)。

## 实测及发布边界

仅核对了本地历史 manifest 的协议/版本和结果状态；新增成功记录属于 Codex CLI，
不是 API。真实 API 成功和 SSE 接入仍未实测，详见[接入矩阵](compatibility-matrix.md)。
未修改用户原始运行，也未用一次真实模型快慢作断言。

工作流、模板和 SECURITY 文件已加入；它们本身不能证明仓库设置已经启用，也不
代表创建了公开 Release 或上传 PyPI。远端 CI/工作流实际运行情况在提交交付时另报。
公开分发前仍需复核第三方未声明许可项和仓库管理设置，见[发布流程](releasing.md)。
