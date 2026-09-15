# 贡献与版本交付流程

本流程生成可审查的分发包，不自动上传 PyPI、创建 GitHub Release 或改变仓库可见性。
源码提交/推送、构建产物与公开发布是不同动作，按当前用户授权执行。

## 准备版本

1. 更新 `pyproject.toml`、`src/dummy_llm_test/__init__.py`、CHANGELOG 和受影响文档。
   用 `uv lock` 刷新锁文件，检查没有无关依赖升级，再 `uv sync --frozen`。
2. 检查兼容性影响：题目、评分器、适配器、调度和性能版本分开说明。
   保持上游快照/许可；来源变更必须有明确固定提交、校验值和采用理由。
3. 运行离线检查并构建。`dist/` 可能有旧版本，交付只选择本次版本文件：

```bash
uv run python scripts/check_repo.py
uv build
uv run python scripts/check_dist.py --dist dist --version 0.4.0
```

检查脚本读取 wheel 和 sdist，不解压执行归档内容；核对版本、元数据、必需模块、
第三方校验值与许可，拒绝原始运行、私有配置、缓存及危险路径。它不是任意内容的
秘密识别器；维护者还须检查待提交 diff 和新增文件内容。

在仓库外的新环境安装 wheel，检查 `list --level quick` 为 5 题、完整档 dry-run 189 题、
题库和指纹库可读、命令帮助与分享导出可用。不要通过开发目录的 editable 安装代替。
源码包也应能构建 wheel，且第三方文件校验保持一致。

## GitHub 构建检查

Actions 的 **Release artifact checks** 可手动选择已提交的 ref，并输入精确版本
（不带 `v`）。流程执行离线检查、构建、归档检查、仓库外 wheel 安装及 dry-run，
最后上传 14 天保留的工作流构建产物。工作流只有仓库读取权限，没有 PyPI 凭据、
OIDC 发布权限或创建 Release 的权限。输入通过环境变量传入，不拼接进 shell 源码。

日常 push/PR 仍运行 Python 3.11/3.12 离线测试矩阵。工作流配置存在不等于已在远端
成功运行；交付记录应列出实际完成的 CI 与本地检查。

## 公开发布前的维护者事项

GitHub 建议提供 README/许可/贡献说明/安全报告入口，并配置相应的仓库安全功能。
项目元数据按 PyPA 的 `[project]` 字段提供作者、地址、关键词、Python 版本和分类。
参见 [GitHub 仓库实践](https://docs.github.com/en/repositories/creating-and-managing-repositories/best-practices-for-repositories)、
[PyPA 元数据规范](https://packaging.python.org/en/latest/specifications/pyproject-toml/)以及
[手动工作流说明](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)。

以下属于仓库管理或独立发布准备，不由本地文件自动完成：确认私密漏洞报告通道、
分支保护和必要状态检查、适用的秘密扫描/推送保护，确认维护联系渠道。
SECURITY.md 描述按钮未启用时的联系办法，不承诺当前已启用任何设置。

本项目代码是 MIT，OpenEnv 为 BSD-3-Clause，其余引入内容分别保留原许可。Candy
上游未声明许可，短提示词只保留来源并自行实现逻辑；未整包复制脚本不等于取得授权。
分发前复核[第三方清单](../THIRD_PARTY_NOTICES.md)中的未声明许可项及采用安排。
包的项目 LICENSE 元数据仅标识 harness 自有代码，不能推导第三方都属于 MIT。

若后续决定公开发布，先完成上述复核，再针对已验证提交打版本标签、创建 Release
及附件；若上 PyPI，单独配置受保护的发布环境和权限，并获得该次发布授权。
不要使用此流程顺带自动改变公共可见性或发布尚未审查的第三方材料。
