from __future__ import annotations

import base64
import html
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

from .core import now, read_json, write_json

STYLE = """
:root{color-scheme:light}body{font:15px/1.65 system-ui,sans-serif;max-width:1200px;margin:40px auto;padding:0 24px;color:#172337;background:#f5f7fb}
h1,h2{line-height:1.3}h1{font-size:30px}h2{margin-top:36px}.muted{color:#61718a}.card,details{background:white;border:1px solid #dce3ee;border-radius:12px;padding:20px;margin:16px 0}
table{border-collapse:collapse;width:100%;background:white}th,td{text-align:left;padding:10px;border-bottom:1px solid #e6ebf2}th{color:#52627b;font-size:13px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:480px;overflow:auto;background:#f5f7fb;padding:16px;border-radius:8px}
img{max-width:100%;max-height:480px;background:white;border:1px solid #ddd}input,select,button{font:inherit;border:1px solid #bbc9dc;border-radius:6px;padding:8px;margin:4px}button{background:#215bbb;color:white;cursor:pointer}.badge{border-radius:4px;background:#e8eef8;padding:2px 6px}summary{cursor:pointer}.warning{color:#8a4300}
"""


def esc(value):
    return html.escape(str(value), quote=True)


def grade_label(grade):
    if grade.get("score") is not None:
        return (
            "通过" if grade["score"] == 1 else ("答案无法解析" if grade["status"] == "unparsed" else "未通过")
        )
    return {
        "pending_review": "待人工评阅",
        "diagnostic": "诊断记录",
        "fingerprint_pending_group": "查看指纹结果",
        "timeout": "运行超时",
        "refused": "服务端拒答",
        "truncated": "输出截断",
    }.get(grade["status"], "未评分")


def page(title, body, script=""):
    return f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{esc(title)}</title><style>{STYLE}</style><body>{body}<script>{script}</script></body></html>'


def svg_image(grade):
    preview = grade.get("preview") or {}
    if not preview.get("svg"):
        return f'<p class="muted">SVG 预览：{esc(preview.get("status", "无"))}</p>'
    data = base64.b64encode(preview["svg"].encode()).decode()
    return f'<img alt="待评阅 SVG" src="data:image/svg+xml;base64,{data}"><p class="muted">仅通过格式和预览安全检查；视觉效果待人工评阅。</p>'


