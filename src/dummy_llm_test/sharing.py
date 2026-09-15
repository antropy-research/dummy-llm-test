"""Allowlisted statistics export. Never copy evidence or redact arbitrary text."""

from collections import defaultdict
from pathlib import Path

from .core import read_json, write_json
from .performance import METRICS, analyze, load_fragments, number, summarize_rows
from .performance_report import LABELS, esc, fmt, render_performance
from .report import RUBRICS, page
from .runner import latest_records, read_records

STATUSES = frozenset(
    {
        "ok",
        "timeout",
        "refused",
        "truncated",
        "empty",
        "empty_response",
        "rate_limit",
        "server_error",
        "client_error",
        "protocol_error",
        "cli_error",
        "harness_error",
        "tool_violation",
        "protocol_violation",
        "not_run",
        "cancelled",
        "network_error",
        "authentication_error",
        "api_error",
    }
)
GRADE_STATUSES = STATUSES | {
    "graded",
    "unparsed",
    "pending_review",
    "diagnostic",
    "fingerprint_pending_group",
}
STOP_REASONS = {"complete", "interrupted", "budget_exhausted", "usage_unknown", "harness_error", "running"}
NOTICE = (
    "分享统计 / Shared statistics。目标、题目、题集和样本均使用本次导出的局部别名。"
    "未包含模型身份、地址、路径、时间戳、提示词、回答、SVG、原始事件、错误正文或评阅者信息。"
    "数字成绩、输出长度和运行特征仍会公开，请在分享前检查。"
    "本文件不是原始证据，不能续跑、重判或验证回答；缺失值仍表示未提供／不支持。"
    "自报知识截止日期和候选模型匹配不在此分享包内，不能据此作身份或降智判断。"
)


def enum(value, allowed):
    return value if isinstance(value, str) and value in allowed else "other"


def export_data(records, fragments=(), reviews=()):
    aliases = defaultdict(dict)

    def alias(kind, value):
        mapping = aliases[kind]
        if value not in mapping:
            mapping[value] = f"{kind}-{len(mapping) + 1}"
        return mapping[value]

    data = analyze(records, fragments)
    rows = []
    for source in data["observations"]:
        row = {
            k: number(source.get(k))
            for k in (*METRICS, "repeat", "attempt", "retry_count", "output_characters")
        }
        row.update({k: alias(k, source[k]) for k in ("sample_id", "target", "case_id", "suite")})
        row.update(
            status=enum(source["status"], STATUSES),
            success=source["success"] is True,
            fragment_id=alias("fragment", source["fragment_id"]) if source["fragment_id"] else None,
            attempts=[
                {
                    "attempt": number(a.get("attempt")),
                    "seconds": number(a.get("seconds")),
                    "tps": number(a.get("tps")),
                    "status": enum(a.get("status"), STATUSES),
                }
                for a in source["attempts"]
            ],
        )
        rows.append(row)
    groups, targets = defaultdict(list), defaultdict(list)
    for row in rows:
        groups[(row["target"], row["suite"])].append(row)
        targets[row["target"]].append(row)
    safe_fragments = []
    fragment_numbers = (
        "concurrency",
        "retries",
        "timeout",
        "duration_seconds",
        "first_dispatch_offset_seconds",
        "last_attempt_end_offset_seconds",
        "completed_attempts",
        "successful_samples",
        "attempts_per_minute",
        "successful_samples_per_minute",
        "known_output_tokens",
        "output_usage_coverage",
        "effective_output_tokens_per_second",
        "known_output_tokens_per_second",
        "peak_inflight_attempts",
        "average_inflight_attempts",
    )
    for fragment in data["fragments"]:
        safe_fragments.append(
            {
                **{k: number(fragment.get(k)) for k in fragment_numbers},
                "fragment_id": alias("fragment", fragment["fragment_id"]),
                "stop_reason": enum(fragment["stop_reason"], STOP_REASONS),
                "target_concurrency": {
                    alias("target", k): number(v) for k, v in (fragment["target_concurrency"] or {}).items()
                },
                "throughput_scope": enum(fragment["throughput_scope"], {"complete", "known_partial"}),
                "unresolved_sample_ids": [alias("sample_id", k) for k in fragment["unresolved_sample_ids"]],
                "created_at": None,
                "finished_at": None,
                "first_dispatched_at": None,
                "last_attempt_finished_at": None,
                "concurrency_events": [
                    {k: number(e.get(k)) for k in ("offset_seconds", "inflight_attempts")}
                    for e in fragment["concurrency_events"]
                ],
            }
        )
    grades = [
        {
            "sample_id": alias("sample_id", r["sample_id"]),
            "status": enum(r.get("grade", {}).get("status"), GRADE_STATUSES),
            "score": number(r.get("grade", {}).get("score"))
            if r.get("kind") in {"exact", "choice", "rules", "candy"}
            else None,
            "compatibility_score": number(r.get("grade", {}).get("compatibility_score"))
            if r.get("kind") == "candy"
            else None,
        }
        for r in records
    ]
    manual = []
    sample_ids = {r["sample_id"] for r in records}
    for review in reviews:
        rubric = review.get("rubric")
        if review.get("sample_id") not in sample_ids or not isinstance(rubric, str) or rubric not in RUBRICS:
            continue
        manual.append(
            {
                "sample_id": alias("sample_id", review["sample_id"]),
                "rubric": rubric,
                "scores": {
                    k: v
                    for k, v in review.get("scores", {}).items()
                    if k in RUBRICS[rubric] and type(v) is int and v in RUBRICS[rubric][k]
                },
            }
        )
    return {
        "schema_version": 1,
        "kind": "sanitized_statistics_not_raw_evidence",
        "notice": NOTICE,
        "objective_grades": grades,
        "human_reviews": manual,
        "performance": {
            "observations": rows,
            "fragments": safe_fragments,
            "targets": [{"target": k, **summarize_rows(v)} for k, v in targets.items()],
            "groups": [{"target": k[0], "suite": k[1], **summarize_rows(v)} for k, v in groups.items()],
        },
    }


