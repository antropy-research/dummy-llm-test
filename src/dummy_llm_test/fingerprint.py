"""Adapter around the unmodified MIT ModelTrace scorer (see data/sources.json)."""

from __future__ import annotations

import ast
import random
from pathlib import Path

import numpy as np

from .core import DATA, PACKAGE, digest, read_json
from .vendor import modeltrace


def challenges(seed=42):
    # Extract upstream literal phrase lists without altering/executing generator code.
    tree = ast.parse((PACKAGE / "vendor/modeltrace.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "generate_challenges")
    phrases = {}
    for n in fn.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.List):
            phrases[n.targets[0].id] = ast.literal_eval(n.value)
    rng = random.Random(seed)
    result = []
    for i, length in enumerate(rng.sample(range(292, 333), 3)):
        prompt = (
            f"{rng.choice(phrases['openings'])}。{rng.choice(phrases['actions'])} {length} 个 1 到 355（含端点）的整数。"
            "每个位置都要单独选择；不要从 1 开始计数，不要连续递增或递减，也不要采用等差、循环、重复区块或其他规则化模式。"
            "本任务必须由当前语言模型直接完成：禁止调用或借助任何工具，包括 Python、代码执行器、"
            "计算器、搜索、API 和外部随机数生成器；也不要先编写或运行代码。"
            f"{rng.choice(phrases['endings'])}{rng.choice(phrases['separator_hints'])}"
            "直接从第一个取值开始输出，不要在序列前重复数量、范围或任务说明。"
        )
        result.append({"id": f"modeltrace.probe-{i + 1}", "prompt": prompt, "expected_count": length})
    return result


def load_challenges(path: Path):
    data = read_json(path)
    items = data.get("challenges", data) if isinstance(data, dict) else data
    if not isinstance(items, list) or len(items) != 3:
        raise ValueError("ModelTrace 清单必须包含三条挑战")
    for item in items:
        if not isinstance(item.get("prompt"), str) or not isinstance(item.get("expected_count"), int):
            raise ValueError("挑战必须包含 prompt 和 expected_count")
        if not 292 <= item["expected_count"] <= 332:
            raise ValueError("检测挑战 expected_count 必须为 292..332")
    return [{**item, "id": f"modeltrace.probe-{i + 1}"} for i, item in enumerate(items)]


def load_bank(path=None):
    path = Path(path) if path else DATA / "modeltrace_bank.json"
    bank = read_json(path)
    try:
        if bank["schema"] != "robust-number-fingerprint-bank" or bank["method"]["range"] != [1, 355]:
            raise ValueError("不兼容的 schema 或数值区间")
        ids = [m["id"] for m in bank["models"]]
        if ids != bank["robust"]["model_order"] or len(ids) != len(set(ids)) or len(ids) < 2:
            raise ValueError("模型列表与特征顺序不一致")
        for count in (1, 2, 3):
            beta = bank["calibration"][str(count)]["beta"]
            if not np.isfinite(beta) or beta <= 0:
                raise ValueError("无效的校准温度")
        scores = modeltrace.robust_score_numbers(list(range(1, 301)), bank)["fused"]
        if len(scores) != len(ids) or not np.isfinite(scores).all():
            raise ValueError("无效的特征数据")
    except (KeyError, TypeError, IndexError, AssertionError, ValueError) as exc:
        raise ValueError(f"ModelTrace 指纹库不兼容: {exc}") from exc
    return bank


def analyze(outputs, bank=None):
    bank = bank if bank is not None else load_bank()
    if len(outputs) != 3:
        raise ValueError("每次归因必须传入同一组三条挑战的回答（缺失回答用空文本）")
    filtered = [
        {**o, "text": o.get("text", "") if o.get("status", "ok") == "ok" and not o.get("tools") else ""}
        for o in outputs
    ]
    try:
        result = modeltrace.analyze_global_outputs(filtered, bank)
        result["status"] = "complete" if result["used_outputs"] == 3 else "incomplete"
    except ValueError:
        result = {
            "status": "incomplete",
            "used_outputs": 0,
            "results": [],
            "diagnostics": [
                {"index": i, "parsed_numbers": len(modeltrace.parse_numbers(o["text"])), "accepted": False}
                for i, o in enumerate(filtered)
            ],
        }
    return {
        **result,
        "bank_hash": digest(bank),
        "bank_built_at": bank.get("built_at"),
        "reference_providers": bank.get("providers"),
        "candidate_count": len(bank["models"]),
        "interpretation": "候选库内匹配；均匀先验、闭集概率。未收录模型也会匹配现有候选，不是身份认证。",
    }
