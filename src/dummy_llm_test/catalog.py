from __future__ import annotations

import itertools
import random
from functools import lru_cache
from pathlib import Path

from .core import DATA, Case, read_json
from .fingerprint import challenges, load_challenges
from .vendor.openenv_tasks import all_tasks


@lru_cache(maxsize=64)
def candy_solution(counts=(7, 9, 8, 7, 6, 4)):
    """Exhaust all failure samples, independently of model output or upstream answer."""
    bad = set()
    for a, p, w, sa, sp, sw in itertools.product(*(range(n + 1) for n in counts)):
        if not ((a and sp) or (p and sa)):
            bad.add((a + p + w, sa + sp + sw))
    valid = [
        (r + s, r, s)
        for r in range(sum(counts[:3]) + 1)
        for s in range(sum(counts[3:]) + 1)
        if (r, s) not in bad
    ]
    best = min(v[0] for v in valid)
    return {
        "answer": best,
        "selections": [[r, s] for n, r, s in valid if n == best],
        "blind_answer": 1 + max(r + s for r, s in bad),
    }


def candy_cases():
    yield Case(
        "candy.original",
        "candy",
        (DATA / "candy_prompt.txt").read_text(),
        "candy",
        "21",
        metadata={"protocol": "upstream-prompt", "compatibility_answer": 21},
    )
    variants = [
        (7, 9, 8, 7, 6, 4),
        (2, 3, 1, 3, 2, 1),
        (4, 2, 3, 2, 4, 2),
        (3, 4, 2, 4, 3, 1),
        (5, 3, 2, 2, 5, 3),
        (2, 5, 3, 4, 2, 1),
        (4, 4, 1, 3, 3, 2),
        (6, 2, 3, 3, 5, 2),
        (3, 6, 1, 5, 2, 3),
    ]
    for i, values in enumerate(variants):
        solved = candy_solution(values)
        prompt = (
            "袋中有苹果、桃子、西瓜三种口味的糖果。圆形和五角星形可以用手感分辨，口味不能分辨。\n"
            "你可以事先决定分别取多少个圆形和五角星形，并按形状挑选；同一形状内不能挑选口味。\n"
            f"圆形的苹果、桃子、西瓜分别有 {values[0]}、{values[1]}、{values[2]} 个；"
            f"五角星形分别有 {values[3]}、{values[4]}、{values[5]} 个。\n"
            "最少共取多少个，才能保证至少出现圆形苹果配五角星桃子，或圆形桃子配五角星苹果？"
            "最后一行用 Final Answer: 整数 给出答案。"
        )
        yield Case(
            f"candy.explicit-{i}",
            "candy",
            prompt,
            expected=str(solved["answer"]),
            metadata={"counts": values, "oracle": solved, "protocol": "local-explicit-shape-selection"},
        )


def basic_cases():
    specs = [
        ("decimal", "比较十进制小数 9.11 和 9.9，哪个更大？", "9.9"),
        ("strawberry", "英文单词 strawberry 中有几个小写字母 r？", "3"),
        ("decimal-negative", "比较十进制小数 -9.11 和 -9.9，哪个更大？", "-9.11"),
        ("decimal-zero", "0.09 和 0.010 哪个更大？", "0.09"),
        ("count-r", "字符串 rrRrr 中有几个小写 r？区分大小写。", "4"),
        ("count-cn", "字符串 哈哈哈呵哈哈 中有几个 哈 字？", "5"),
        ("units", "1.5 千米加上 250 米，共多少米？", "1750"),
        ("weight", "0.75 千克减去 250 克，共多少克？", "500"),
        ("ratio", "12 个盒子，每盒 8 支笔，取走 19 支，还剩多少支？", "77"),
        ("rank", "从低到高排序，甲低于乙，乙低于丙。谁排第二？", "乙"),
        ("queue", "队伍从前到后为 A B C D，B 移到末尾，第二个是谁？", "C"),
        ("reverse", "把字符序列 a1b2c3 逐字符逆序。", "3c2b1a"),
    ]
    for name, prompt, expected in specs:
        yield Case(f"basic.{name}", "basic", prompt + " 只输出答案，不要解释。", expected=expected)


def instruction_cases():
    for i in range(2):
        word = ["orchid", "cobalt"][i]
        yield Case(
            f"instruction.json-{i}",
            "instruction",
            f'只输出合法 JSON 对象，恰好包含键 "label" 和 "count"，值分别为 "{word}" 和 {i + 3}。',
            "rules",
            {"json_equals": {"label": word, "count": i + 3}},
        )
        yield Case(
            f"instruction.lines-{i}",
            "instruction",
            f"输出 {i + 3} 行，每行只能包含一个大写字母 X。不要空行或解释。",
            "rules",
            {"lines_equal": ["X"] * (i + 3)},
        )
        yield Case(
            f"instruction.include-{i}",
            "instruction",
            f"写一个英文句子，必须恰好出现 {i + 2} 次单词 {word}。只输出句子。",
            "rules",
            {"word_count": [word, i + 2]},
        )
        yield Case(
            f"instruction.exclude-{i}",
            "instruction",
            "用英语写一句问候语，至少 3 个单词，不允许出现字母 e 或 E。不要解释。",
            "rules",
            {"exclude_chars": "eE", "min_words": 3},
        )
        yield Case(
            f"instruction.wrapper-{i}",
            "instruction",
            f"用英语输出恰好三个单词，必须以 [{word}] 开头，以 [/end] 结尾。标签不算单词。",
            "rules",
            {"wrapper": [f"[{word}]", "[/end]"], "inner_words": 3},
        )
        yield Case(
            f"instruction.csv-{i}",
            "instruction",
            f"只输出两行 CSV：表头 name,value，数据行为 {word},{i + 7}。不要代码围栏或解释。",
            "rules",
            {"lines_equal": ["name,value", f"{word},{i + 7}"]},
        )


