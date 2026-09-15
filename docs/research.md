# 社区验智与模型指纹测试调研

调研日期：2026-09-14。目标是可复现、可配置、可保留证据的日常筛查与回归，不制作新的通用模型排行榜。

调研路径包括 GitHub 原仓库、原作者说明、LINUX DO / NodeLoc / Reddit / Hacker News 等社区讨论线索。社区反馈用于发现方法；实现、答案和算法以原始源码或独立验证为依据，不能把社区的“降智”归因直接当成事实。

## 首批引入与复现

### Candy Eval：同一道题重复采样

- 来源：[haowang02/codex-candy-eval](https://github.com/haowang02/codex-candy-eval)，固定 `4dde0a9e8043c9f84e5e810c4f7cdd555751a20c`。
- 原实现用本地 Codex CLI 运行糖果题，输出 token 用量、耗时、端到端 TPS 和正确率；另有 Claude、OpenCode 等脚本。CLI 新会话、stdin 传题，读取结构化完成事件。
- 原评分是回答中出现独立数字 `21` 即通过，因此推导中出现 21、最终结论为其他值也会误判。
- 实现：只提取数学题文本，不整包复制未声明许可的运行脚本；本地重写统一适配器。保留兼容分，增加最终答案分和九道明确题意/参数变化题。
- 独立验证：按形状选择的最优解为圆形 9 + 星形 12，总计 21；完全随机抓取需要 29。原题提示词、明确题意版本与参数变化是不同协议。
- 局限：一道公开题可能被记忆；重复采样能检查稳定性，但不能等价于增加不同题目的覆盖率。

### Simon Willison 的鹈鹕

- 原项目：[simonw/pelican-bicycle](https://github.com/simonw/pelican-bicycle)，调研快照 `a0cfd51f5838613d486f93c24ee77ec2690f3400`。
- 核心是一条文本提示，让模型输出鹈鹕骑自行车的 SVG，原项目收集不同模型的 SVG 样例。不是调用文生图工具。
- 实现：保留简短原提示；SVG/回答本地落盘，以人工评价语义和空间关系。没有复制原项目的示例图片或生成脚本。
- 局限：公开题的熟悉度、视觉风格和主观偏好都会影响结果。原作者也讨论了该任务被训练优化与模型比较的局限，参见[原作者讨论](https://simonwillison.net/2025/Nov/13/training-for-pelicans-riding-bicycles/)。单张图片不能代表综合能力。

### OpenEnv：动物 × 交通工具

- 来源：[OpenEnv Pelican SVG](https://github.com/huggingface/OpenEnv/blob/main/docs/source/environments/pelican_svg.md)，固定 `da5929566e99c8eb376a47042b316cb13c0aae29`，BSD-3-Clause。
- 原实现包含 6 种动物 × 5 种交通工具，共 30 种组合；分门禁、几何和视觉裁判层评分，还支持训练环境。
- 实现：复用纯 Python 的任务目录，保留全部 30 种组合、动物特征和车辆要求，另加 Simon 原提示共 31 题。其模板增加了只输出 SVG、禁止嵌入位图等要求，不能冒称与 Simon 原题提示完全一致。
- 不引入环境服务器、GPU 训练或视觉裁判；按用户选择，视觉效果全部人工评阅。
- 局限：可解析图形、两个圆加一条线不是画对动物和骑乘关系的充分证据。新的组合也不能仅凭改动物名就被称为“无污染集”。

### Collatz：审题及是否被关键词带偏

- 来源：[unryuu/idiot](https://github.com/unryuu/idiot)，固定 `01070f7854ff5c3b0722060a4e7e51417ebe2eba`，MIT。
- 原单轮题问 1..1000 中首次到 1 前经过 16 的数字有多少，附用户的直觉推理。原作者还比较开启/关闭推理和多次重复。
- 实现：引入 `tests/collatz-16/test.json` 的 prompt/system，不把参考答案和 notes 发给模型；独立遍历序列确认只有 1、2、4、8 例外，答案 996。
- 局限：这个版本的用户推理本身已经给出候选答案，测量包含对用户观点的审查和一致性，不能当作无提示数学题。该仓库《礼物》属于多轮开放式文学题，第一版暂不引入。

### SimpleBench 公开集

- 来源：[simple-bench/SimpleBench](https://github.com/simple-bench/SimpleBench)，固定 `fbc2e429085bdedad7d1a236d2bc9bc18c95f16e`，MIT。
- 已读取并解析公开 JSON/CSV，共 10 题；原 runner 依赖 LiteLLM、Weave，支持多回答投票和固定 system prompt。
- 实现：引入 JSON、原 system prompt 和答案，使用本项目适配器进行单回答/重复采样，最终选项自动评分；不引入 Weave 服务或投票选优。
- 局限：公开集仅 10 题，不是完整私有测试集；本地结果不能直接当作官方排行榜分数。

### BullshitBench：能否识别错误前提

- 来源：[petergpt/bullshit-benchmark](https://github.com/petergpt/bullshit-benchmark)，固定 `2678ac296fe6e234d391e0f4ab339f6a777ba2a3`，MIT。
- 上游 V2 覆盖多种制造错误前提的方法，原发布流程包含多模型裁判、拒答/错误处理及特定统计口径。
- 实现：固定 `questions.v2.json` 的 100 道题，保留原文和解释。注意该文件内部 version 标记为 `v2.0-draft`，本项目依据文件和提交哈希定位快照，不把它描述成实时排行榜的完整复现。
- 开放回答全部人工按 0/1/2 打分；只有问题发给模型，nonsensical_element 只出现在评阅包里。
- 局限：识别错误前提与过度拒绝正确问题是不同能力；该题集不足以量化后者。人工评分和上游模型裁判不可直接混比。

### ModelTrace：输出数字分布的身份线索

- 来源：[网站](https://xqy2006.github.io/ModelTrace/)与[GitHub 原仓库](https://github.com/xqy2006/ModelTrace)。网站读取受限时，直接检查原仓库源码与静态页面文件。固定 `60949ef522a84f66b1236b459308b48028d36949`，MIT。
- 实际检测入口 `fingerprint.generate_challenges` 生成三条中文整数选择任务；`challenge_suite.fingerprint_suite` 的 36 条不同环境挑战用于建库，两者不能混用。
- 原算法把 Hellinger 数字分布特征和有序块特征融合，移除部分参考环境方向，按有效回答数选校准参数；统一 softmax 得到模型概率，家族概率为所属模型概率之和。
- 实现：原样保留 `fingerprint.py` 与统一库，增加统一目标适配、固定种子、三条整组调用、快照保存、工具审计、离线导入和无有效回答状态。保留数字解析和有效性门槛。
- 当前固定库有 13 个候选、两个家族；参考渠道由上游标注为 Codex / OAIPro。这是参考数据标签，未由本项目重新认证。
- 局限：闭集方法没有“所有未知模型”的真实概率。未收录的模型也会匹配某个候选，哪怕概率很高也不能据此认定供应商冒充模型。第一版不训练新库，不承诺指纹准确率。

## 自编的客观回归题

基础易错题覆盖 9.11/9.9、strawberry 计数等流行测试思路，并加入负数、大小写、单位转换、排序及反转变体；只复用测试思想，自行编写题目和答案。

[IFEval 原实现](https://github.com/google-research/google-research/tree/master/instruction_following_eval)展示了如何用确定性约束验证指令遵循。本项目采用其中“可程序验证”的方法，自编 JSON、行数、单词次数、禁用字符和首尾标签题，没有声称复现原数据集或完整 strict/loose 协议。

[RULER](https://github.com/NVIDIA/RULER)包含多种长上下文任务。本项目仅自编指定 key 检索，设置约 4K/16K/64K/128K 字符、前后两个位置，以固定种子生成答案和干扰项。字符数不等于 token 数；能通过该任务也不等于测得真实上下文上限。

## 其他调研对象及暂不采用原因

| 对象 | 调研所得 | 决策 |
|---|---|---|
| [martianzhang/llm-test](https://github.com/martianzhang/llm-test) | 中文数学、常识、字符、亲属关系等易错题集合；快照 `37d7e6c75df32d36eeeedfa4210b64bc1e702e06` 未检出仓库许可 | 用作分类与线索参考，不批量搬运题目/答案 |
| [api-model-spy](https://github.com/dabaibian/api-model-spy) | 混合自报身份、日期、字符、数值、速度等启发式指纹 | 不采用其模型身份结论规则，避免把多种间接信号包装成认证 |
| Candy 仓库的 juice / TPS 脚本 | 社区用模型自报内部数值和 token 速度判断状态 | 不采集隐藏指令或以自报数值判能力；只记录服务端实际用量及端到端耗时 |
| [apoorvumang/knowledge-cutoff](https://github.com/apoorvumang/knowledge-cutoff) | 用按月分布的事件题及对照观察有效知识覆盖，含选择题与开放题 | 用户明确只问知识截止日期，第一版不加入事实时效题；也不凭日期自述作真值 |
| [LiveBench](https://github.com/LiveBench/LiveBench) | 更广的能力维度和不断更新的任务 | 作为未来标准基准扩展，本次聚焦社区题和可维护的日常回归 |
| [lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness) | 成熟的模型/任务注册与批量评测基础设施 | 第一版不引入整套框架；本地 CLI 事件和人工 SVG 评阅需要专门处理 |
| [Promptfoo](https://www.promptfoo.dev/docs/configuration/reference/) | YAML、provider、断言和比较能力 | 借鉴配置体验；本项目采用 Python，便于复用 ModelTrace 的 NumPy 算法并维护小型依赖集 |
| [openai/simple-evals](https://github.com/openai/simple-evals) | 轻量评测与结果归档参考 | 借鉴证据保存，不引入额外大规模基准或模型裁判 |

社区线索示例：[NodeLoc 糖果测试讨论](https://www.nodeloc.com/t/topic/95658)、[Hacker News 鹈鹕讨论](https://news.ycombinator.com/item?id=42427058)、[Reddit BullshitBench 讨论](https://www.reddit.com/r/LocalLLaMA/comments/1rdw6pp/bullshit_benchmark_a_benchmark_for_testing/)。其中关于账号/IP、模型内部预算、替换模型的断言未被本项目验证。

## 版本维护

实际引入文件的原始 URL、提交 SHA、SHA-256、许可位置集中存放在 `src/dummy_llm_test/data/sources.json`。`doctor` 检查文件是否仍匹配快照。`scripts/vendor_sources.py` 仅维护固定允许列表，通过下载/静态提取更新来源，不执行远程脚本。

运行时不依赖 GitHub 下载题库。升级来源后应重新核对题目数量、答案、判分与许可，更新快照和验证记录；旧结果保留其 manifest 和哈希，不能与新版本无条件混比。
