"""Versioned performance observations; unknown values stay unknown."""

from __future__ import annotations

import math
import threading
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from .core import digest, now, read_json, write_json
from .streaming import visible_metrics

SCHEMA = 1
METRICS = (
    "attempt_seconds",
    "sample_seconds",
    "queue_wait_seconds",
    "output_tokens",
    "final_attempt_tps",
    "effective_tps",
    "first_visible_text_seconds",
    "visible_text_receive_seconds",
)


def number(value):
    return (
        value
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
        else None
    )


def divide(numerator, denominator):
    a, b = number(numerator), number(denominator)
    return a / b if a is not None and b is not None and b > 0 else None


def quantile(values, p):
    values = sorted(v for v in values if number(v) is not None)
    if not values:
        return None
    position = (len(values) - 1) * p
    left = int(position)
    return values[left] + (values[min(left + 1, len(values) - 1)] - values[left]) * (position - left)


def distribution(values):
    values = [v for v in values if number(v) is not None]
    return {
        "n": len(values),
        "p5": quantile(values, 0.05),
        "p50": quantile(values, 0.5),
        "p95": quantile(values, 0.95),
    }


def observation(record):
    response = record["response"]
    attempts = record.get("attempts") or []
    timing = record.get("timing") or {}
    stream = dict(response.get("stream") or {})
    if stream.get("events"):
        stream.update(visible_metrics(stream["events"]))
    output = number((response.get("usage") or {}).get("output_tokens"))
    elapsed = number(response.get("elapsed"))
    if elapsed == 0 and not response.get("timing"):
        elapsed = None  # Legacy default zero was not an observed duration.
    total = number(timing.get("sample_seconds"))
    success = response.get("status") == "ok" and bool(response.get("text", "").strip())
    values = {
        "attempt_seconds": elapsed,
        "sample_seconds": total,
        "queue_wait_seconds": number(timing.get("queue_wait_seconds")),
        "output_tokens": output,
        "final_attempt_tps": divide(output, elapsed),
        "effective_tps": divide(output, total) if success else None,
        "first_visible_text_seconds": number(stream.get("first_visible_text_seconds")),
        "visible_text_receive_seconds": number(stream.get("visible_text_receive_seconds")),
    }
    reasons = {k: "not_recorded" for k, v in values.items() if v is None}
    if output is None:
        reasons["output_tokens"] = "usage_missing_or_invalid"
    if values["final_attempt_tps"] is None:
        reasons["final_attempt_tps"] = "output_usage_or_positive_duration_unavailable"
    if total is None:
        reasons["sample_seconds"] = "legacy_sample_monotonic_span_unavailable"
    if not success:
        reasons["effective_tps"] = "final_response_not_successful"
    for key in ("first_visible_text_seconds", "visible_text_receive_seconds"):
        if values[key] is None:
            reasons[key] = stream.get("reason") or "incremental_arrival_not_recorded"
    return {
        "schema_version": SCHEMA,
        **{key: record[key] for key in ("sample_id", "target", "case_id", "suite", "repeat")},
        "attempt": attempts[-1].get("attempt", len(attempts)) if attempts else None,
        "fragment_id": timing.get("fragment_id"),
        "timing": timing,
        "status": response.get("status"),
        "success": success,
        "retry_count": max(0, len(attempts) - 1) if attempts else None,
        "output_characters": len(response.get("text", "")),
        **values,
        "missing_reasons": reasons,
        "generation_tokens_per_second": None,
        "generation_rate_reason": "token_range_and_generation_time_boundaries_unavailable",
        "attempts": [
            {
                **{key: record[key] for key in ("sample_id", "target", "case_id", "repeat")},
                "attempt": a.get("attempt"),
                "status": a.get("status"),
                "seconds": number(a.get("elapsed")),
                "timing": a.get("timing"),
                "output_tokens": number((a.get("usage") or {}).get("output_tokens")),
                "tps": divide((a.get("usage") or {}).get("output_tokens"), a.get("elapsed")),
            }
            for a in attempts
        ],
    }


