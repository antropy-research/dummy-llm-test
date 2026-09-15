"""Local HTML/SVG performance views. Only finite measured values enter plots."""

from __future__ import annotations

import html
import json
import math

from .performance import METRICS, number, observation

LABELS = {
    "attempt_seconds": "最终尝试耗时 s",
    "sample_seconds": "样本总耗时 s",
    "queue_wait_seconds": "调度等待 s",
    "output_tokens": "输出 token",
    "final_attempt_tps": "最终尝试 TPS",
    "effective_tps": "样本有效 TPS",
    "first_visible_text_seconds": "首个可见文本延迟 s",
    "visible_text_receive_seconds": "可见文本接收时长 s",
}


def esc(value):
    return html.escape(str(value), quote=True)


def fmt(value, percent=False):
    if value is None or not isinstance(value, (float, int)) or not math.isfinite(value):
        return "未提供／不支持"
    return f"{value * 100:.1f}%" if percent else f"{value:.3g}"


def plot(rows, kind):
    width, height = 560, 220
    svg = f'<svg role="img" viewBox="0 0 {width} {height}" style="width:100%;max-width:600px"><rect width="560" height="220" fill="#fff"/>'
    if kind == "histogram":
        values = [r["sample_seconds"] for r in rows if number(r["sample_seconds"]) is not None]
        if not values:
            return '<p class="muted">样本耗时分布：未提供／不支持</p>'
        maximum = max(values) or 1
        bins = [0] * 10
        for value in values:
            bins[min(9, int(value / maximum * 10))] += 1
        for index, count in enumerate(bins):
            bar_height = count / max(bins) * 155
            label = f"{index * maximum / 10:.3g}–{(index + 1) * maximum / 10:.3g}s：{count} 个样本"
            svg += f'<rect x="{45 + index * 48}" y="{180 - bar_height}" width="44" height="{bar_height}" fill="#426ddd"><title>{esc(label)}</title></rect>'
        svg += f'<text x="45" y="205">0</text><text x="410" y="205">{maximum:.3g} s</text><text x="45" y="18">样本总耗时分布（成功样本，含重试）n={len(values)}</text>'
    elif kind == "scatter":
        valid = [
            r
            for r in rows
            if number(r["output_tokens"]) is not None and number(r["attempt_seconds"]) is not None
        ]
        if not valid:
            return '<p class="muted">输出 token—耗时散点图：未提供／不支持</p>'
        max_x = max(r["output_tokens"] for r in valid) or 1
        max_y = max(r["attempt_seconds"] for r in valid) or 1
        svg += '<path d="M45 25 V180 H535" fill="none" stroke="#718096"/>'
        for row in valid:
            x, y = 45 + row["output_tokens"] / max_x * 480, 180 - row["attempt_seconds"] / max_y * 150
            label = f"{row['sample_id']} / {row['case_id']} / repeat={row['repeat']} / attempt={row['attempt']} / {row['status']} / {row['output_tokens']} token / {row['attempt_seconds']:.3g}s"
            color = "#426ddd" if row["success"] else "#c05621"
            svg += f'<circle cx="{x}" cy="{y}" r="4" fill="{color}" opacity=".7"><title>{esc(label)}</title></circle>'
        svg += f'<text x="45" y="18">最终尝试耗时（纵轴 0–{max_y:.3g}s）</text><text x="45" y="205">输出 token（横轴 0–{max_x:.3g}）；蓝=成功，橙=异常</text>'
    return svg + "</svg>"


def concurrency_plot(fragment):
    events = fragment["concurrency_events"]
    duration = fragment["duration_seconds"]
    if not events or not duration:
        return ""
    start = fragment["first_dispatch_offset_seconds"]
    peak = fragment["peak_inflight_attempts"] or 1
    path, previous = "M40 170", 0
    for event in events:
        x = 40 + (event["offset_seconds"] - start) / duration * 490
        path += f" H{x:.3f} V{170 - event['inflight_attempts'] / peak * 140:.3f}"
        previous = event["inflight_attempts"]
    return f'<svg role="img" viewBox="0 0 560 205" style="width:100%;max-width:600px"><title>在途尝试数；重试等待不计为请求</title><path d="{path}" fill="none" stroke="#426ddd" stroke-width="2"/><text x="40" y="195">0–{duration:.3g}s；实际峰值 {peak}，末值 {previous}</text></svg>'