def context_cases(seed):
    for length in (4096, 16384, 65536, 131072):
        for i, fraction in enumerate((0.15, 0.85)):
            rng = random.Random(f"{seed}:{length}:{i}")
            lines = []
            while sum(map(len, lines)) < length:
                lines.append(f"item-{len(lines):05d}: {rng.getrandbits(64):016x}\n")
            answer = f"{rng.getrandbits(64):016x}"
            pos = int(len(lines) * fraction)
            lines.insert(pos, f"TARGET-ACCESS-CODE: {answer}\n")
            text = "".join(lines)
            prompt = (
                f"从以下记录中找出 TARGET-ACCESS-CODE 的精确值。只输出这个值。\n<records>\n{text}</records>"
            )
            yield Case(
                f"context.{length}-{i}",
                "context",
                prompt,
                expected=answer,
                metadata={
                    "nominal_chars": length,
                    "actual_chars": len(text),
                    "position_fraction": fraction,
                    "note": "字符长度，不是 tokenizer 测得的 token 长度",
                },
            )


def catalog(config):
    from .scoring import check_rules

    cases = list(candy_cases()) + list(basic_cases()) + list(instruction_cases())
    cases.append(
        Case(
            "svg.pelican-original",
            "svg",
            "Generate an SVG of a pelican riding a bicycle",
            "svg",
            metadata={"subject": "pelican", "vehicle": "bicycle", "protocol": "simon-original"},
        )
    )
    for task in all_tasks():
        cases.append(Case("svg.openenv-" + task.task_id, "svg", task.prompt, "svg", metadata=task.to_dict()))
    cases.extend(
        [
            Case(
                "diagnostic.cutoff-zh",
                "diagnostic",
                "你的知识截止日期是什么时候？请说明到年、月；不确定请直说。",
                "diagnostic",
            ),
            Case(
                "diagnostic.cutoff-en",
                "diagnostic",
                "What is your knowledge cutoff date? Give the year and month, or say if you are unsure.",
                "diagnostic",
            ),
        ]
    )
    source = read_json(DATA / "collatz/test.json")
    cases.append(
        Case(
            "collatz.original",
            "collatz",
            source["user_prompt"],
            expected=source["expected"],
            system=source["system_prompt"],
            metadata={"protocol": "upstream-with-user-intuition"},
        )
    )
    for item in read_json(DATA / "simplebench.json")["eval_data"]:
        cases.append(
            Case(
                f"simplebench.{item['question_id']}",
                "simplebench",
                item["prompt"],
                "choice",
                item["answer"],
                system=(DATA / "simplebench_system.txt").read_text().strip(),
            )
        )
    for technique in read_json(DATA / "bullshitbench.json")["techniques"]:
        for item in technique["questions"]:
            cases.append(
                Case(
                    f"bullshitbench.{item['id']}",
                    "bullshitbench",
                    item["question"],
                    "manual",
                    metadata={
                        "rubric": "bullshit-v1",
                        "reference": item["nonsensical_element"],
                        "domain": item["domain_group"],
                        "technique": item["technique"],
                    },
                )
            )
    cases.extend(context_cases(config["seed"]))
    probes = (
        load_challenges(Path(config["challenges"]))
        if config.get("challenges")
        else challenges(config["seed"])
    )
    for item in probes:
        cases.append(
            Case(
                item["id"],
                "modeltrace",
                item["prompt"],
                "fingerprint",
                metadata={"expected_count": item["expected_count"]},
            )
        )
    for path in config.get("custom_cases", []):
        for item in read_json(Path(path)):
            try:
                cases.append(Case(**item))
            except TypeError as exc:
                raise ValueError(f"自定义题目格式无效: {exc}") from exc
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("题目 ID 必须唯一")
    for c in cases:
        if not all(isinstance(v, str) and v for v in (c.id, c.suite, c.prompt)):
            raise ValueError("题目 id、suite、prompt 必须是非空字符串")
        if c.kind == "rules":
            if not isinstance(c.expected, dict):
                raise ValueError("rules 题目的 expected 必须是规则对象")
            check_rules("", c.expected)
        if c.kind not in ("exact", "choice", "candy", "rules", "svg", "manual", "diagnostic", "fingerprint"):
            raise ValueError(f"未知评分器: {c.kind}")
    return cases


def select(config, level):
    if level not in config["levels"]:
        raise ValueError(f"未知 level: {level}")
    spec = config["levels"][level]
    cases = catalog(config)
    known = {c.id for c in cases}
    unknown = set(spec.get("cases", [])) - known
    if unknown:
        raise ValueError(f"未知题目: {sorted(unknown)}")
    suites = spec.get("suites", [])
    unknown_suites = set(suites) - {"*"} - {c.suite for c in cases}
    if unknown_suites:
        raise ValueError(f"未知题集: {sorted(unknown_suites)}")
    selected = [
        c
        for c in cases
        if (c.id in spec.get("cases", []) or c.suite in suites or "*" in suites)
        and c.suite not in config.get("disabled_suites", [])
        and c.id not in config.get("disabled_cases", [])
    ]
    if spec.get("cases") and not suites:
        selected.sort(key=lambda c: spec["cases"].index(c.id))
    if not selected:
        raise ValueError("没有启用的题目")
    probes = [c for c in selected if c.kind == "fingerprint"]
    if probes and len(probes) != 3:
        raise ValueError("ModelTrace 必须按三条挑战整组选取")
    return selected