def summarize_rows(rows):
    successful = [r for r in rows if r["success"]]
    statuses = Counter(r["status"] for r in rows)
    attempt_statuses = Counter(a["status"] for r in rows for a in r["attempts"])
    known = sum(r["output_tokens"] is not None for r in successful)
    retry_known = [r for r in rows if r["retry_count"] is not None]
    return {
        "samples": len(rows),
        "successful_samples": len(successful),
        "success_output_usage_known": known,
        "success_output_usage_coverage": divide(known, len(successful)),
        "success_metrics": {m: distribution(r[m] for r in successful) for m in METRICS},
        "statuses": dict(statuses),
        "attempt_statuses": dict(attempt_statuses),
        "failure_rate": divide(len(rows) - len(successful), len(rows)),
        "status_rates": {k: divide(v, len(rows)) for k, v in statuses.items()},
        "retry_rate": divide(sum(r["retry_count"] > 0 for r in retry_known), len(retry_known)),
        "retry_observation_coverage": divide(len(retry_known), len(rows)),
        "sample_ids": [r["sample_id"] for r in rows],
    }


class ExecutionFragment:
    """One launch, with attempt-level concurrency (retry waits consume no request slot)."""

    def __init__(self, directory, config, targets, clock=None, utc=None):
        self.clock, self.utc = clock or time.monotonic, utc or now
        self.origin = self.clock()
        self.lock = threading.Lock()
        self.path = Path(directory) / "segments" / (uuid.uuid4().hex + ".json")
        self.data = {
            "schema_version": SCHEMA,
            "fragment_id": self.path.stem,
            "sequence": max((f.get("sequence", 0) for f in load_fragments(directory)), default=0) + 1,
            "created_at": self.utc(),
            "finished_at": None,
            "stop_reason": "running",
            "events": [],
            "concurrency": config["concurrency"],
            "target_concurrency": {
                n: min(config["concurrency"], config["targets"][n].get("concurrency", config["concurrency"]))
                for n in targets
            },
            "retries": config["retries"],
            "timeout": config["timeout"],
        }
        self.queue = {}
        self.dispatched = {}
        self.persist()

    def persist(self):
        write_json(self.path, self.data)

    def enqueue(self, tasks):
        for task in tasks:
            self.queue[task[3]] = {"monotonic": self.clock(), "utc": self.utc()}

    def dispatch(self, task):
        case, target, repeat, sid = task
        at = self.clock()
        queued = self.queue[sid]
        self.dispatched[sid] = {
            "fragment_id": self.path.stem,
            "queued_at": queued["utc"],
            "dispatched_at": self.utc(),
            "queue_wait_seconds": at - queued["monotonic"],
        }
        self.event(
            "sample_dispatched",
            {"sample_id": sid, "target": target, "case_id": case.id, "repeat": repeat},
            at,
        )

    def event(self, kind, identity, at=None, utc_at=None):
        with self.lock:
            self.data["events"].append(
                {
                    **identity,
                    "type": kind,
                    "offset_seconds": (self.clock() if at is None else at) - self.origin,
                    "at": utc_at or self.utc(),
                    "index": len(self.data["events"]),
                }
            )
            self.persist()

    def finish(self, reason):
        self.data.update(finished_at=self.utc(), stop_reason=reason)
        self.persist()