def render_report(directory, manifest, records, summary):
    cases = {c["id"]: c for c in manifest["cases"]}
    body = f'<h1>dummy-llm-test</h1><p class="muted">{esc(manifest["run_id"])} · {esc(manifest["plan"]["level"])} · {esc(manifest["plan"]["mode"])}</p>'
    body += f'<div class="card">已完成 <b>{summary["completed"]}/{summary["planned"]}</b> 个评测调用。客观分数、人工评阅、模型指纹和运行故障分别呈现。</div>'
    body += "<h2>客观题与运行状态</h2><table><tr><th>目标</th><th>题集</th><th>正确 / 可评分</th><th>首轮 Wilson 95% 区间</th><th>运行状态</th></tr>"
    for g in summary["groups"]:
        ci = g["first_repeat_ci95"]
        interval = f"{ci[0]:.1%}–{ci[1]:.1%}" if ci else "—"
        fraction = f"{g['correct']}/{g['graded']}" if g["graded"] else "—"
        body += f"<tr><td>{esc(g['target'])}</td><td>{esc(g['suite'])}</td><td>{fraction}</td><td>{interval}</td><td>{esc(g['statuses'])}</td></tr>"
    body += '</table><p class="muted">重复题可能相关，区间只使用各题首轮。小样本仅供筛查，不能证明模型退化；未评分不代表答错。</p>'
    body += "<h2>人工评阅</h2>"
    if summary["manual"]:
        body += "<table><tr><th>目标</th><th>题集</th><th>已评 / 待评总数</th><th>各维度均分（0–2）</th></tr>"
        for g in summary["manual"]:
            dimensions = defaultdict(list)
            for item in g["scores"]:
                for key, value in item["scores"].items():
                    dimensions[key].append(value)
            means = {k: round(statistics.mean(v), 3) for k, v in dimensions.items()}
            body += f"<tr><td>{esc(g['target'])}</td><td>{esc(g['suite'])}</td><td>{g['reviewed']}/{g['eligible']}</td><td>{esc(means) if means else '待评阅'}</td></tr>"
        body += "</table><p>使用 review export 生成隐藏模型身份的评阅包，再使用 review import 导入评分。</p>"
    else:
        body += '<p class="muted">本次没有可评阅的开放题。</p>'
    body += "<h2>模型指纹</h2>"
    if not summary["fingerprints"]:
        body += '<p class="muted">本次未运行指纹测试。</p>'
    for fp in summary["fingerprints"]:
        body += f'<div class="card"><b>{esc(fp["target"])} · 第 {fp["repeat"] + 1} 组</b><p>{esc(fp["status"])}，有效回答 {fp["used_outputs"]}/3；候选库 {esc(fp["bank_built_at"])}</p><p class="warning">{esc(fp["interpretation"])}</p>'
        body += "<table><tr><th>候选</th><th>库内概率</th></tr>"
        for item in fp["results"]:
            body += f"<tr><td>{esc(item['model'])}</td><td>{item['probability']:.2%}</td></tr>"
        body += "</table></div>"
    body += '<h2>逐题证据</h2><input id="filter" placeholder="筛选目标、题号、状态">'
    for r in records:
        case = cases[r["case_id"]]
        label = f"{r['target']} · {r['case_id']} · {r['response']['status']} · 第 {r['repeat'] + 1} 次"
        body += f'<details data-label="{esc(label.lower())}"><summary>{esc(label)} <span class="badge">{grade_label(r["grade"])}</span></summary>'
        body += f"<p>耗时 {r['response']['elapsed']:.2f}s · 用量 {esc(r['response']['usage'])}</p>"
        if case["kind"] == "svg":
            body += svg_image(r["grade"])
        body += f"<h3>回答</h3><pre>{esc(r['response']['text'])}</pre>"
        if r["response"].get("error"):
            body += f"<pre>{esc(r['response']['error'])}</pre>"
        body += f"<h3>判分</h3><pre>{esc({k: v for k, v in r['grade'].items() if k != 'preview'})}</pre>"
        body += f"<details><summary>实际题目与参数</summary><pre>{esc(case['prompt'])}</pre><pre>{esc(manifest['config']['targets'][r['target']])}</pre></details></details>"
    script = "document.querySelector('#filter').addEventListener('input',e=>document.querySelectorAll('details[data-label]').forEach(d=>d.hidden=!d.dataset.label.includes(e.target.value.toLowerCase())));"
    (Path(directory) / "report.html").write_text(page("dummy-llm-test 报告", body, script), encoding="utf-8")


RUBRICS = {
    "svg-v1": {"subject": [0, 1, 2], "vehicle": [0, 1, 2], "riding": [0, 1, 2], "overall": [0, 1, 2]},
    "bullshit-v1": {"pushback": [0, 1, 2]},
}


