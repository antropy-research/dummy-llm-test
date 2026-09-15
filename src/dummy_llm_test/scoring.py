from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

from defusedxml import ElementTree as SafeET

from .core import Case, Response


def final_answer(text):
    text = text.strip()
    # Only a final-answer marker, a standalone final line, or an unambiguous Chinese conclusion.
    markers = re.findall(r"(?im)^\s*(?:\*\*)?(?:final answer|最终答案|答案)\s*[:：]\s*(.+)$", text)
    last = markers[-1] if markers else (text.splitlines()[-1] if text else "")
    last = last.strip().strip("*` $。.!！")
    boxed = re.fullmatch(r"\\boxed\{([^{}]+)\}", last)
    if boxed:
        last = boxed.group(1)
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?|[A-Za-z0-9\u4e00-\u9fff]+", last):
        return last
    numeric_conclusion = re.fullmatch(r"([-+]?\d+(?:\.\d+)?)\s*(?:更大|个|颗|米|克)(?:糖果)?", last)
    if numeric_conclusion:
        return numeric_conclusion.group(1)
    minimum_conclusion = re.search(
        r"[*`]*(\d+)\s*个(?:糖果)?(?:是|为)最少(?:的保证数目|的数量|的个数)?[*`]*[。.!！\s]*$", last
    )
    if minimum_conclusion:
        return minimum_conclusion.group(1)
    match = re.search(
        r"(?:最少(?:需要|要|取出|取)?|答案(?:是|为)|需要(?:取出)?|应(?:该)?取出)\s*[*`]*\s*(\d+)\s*[*`]*\s*(?:个|颗)(?:糖果|糖)?[。.!！\s*`]*$",
        last,
    )
    return match.group(1) if match else None


def check_rules(text, rules):
    checks = {}
    if "json_equals" in rules:
        try:
            checks["json_equals"] = json.dumps(json.loads(text), sort_keys=True) == json.dumps(
                rules["json_equals"], sort_keys=True
            )
        except (ValueError, TypeError):
            checks["json_equals"] = False
    if "lines_equal" in rules:
        checks["lines_equal"] = text.strip().splitlines() == rules["lines_equal"]
    if "word_count" in rules:
        word, count = rules["word_count"]
        checks["word_count"] = len(re.findall(r"\b" + re.escape(word) + r"\b", text)) == count
    if "exclude_chars" in rules:
        checks["exclude_chars"] = not any(c in text for c in rules["exclude_chars"])
    if "min_words" in rules:
        checks["min_words"] = len(re.findall(r"\b[A-Za-z]+\b", text)) >= rules["min_words"]
    if "wrapper" in rules:
        prefix, suffix = rules["wrapper"]
        t = text.strip()
        wrapped = t.startswith(prefix) and t.endswith(suffix)
        checks["wrapper"] = wrapped
        if "inner_words" in rules:
            inner = t[len(prefix) : -len(suffix)] if wrapped else ""
            checks["inner_words"] = (
                wrapped and len(re.findall(r"\b[A-Za-z]+\b", inner)) == rules["inner_words"]
            )
    supported = {
        "json_equals",
        "lines_equal",
        "word_count",
        "exclude_chars",
        "min_words",
        "wrapper",
        "inner_words",
    }
    if set(rules) - supported or not checks:
        raise ValueError("未知或空指令评分规则")
    return checks


def safe_svg(text):
    """Return a self-contained SVG for img embedding; never inline untrusted XML in HTML."""
    if len(text.encode()) > 2_000_000:
        return {"status": "too_large", "svg": None}
    if re.search(r"<!DOCTYPE|<!ENTITY", text, re.I):
        return {"status": "unsafe_xml", "svg": None}
    match = re.search(r"<svg\b[\s\S]*?</svg\s*>", text, re.I)
    if not match:
        return {"status": "no_complete_svg", "svg": None}
    try:
        root = SafeET.fromstring(match.group())
    except (ET.ParseError, ValueError) as exc:
        return {"status": "parse_error", "error": str(exc), "svg": None}
    tags = {
        "svg",
        "g",
        "path",
        "circle",
        "ellipse",
        "rect",
        "line",
        "polyline",
        "polygon",
        "defs",
        "use",
        "symbol",
        "clipPath",
        "mask",
        "linearGradient",
        "radialGradient",
        "stop",
        "title",
        "desc",
        "text",
        "tspan",
        "style",
    }
    stack = [(root, 0)]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if depth > 64 or count > 5000:
            return {"status": "too_complex", "svg": None}
        tag = node.tag.split("}")[-1]
        ns = node.tag.split("}")[0].lstrip("{") if "}" in node.tag else ""
        if tag not in tags or ns not in ("", "http://www.w3.org/2000/svg"):
            return {"status": "forbidden_element", "svg": None}
        values = [node.text or ""] if tag == "style" else []
        for key, value in node.attrib.items():
            key = key.split("}")[-1]
            if key.lower().startswith("on") or key in ("base", "src"):
                return {"status": "forbidden_attribute", "svg": None}
            if key == "href" and not re.fullmatch(r"#[A-Za-z_][\w:.-]*", value):
                return {"status": "external_reference", "svg": None}
            values.append(value)
        for value in values:
            # Reject CSS escaping/comments to prevent obfuscated imports or URLs.
            if any(
                s in value.lower()
                for s in ("@import", "javascript:", "data:", "http:", "https:", "expression(", "/*", "\\")
            ):
                return {"status": "unsafe_style_or_reference", "svg": None}
            for ref in re.findall(r"url\s*\((.*?)\)", value, re.I):
                if not re.fullmatch(r"['\"]?#[\w:.-]+['\"]?", ref.strip()):
                    return {"status": "external_reference", "svg": None}
        stack.extend((child, depth + 1) for child in node)
    # Root from the regex is always svg; normalize namespace for reliable img rendering.
    if "}" not in root.tag:
        root.set("xmlns", "http://www.w3.org/2000/svg")
    return {
        "status": "valid_svg",
        "svg": ET.tostring(root, encoding="unicode"),
        "elements": count,
        "note": "格式与预览安全检查，不是视觉正确性评分",
    }


def score(case: Case, response: Response):
    if response.status != "ok":
        return {"status": response.status, "score": None, "kind": case.kind}
    text = response.text.strip()
    result = {"kind": case.kind, "score": None}
    if case.kind in ("exact", "choice", "candy"):
        answer = final_answer(text)
        result.update(
            status="graded" if answer is not None else "unparsed",
            answer=answer,
            score=int(answer == str(case.expected)),
        )
        if case.kind == "candy":
            result["compatibility_score"] = int(bool(re.search(r"(?<!\d)21(?!\d)", text)))
            result["compatibility_note"] = "上游规则；正文出现 21 也可能误判，不纳入严格正确率"
    elif case.kind == "rules":
        checks = check_rules(text, case.expected)
        result.update(status="graded", score=int(all(checks.values())), checks=checks)
    elif case.kind in ("svg", "manual"):
        result.update(status="pending_review", rubric="svg-v1" if case.kind == "svg" else "bullshit-v1")
        if case.kind == "svg":
            result["preview"] = safe_svg(text)
    elif case.kind == "diagnostic":
        dates = re.findall(r"\b(?:19|20)\d{2}(?:\s*[-/年]\s*\d{1,2}\s*月?)?\b", text)
        months = re.findall(
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+(?:19|20)\d{2}\b",
            text,
            re.I,
        )
        result.update(status="diagnostic", reported_dates=months or dates, note="模型自述；无统一真值")
    else:
        result.update(status="fingerprint_pending_group")
    return result