def fragment_metrics(fragment, rows):
    events = sorted(fragment.get("events", []), key=lambda e: (e["offset_seconds"], e["index"]))
    dispatches = [e["offset_seconds"] for e in events if e["type"] == "sample_dispatched"]
    endings = [e["offset_seconds"] for e in events if e["type"] == "attempt_finished"]
    finished = fragment.get("finished_at") is not None
    start = min(dispatches) if dispatches else None
    end = max(endings) if endings else None
    duration = end - start if finished and start is not None and end is not None and end >= start else None
    active, peak, area = 0, 0, 0.0
    previous = start
    curve = []
    for event in events:
        if event["type"] not in ("attempt_started", "attempt_finished"):
            continue
        at = event["offset_seconds"]
        if previous is not None:
            area += active * max(0, at - previous)
        active += 1 if event["type"] == "attempt_started" else -1
        peak = max(peak, active)
        previous = at
        curve.append({**event, "inflight_attempts": active})
    successful = [r for r in rows if r["fragment_id"] == fragment["fragment_id"] and r["success"]]
    if active != 0:
        duration = None
    observed_samples = {r["sample_id"] for r in rows if r["fragment_id"] == fragment["fragment_id"]}
    unresolved = sorted(
        {e["sample_id"] for e in events if e["type"] == "sample_dispatched"} - observed_samples
    )
    known = [r["output_tokens"] for r in successful if r["output_tokens"] is not None]
    complete_usage = len(known) == len(successful) and not unresolved
    return {
        **{
            k: fragment.get(k)
            for k in (
                "fragment_id",
                "created_at",
                "finished_at",
                "stop_reason",
                "concurrency",
                "target_concurrency",
                "retries",
                "timeout",
            )
        },
        "duration_seconds": duration,
        "first_dispatched_at": next((e["at"] for e in events if e["type"] == "sample_dispatched"), None),
        "last_attempt_finished_at": next(
            (e["at"] for e in reversed(events) if e["type"] == "attempt_finished"), None
        ),
        "first_dispatch_offset_seconds": start,
        "last_attempt_end_offset_seconds": end,
        "completed_attempts": len(endings),
        "unresolved_sample_ids": unresolved,
        "successful_samples": len(successful),
        "attempts_per_minute": divide(len(endings) * 60, duration),
        "successful_samples_per_minute": divide(len(successful) * 60, duration),
        "known_output_tokens": sum(known) if known or not successful else None,
        "output_usage_coverage": divide(len(known), len(successful)),
        "effective_output_tokens_per_second": divide(sum(known), duration) if complete_usage else None,
        "known_output_tokens_per_second": divide(sum(known), duration) if known or not successful else None,
        "throughput_scope": "complete" if complete_usage else "known_partial",
        "peak_inflight_attempts": peak if finished and dispatches else None,
        "average_inflight_attempts": divide(area, duration),
        "concurrency_events": curve,
        "missing_reason": None if duration is not None else "no_dispatch_or_unfinished_fragment",
    }


def analyze(records, fragments=()):
    rows = [observation(r) for r in records]
    suites, targets = defaultdict(list), defaultdict(list)
    for row in rows:
        suites[(row["target"], row["suite"])].append(row)
        targets[row["target"]].append(row)
    return {
        "schema_version": SCHEMA,
        "observations": rows,
        "targets": [{"target": k, **summarize_rows(v)} for k, v in targets.items()],
        "groups": [{"target": k[0], "suite": k[1], **summarize_rows(v)} for k, v in suites.items()],
        "fragments": [fragment_metrics(f, rows) for f in fragments],
    }


def load_fragments(directory):
    return sorted(
        [read_json(p) for p in (Path(directory) / "segments").glob("*.json")],
        key=lambda f: (f.get("sequence", 0), f.get("created_at", "")),
    )


def conditions(manifest, record):
    config = manifest["config"]
    target = config["targets"][record["target"]]
    return {
        "case_hash": record["case_hash"],
        "mode": record["mode"],
        "target": target,
        "identity": manifest.get("identities", {}).get(record["target"]),
        "actual_model": record["response"].get("actual_model"),
        "concurrency": config.get("concurrency"),
        "retries": config.get("retries"),
        "timeout": config.get("timeout"),
        "stream": target.get("stream", False),
        "output_limit": record["response"]
        .get("request", {})
        .get("output_limit", target.get("max_output_tokens", 8192)),
        "harness_version": manifest.get("version"),
        "harness_code_hash": manifest.get("code_hash"),
    }


def change(before, after):
    if number(before) is None or number(after) is None:
        return {"before": before, "after": after, "absolute": None, "percent": None}
    return {
        "before": before,
        "after": after,
        "absolute": after - before,
        "percent": (after - before) / before * 100 if before > 0 else None,
    }