def export_review(directory, output):
    from .runner import latest_records, read_records

    directory, output = Path(directory), Path(output)
    manifest = read_json(directory / "manifest.json")
    cases = {c["id"]: c for c in manifest["cases"]}
    items = []
    for r in latest_records(read_records(directory)):
        if r["grade"]["status"] != "pending_review":
            continue
        c = cases[r["case_id"]]
        items.append(
            {
                "sample_id": r["sample_id"],
                "case_id": r["case_id"],
                "prompt": c["prompt"],
                "response": r["response"]["text"],
                "rubric": r["grade"]["rubric"],
                "reference": c["metadata"].get("reference", ""),
                "preview": r["grade"].get("preview"),
                "scores": {},
                "notes": "",
            }
        )
    # Opaque IDs and deterministic hash order avoid target-group order leakage.
    items.sort(key=lambda x: x["sample_id"])
    package = {"schema_version": 1, "run_id": manifest["run_id"], "reviewer": "", "items": items}
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "review.json", package)
    body = '<h1>匿名人工评阅</h1><p>模型身份已隐藏。SVG 各维度：0 不符合，1 部分符合，2 清楚符合。错误前提题：0 接受，1 部分质疑，2 明确指出。未选择的题保持待评阅。</p><label>评阅者 <input id="reviewer"></label><button id="download">下载评分 JSON</button>'
    for i, item in enumerate(items):
        body += f'<div class="card"><h2>样本 {i + 1} · {esc(item["case_id"])}</h2><pre>{esc(item["prompt"])}</pre>'
        if item["preview"]:
            body += svg_image({"preview": item["preview"]})
        body += f"<pre>{esc(item['response'])}</pre><p>{esc(item['reference'])}</p>"
        for key in RUBRICS[item["rubric"]]:
            body += f'<label>{esc(key)} <select data-index="{i}" data-key="{key}"><option value="">待评</option><option>0</option><option>1</option><option>2</option></select></label>'
        body += (
            f'<input data-note="{i}" placeholder="备注"><p class="muted">{esc(item["sample_id"])}</p></div>'
        )
    safe_json = (
        json.dumps(package, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    script = (
        "const data="
        + safe_json
        + ";"
        + """
document.querySelector('#download').onclick=()=>{
 data.reviewer=document.querySelector('#reviewer').value.trim();
 if(!data.reviewer){alert('请填写评阅者');return;}
 document.querySelectorAll('select[data-index]').forEach(s=>{if(s.value!=='')data.items[+s.dataset.index].scores[s.dataset.key]=+s.value;else delete data.items[+s.dataset.index].scores[s.dataset.key];});
 document.querySelectorAll('[data-note]').forEach(n=>data.items[+n.dataset.note].notes=n.value);
 data.reviewed_at=new Date().toISOString();
 const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
 const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='review-scored.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
};"""
    )
    (output / "index.html").write_text(page("匿名人工评阅", body, script), encoding="utf-8")
    return len(items)


def import_review(directory, path):
    from .runner import latest_records, read_records, summarize

    directory = Path(directory)
    package = read_json(Path(path))
    manifest = read_json(directory / "manifest.json")
    if package.get("run_id") != manifest["run_id"] or package.get("schema_version") != 1:
        raise ValueError("评阅包与运行不匹配")
    if not isinstance(package.get("reviewer"), str) or not package["reviewer"].strip():
        raise ValueError("必须填写评阅者")
    rows = {r["sample_id"]: r for r in latest_records(read_records(directory))}
    additions, seen = [], set()
    for item in package.get("items", []):
        sid = item.get("sample_id")
        if sid in seen:
            raise ValueError("重复评分 sample_id")
        seen.add(sid)
        row = rows.get(sid)
        if (
            not row
            or row["grade"]["status"] != "pending_review"
            or item.get("rubric") != row["grade"]["rubric"]
        ):
            raise ValueError("无效的样本或评分标准")
        scores = item.get("scores", {})
        if not scores:
            continue
        expected = RUBRICS[item["rubric"]]
        if set(scores) != set(expected) or any(
            type(v) is not int or v not in expected[k] for k, v in scores.items()
        ):
            raise ValueError("评分维度不完整或分值不在 0/1/2 内")
        additions.append(
            {
                "sample_id": sid,
                "rubric": item["rubric"],
                "scores": scores,
                "notes": str(item.get("notes", "")),
                "reviewer": package["reviewer"].strip(),
                "reviewed_at": package.get("reviewed_at") or now(),
                "imported_at": now(),
            }
        )
    path = directory / "reviews.json"
    history = read_json(path) if path.exists() else []
    write_json(path, history + additions)
    summarize(directory)
    return len(additions)


def compare(baseline, current, output):
    from .runner import latest_records, read_records

    old = latest_records(read_records(Path(baseline)))
    new = latest_records(read_records(Path(current)))
    index = {(r["target"], r["case_id"], r["repeat"]): r for r in old}
    review_maps = []
    for directory in (baseline, current):
        path = Path(directory) / "reviews.json"
        review_maps.append({r["sample_id"]: r for r in read_json(path)} if path.exists() else {})
    pairs = []
    for r in new:
        previous = index.get((r["target"], r["case_id"], r["repeat"]))
        if not previous:
            pairs.append(
                {
                    "target": r["target"],
                    "case_id": r["case_id"],
                    "repeat": r["repeat"],
                    "status": "no_baseline",
                }
            )
            continue
        compatible = (
            previous["case_hash"] == r["case_hash"]
            and previous["target_signature"] == r["target_signature"]
            and previous["mode"] == r["mode"]
            and previous.get("grader_signature", "legacy") == r.get("grader_signature", "legacy")
            and previous["response"].get("actual_model") == r["response"].get("actual_model")
        )
        a, b = previous["grade"]["score"], r["grade"]["score"]
        pairs.append(
            {
                "target": r["target"],
                "case_id": r["case_id"],
                "suite": r["suite"],
                "repeat": r["repeat"],
                "status": "matched" if compatible else "incompatible",
                "before": a,
                "after": b,
                "delta": b - a if compatible and a is not None and b is not None else None,
                "runtime_before": previous["response"]["status"],
                "runtime_after": r["response"]["status"],
                "diagnostic_before": previous["grade"].get("reported_dates"),
                "diagnostic_after": r["grade"].get("reported_dates"),
                "manual_before": review_maps[0].get(previous["sample_id"]),
                "manual_after": review_maps[1].get(r["sample_id"]),
            }
        )
    grouped = defaultdict(list)
    for p in pairs:
        if p.get("delta") is not None:
            grouped[(p["target"], p["suite"])].append(p)
    groups = []
    for (target, suite), values in grouped.items():
        by_case = defaultdict(list)
        for value in values:
            by_case[value["case_id"]].append(value["delta"])
        deltas = [statistics.mean(v) for v in by_case.values()]
        rng = random.Random(42)
        bootstrap = (
            sorted(statistics.mean(rng.choices(deltas, k=len(deltas))) for _ in range(2000))
            if len(deltas) >= 2
            else []
        )
        groups.append(
            {
                "target": target,
                "suite": suite,
                "pairs": len(values),
                "distinct_cases": len(deltas),
                "before_accuracy": statistics.mean(v["before"] for v in values),
                "after_accuracy": statistics.mean(v["after"] for v in values),
                "case_mean_delta": statistics.mean(deltas),
                "paired_case_bootstrap_ci95": [bootstrap[49], bootstrap[1949]] if bootstrap else None,
                "evidence": "screening_only" if len(deltas) < 30 else "descriptive",
            }
        )
    old_summary = read_json(Path(baseline) / "summary.json")
    new_summary = read_json(Path(current) / "summary.json")
    result = {
        "baseline": str(Path(baseline).resolve()),
        "current": str(Path(current).resolve()),
        "pairs": pairs,
        "groups": groups,
        "fingerprints_before": old_summary.get("fingerprints", []),
        "fingerprints_after": new_summary.get("fingerprints", []),
        "note": "仅相同目标名、题目、参数、版本和模式可逐题回归。跨模型/配置结果仅作描述性对照；无自动降智结论。",
    }
    output = Path(output)
    write_json(output, result)
    body = (
        "<h1>历史对比</h1><p>"
        + esc(result["note"])
        + "</p><h2>分类变化</h2><p>按题目聚类的配对 bootstrap 95% 区间；重复次数不增加独立题目数。小样本和全相同结果可产生退化区间，不表示确定性。</p>"
    )
    for group in groups:
        body += '<div class="card"><pre>' + esc(group) + "</pre></div>"
    body += "<h2>逐题变化</h2><table><tr><th>目标 / 题目</th><th>状态</th><th>之前</th><th>之后</th><th>差值</th></tr>"
    for p in pairs:
        body += f"<tr><td>{esc(p['target'])} / {esc(p['case_id'])}</td><td>{esc(p['status'])}</td><td>{esc(p.get('before'))}</td><td>{esc(p.get('after'))}</td><td>{esc(p.get('delta'))}</td></tr>"
    body += "</table>"
    changes = [
        p
        for p in pairs
        if p.get("diagnostic_before") is not None or p.get("manual_before") or p.get("manual_after")
    ]
    if changes:
        body += "<h2>诊断自述和人工评分（单独对照）</h2><pre>" + esc(changes) + "</pre>"
    if result["fingerprints_before"] or result["fingerprints_after"]:
        body += (
            "<h2>指纹匹配（描述性对照）</h2><p>核对 bank_hash 和模式后解释。库内概率不能证明实际身份；不同指纹库概率不可直接比较。</p><pre>"
            + esc({"before": result["fingerprints_before"], "after": result["fingerprints_after"]})
            + "</pre>"
        )
    output.with_suffix(".html").write_text(page("历史对比", body), encoding="utf-8")
    return result


def regrade(directory, output):
    """Replay stored responses with today's parser/grader into a separate derived run."""
    import shutil
    from dataclasses import asdict

    from .adapters import parse_api, parse_cli
    from .core import Case, Response, digest, grading_hash
    from .runner import latest_records, read_records, summarize
    from .scoring import score

    directory, output = Path(directory).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("重新判分输出目录必须不存在，避免覆盖原始证据")
    manifest = read_json(directory / "manifest.json")
    source_id = manifest["run_id"]
    manifest["run_id"] = output.name
    manifest["derived_from"] = {
        "run_id": source_id,
        "path": str(directory),
        "operation": "offline-regrade",
        "grader_signature": grading_hash(),
        "time": now(),
        "results_hash": digest((directory / "results.jsonl").read_text()),
    }
    manifest["resume_hash"] = "derived-run-not-resumable"
    cases = {c["id"]: Case(**c) for c in manifest["cases"]}
    output.mkdir(parents=True)
    write_json(output / "manifest.json", manifest)
    for filename in ("fingerprint_bank.json", "challenges.json", "reviews.json"):
        if (directory / filename).exists():
            shutil.copyfile(directory / filename, output / filename)
    with (output / "results.jsonl").open("w") as f:
        for record in latest_records(read_records(directory)):
            response = Response(**record["response"])
            kind = manifest["config"]["targets"][record["target"]]["kind"]
            raw = response.raw
            reparsed = None
            if kind in ("codex", "claude") and isinstance(raw, dict) and "events" in raw:
                stdout = (
                    "\n".join(json.dumps(e) for e in raw["events"])
                    + "\n"
                    + "\n".join(raw.get("non_json", []))
                )
                reparsed = parse_cli(
                    stdout,
                    raw.get("stderr", ""),
                    raw.get("exit_code", 0),
                    response.status == "timeout",
                    kind,
                    record["mode"],
                    record["kind"] == "fingerprint",
                )
            elif isinstance(raw, dict) and ("choices" in raw or "output" in raw):
                reparsed = parse_api(raw, kind)
            if reparsed:
                reparsed.elapsed, reparsed.request = response.elapsed, response.request
                response = reparsed
            record.setdefault("original_grade", record["grade"])
            record.setdefault("original_response_status", record["response"]["status"])
            record["response"] = asdict(response)
            record["grade"] = score(cases[record["case_id"]], response)
            record["grader_signature"] = grading_hash()
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return summarize(output)