def render_sample(record):
    row = observation(record)
    body = "<h3>性能观测</h3><table><tr><th>指标</th><th>值</th></tr>"
    for metric in METRICS:
        body += f"<tr><td>{LABELS[metric]}</td><td>{fmt(row[metric])}</td></tr>"
    body += f"<tr><td>重试次数</td><td>{fmt(row['retry_count'])}</td></tr></table>"
    body += '<p class="muted">TPS 使用服务端报告的总输出 token，可能包含推理 token；不是纯生成速度。调度等待不是服务端排队。</p>'
    body += (
        "<details><summary>尝试、UTC 时间与缺失原因</summary><pre>"
        + esc(
            json.dumps(
                {
                    "sample_id": row["sample_id"],
                    "timing": record.get("timing"),
                    "attempts": row["attempts"],
                    "missing_reasons": row["missing_reasons"],
                    "generation_rate_reason": row["generation_rate_reason"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        + "</pre></details>"
    )
    events = (record["response"].get("stream") or {}).get("events") or []
    if events:
        body += "<details><summary>最终尝试流式事件到达顺序（原始内容见 JSONL）</summary><table><tr><th>序号</th><th>类型</th><th>相对请求开始 s</th><th>UTC</th></tr>"
        for event in events:
            body += f"<tr><td>{esc(event['index'])}</td><td>{esc(event['type'])}</td><td>{fmt(event['offset_seconds'])}</td><td>{esc(event['received_at'])}</td></tr>"
        body += "</table></details>"
    return body


def render_performance(data):
    body = "<h2>运行性能</h2><p>成功指正常返回非空回答，不要求答题正确。耗时越低越好；TPS 的 P95 是较快样本，P5 表示慢端。小样本只作描述，不是能力降智证据。</p>"
    for label, groups in (("按目标", data["targets"]), ("按目标和题集", data["groups"])):
        body += f"<h3>{label}：成功样本</h3><table><tr><th>目标 / 题集</th><th>指标</th><th>n</th><th>P5</th><th>P50</th><th>P95</th><th>成功输出用量覆盖率</th></tr>"
        for group in groups:
            for metric in METRICS:
                values = group["success_metrics"][metric]
                body += f"<tr><td>{esc(group['target'])} / {esc(group.get('suite', '全部'))}</td><td>{LABELS[metric]}</td><td>{values['n']}</td><td>{fmt(values['p5'])}</td><td>{fmt(values['p50'])}</td><td>{fmt(values['p95'])}</td><td>{fmt(group['success_output_usage_coverage'], True)}</td></tr>"
        body += "</table>"
    body += "<h3>异常与重试（独立统计）</h3><table><tr><th>目标 / 题集</th><th>样本数</th><th>最终状态 / 占比</th><th>故障率</th><th>重试率</th><th>各次尝试状态</th></tr>"
    for group in data["targets"] + data["groups"]:
        statuses = "; ".join(
            f"{k}: {v} ({fmt(group['status_rates'][k], True)})" for k, v in group["statuses"].items()
        )
        body += f"<tr><td>{esc(group['target'])} / {esc(group.get('suite', '全部'))}</td><td>{group['samples']}</td><td>{esc(statuses)}</td><td>{fmt(group['failure_rate'], True)}</td><td>{fmt(group['retry_rate'], True)}</td><td>{esc(group['attempt_statuses'])}</td></tr>"
    body += '</table><p class="muted">故障率包含超时、截断、拒答等非成功状态；重试率分母为有尝试记录的样本，不是失败尝试占比。</p>'
    for target in data["targets"]:
        rows = [r for r in data["observations"] if r["target"] == target["target"]]
        body += "<h3>" + esc(target["target"]) + "：分布与输出长度</h3>"
        body += plot([r for r in rows if r["success"]], "histogram") + plot(rows, "scatter")
    body += "<h3>各次启动的执行片段</h3><p>每次续跑独立计时，不包含两次启动之间的离线间隔。在途数指实际 API/CLI 尝试，重试等待不计入；整体吞吐量不由单请求 TPS 相加。</p>"
    if not data["fragments"]:
        body += '<p class="muted">未提供／不支持：旧记录没有执行片段观测。</p>'
    for fragment in data["fragments"]:
        body += f'<div class="card"><b>{esc(fragment["fragment_id"])}</b> · {esc(fragment["stop_reason"])}<p>{esc(fragment["created_at"])} → {esc(fragment["finished_at"])}</p><table>'
        body += f"<tr><td>首次派发 → 最后尝试结束（UTC）</td><td>{esc(fragment['first_dispatched_at'] or '未提供／不支持')} → {esc(fragment['last_attempt_finished_at'] or '未提供／不支持')}</td></tr>"
        for label, key in (
            ("执行片段时长 s", "duration_seconds"),
            ("有效输出吞吐量 token/s", "effective_output_tokens_per_second"),
            ("已知部分吞吐量 token/s", "known_output_tokens_per_second"),
            ("成功样本用量覆盖率", "output_usage_coverage"),
            ("完成尝试 / 分钟", "attempts_per_minute"),
            ("成功样本 / 分钟", "successful_samples_per_minute"),
            ("实际峰值并发", "peak_inflight_attempts"),
            ("实际平均并发", "average_inflight_attempts"),
        ):
            body += f"<tr><td>{label}</td><td>{fmt(fragment[key], key == 'output_usage_coverage')}</td></tr>"
        body += "</table>" + concurrency_plot(fragment) + "</div>"
    return body


def render_comparison(data):
    body = "<h2>性能历史对照</h2><p>只有条件一致且两次都成功的样本计算耗时/TPS 差值。百分比以之前值为分母，之前为零时未提供。请同时检查输出长度和故障率；没有自动性能回归或能力结论。</p>"
    coverage = data["coverage"]
    body += f"<p>基线完成/计划：{coverage['baseline_completed']}/{fmt(coverage['baseline_planned'])}；当前完成/计划：{coverage['current_completed']}/{fmt(coverage['current_planned'])}。全部已完成样本的故障率：{fmt(coverage['baseline_all']['failure_rate'], True)} → {fmt(coverage['current_all']['failure_rate'], True)}。</p>"
    if coverage["without_current_record"]:
        body += (
            '<details class="warning"><summary>基线样本未产生当前记录：不得把缺失视为成功或变快</summary><pre>'
            + esc(json.dumps(coverage["without_current_record"], ensure_ascii=False, indent=2))
            + "</pre></details>"
        )
    body += "<h3>按目标与题集</h3>"
    for group in data["groups"]:
        before, after = group["before_all"], group["after_all"]
        body += f"<h4>{esc(group['target'])} / {esc(group['suite'])} · 匹配 {group['matched_samples']} · 条件不同 {group['conditions_differ']}</h4>"
        body += f"<p>并排描述（含条件不同样本）：故障率 {fmt(before['failure_rate'], True)} → {fmt(after['failure_rate'], True)}；成功样本输出用量覆盖率 {fmt(before['success_output_usage_coverage'], True)} → {fmt(after['success_output_usage_coverage'], True)}。</p>"
        body += "<table><tr><th>匹配且双侧成功的样本</th><th>n</th><th>之前 P50</th><th>之后 P50</th><th>绝对变化</th><th>变化 %</th></tr>"
        for metric, values in group["metrics"].items():
            delta = values["p50_change"]
            body += f"<tr><td>{LABELS[metric]}</td><td>{values['n']}</td><td>{fmt(delta['before'])}</td><td>{fmt(delta['after'])}</td><td>{fmt(delta['absolute'])}</td><td>{fmt(delta['percent'])}</td></tr>"
        length = group["output_characters_p50_change"]
        body += f"<tr><td>回答字符数 P50</td><td>双侧成功</td><td>{fmt(length['before'])}</td><td>{fmt(length['after'])}</td><td>{fmt(length['absolute'])}</td><td>{fmt(length['percent'])}</td></tr></table>"
        body += '<p class="muted">各指标只用双侧都有值的同一批样本；故障率来自全部可对齐样本。描述统计，不作显著性或降智判断。</p>'
    body += "<table><tr><th>目标 / 题目 / repeat</th><th>条件</th><th>指标</th><th>之前</th><th>之后</th><th>绝对变化</th><th>变化 %</th></tr>"
    for row in data["pairs"]:
        before = row["before"] or {}
        status_note = f"{before.get('status', '未提供')} → {row['after']['status']}; 字符 {fmt(before.get('output_characters'))} → {fmt(row['after']['output_characters'])}"
        for metric in METRICS:
            delta = row["changes"].get(metric, {})
            body += f"<tr><td>{esc(row['target'])} / {esc(row['case_id'])} / {row['repeat']}</td><td>{esc(row['status'])} {esc(row['different_conditions'])}<br>{esc(status_note)}</td><td>{LABELS[metric]}</td><td>{fmt((row['before'] or {}).get(metric))}</td><td>{fmt(row['after'].get(metric))}</td><td>{fmt(delta.get('absolute'))}</td><td>{fmt(delta.get('percent'))}</td></tr>"
    return body + "</table>"