def compare_performance(old_manifest, new_manifest, old, new):
    index = {(r["target"], r["case_id"], r["repeat"]): r for r in old}
    pairs = []
    groups = defaultdict(list)
    for record in new:
        prior = index.get((record["target"], record["case_id"], record["repeat"]))
        after = observation(record)
        before = observation(prior) if prior else None
        a = conditions(old_manifest, prior) if prior else {}
        b = conditions(new_manifest, record)
        different = [k for k in b if a.get(k) != b[k]] if prior else ["no_baseline"]
        compatible = prior is not None and not different
        success_pair = compatible and before["success"] and after["success"]
        row = {
            "sample_id": record["sample_id"],
            "baseline_sample_id": prior["sample_id"] if prior else None,
            **{k: record[k] for k in ("target", "case_id", "suite", "repeat")},
            "status": "matched" if compatible else "conditions_differ" if prior else "no_baseline",
            "different_conditions": different,
            "before": before,
            "after": after,
            "changes": {m: change(before[m], after[m]) for m in METRICS} if success_pair else {},
            "interpretation": "descriptive_only_not_capability",
        }
        pairs.append(row)
        groups[(record["target"], record["suite"])].append(row)
    summaries = []
    for (target, suite), items in groups.items():
        matched = [p for p in items if p["status"] == "matched"]
        successful = [p for p in matched if p["before"]["success"] and p["after"]["success"]]
        metrics = {}
        for metric in METRICS:
            valid = [
                p
                for p in successful
                if number(p["before"][metric]) is not None and number(p["after"][metric]) is not None
            ]
            metrics[metric] = {
                "n": len(valid),
                "p50_change": change(
                    quantile([p["before"][metric] for p in valid], 0.5),
                    quantile([p["after"][metric] for p in valid], 0.5),
                ),
            }
        summaries.append(
            {
                "target": target,
                "suite": suite,
                "matched_samples": len(matched),
                "conditions_differ": sum(p["status"] == "conditions_differ" for p in items),
                "metrics": metrics,
                "failure_rate_change": change(
                    divide(sum(not p["before"]["success"] for p in matched), len(matched)),
                    divide(sum(not p["after"]["success"] for p in matched), len(matched)),
                ),
                "output_characters_p50_change": change(
                    quantile([p["before"]["output_characters"] for p in successful], 0.5),
                    quantile([p["after"]["output_characters"] for p in successful], 0.5),
                ),
                "evidence": "small_sample_descriptive"
                if len({p["case_id"] for p in successful}) < 30
                else "descriptive",
                "before_all": summarize_rows([p["before"] for p in items if p["before"] is not None]),
                "after_all": summarize_rows([p["after"] for p in items]),
            }
        )
    current_keys = {(r["target"], r["case_id"], r["repeat"]) for r in new}
    return {
        "pairs": pairs,
        "groups": summaries,
        "coverage": {
            "baseline_planned": old_manifest.get("plan", {}).get("invocations"),
            "current_planned": new_manifest.get("plan", {}).get("invocations"),
            "baseline_completed": len(old),
            "current_completed": len(new),
            "without_current_record": [
                {k: r[k] for k in ("sample_id", "target", "case_id", "repeat")}
                for key, r in index.items()
                if key not in current_keys
            ],
            "baseline_all": summarize_rows([observation(r) for r in old]),
            "current_all": summarize_rows([observation(r) for r in new]),
        },
    }


def derive(directory, output):
    from .performance_report import render_performance
    from .report import page
    from .runner import latest_records, read_records

    directory, output = Path(directory).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("性能派生分析输出目录必须不存在；不会覆盖原始记录")
    manifest = read_json(directory / "manifest.json")
    records = latest_records(read_records(directory))
    fragments = load_fragments(directory)
    result = analyze(records, fragments)
    result["derived_from"] = {
        "path": str(directory),
        "run_id": manifest["run_id"],
        "created_at": now(),
        "operation": "offline-performance-analysis",
        "manifest_hash": digest(manifest),
        "results_hash": digest((directory / "results.jsonl").read_text()),
        "fragments_hash": digest(fragments),
    }
    output.mkdir(parents=True)
    write_json(output / "performance.json", result)
    (output / "report.html").write_text(page("性能派生分析", render_performance(result)), encoding="utf-8")
    return result