def write_export(data, output):
    output = Path(output)
    if output.exists():
        raise ValueError("分享输出目录已存在；请指定新目录")
    output.mkdir(parents=True)
    write_json(output / "share.json", data)
    body = "<h1>dummy-llm-test · 分享统计</h1><p>" + esc(NOTICE) + "</p>"
    if data.get("synthetic") is True:
        body += '<p class="warning">完全离线合成数据 / Synthetic demo; not real model results.</p>'
    body += render_performance(data["performance"])
    body += "<h2>逐题观测</h2><table><tr><th>样本 / 目标 / 题目 / 题集 / repeat / attempt</th><th>状态</th><th>重试</th>"
    body += "".join(f"<th>{LABELS[m]}</th>" for m in METRICS) + "</tr>"
    for row in data["performance"]["observations"]:
        identity = " / ".join(
            str(row[k]) for k in ("sample_id", "target", "case_id", "suite", "repeat", "attempt")
        )
        body += f"<tr><td>{esc(identity)}</td><td>{esc(row['status'])}</td><td>{fmt(row['retry_count'])}</td>"
        body += "".join(f"<td>{fmt(row[m])}</td>" for m in METRICS) + "</tr>"
    body += "</table><h2>客观评分（与调用成功分开）</h2><p>严格分与 Candy 上游兼容分分列；兼容分不纳入严格正确率。</p><table><tr><th>样本</th><th>状态</th><th>严格分</th><th>Candy 兼容分</th></tr>"
    for grade in data["objective_grades"]:
        body += f"<tr><td>{esc(grade['sample_id'])}</td><td>{esc(grade['status'])}</td><td>{fmt(grade['score'])}</td><td>{fmt(grade['compatibility_score'])}</td></tr>"
    body += "</table><h2>人工评阅（独立评分）</h2><pre>" + esc(data["human_reviews"]) + "</pre>"
    html = page("dummy-llm-test · Shared statistics", body).replace("<script></script>", "")
    html = html.replace(
        '<meta charset="utf-8">',
        "<meta charset=\"utf-8\"><meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'\">",
    )
    (output / "index.html").write_text(html, encoding="utf-8")
    (output / "README.txt").write_text(
        NOTICE + "\nOpen index.html locally. No server or API key required.\n", encoding="utf-8"
    )


def export_run(directory, output):
    directory, output = Path(directory).resolve(), Path(output).resolve()
    if output == directory or directory in output.parents:
        raise ValueError("分享目录必须位于原始运行目录之外")
    records = latest_records(read_records(directory))
    if not records:
        raise ValueError("没有可导出的样本")
    reviews = read_json(directory / "reviews.json") if (directory / "reviews.json").exists() else []
    data = export_data(records, load_fragments(directory), reviews)
    write_export(data, output)
    return data
