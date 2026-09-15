from __future__ import annotations

import fcntl
import json
import math
import os
import time
import uuid
from collections import Counter, defaultdict, deque
from dataclasses import asdict
from pathlib import Path

from . import __version__, performance
from .adapters import api_payload, call_api, call_cli, cli_preflight, codex_connection
from .catalog import select
from .config import secret_values
from .core import PACKAGE, Case, Response, digest, grading_hash, now, read_json, scrub, wilson, write_json
from .fingerprint import analyze, load_bank
from .scheduler import RunControl, RunInterrupted, dispatch
from .scoring import score


def plan_run(config, level, targets, mode):
    cases = select(config, level)
    repetitions = config["levels"][level].get("repetitions", config["repetitions"])
    if not isinstance(repetitions, int) or repetitions < 1:
        raise ValueError("重复次数必须为正整数")
    for name in targets:
        if name not in config["targets"]:
            raise ValueError(f"未知目标: {name}")
    if len(set(targets)) != len(targets):
        raise ValueError("目标不可重复")
    return {
        "level": level,
        "mode": mode,
        "targets": targets,
        "repetitions": repetitions,
        "cases_per_target": len(cases),
        "invocations": len(cases) * len(targets) * repetitions,
        "concurrency": config["concurrency"],
        "target_concurrency": {
            name: min(
                config["concurrency"], config["targets"][name].get("concurrency", config["concurrency"])
            )
            for name in targets
        },
        "suites": dict(Counter(c.suite for c in cases)),
        "case_ids": [c.id for c in cases],
        "note": "CLI 日常模式内部可能多次调用模型；这里统计评测调用数",
    }, cases


def preflight(config, targets, mode):
    identities = {}
    for name in targets:
        target = config["targets"][name]
        if target["kind"] in ("codex", "claude"):
            identities[name] = cli_preflight(target, mode)
            if target["kind"] == "codex" and mode == "controlled":
                model, overrides = codex_connection(target)
                identities[name]["resolved_model"] = model
                identities[name]["connection_overrides"] = overrides
            if mode == "native":
                paths = (
                    [Path.home() / ".codex/config.toml", Path.home() / ".codex/AGENTS.md"]
                    if target["kind"] == "codex"
                    else [Path.home() / ".claude/settings.json", Path.home() / ".claude/CLAUDE.md"]
                )
                identities[name]["local_config_hashes"] = {
                    p.name: digest(p.read_text()) for p in paths if p.exists()
                }
        else:
            if not target.get("model") or target["model"] == "SET_MODEL":
                raise ValueError(f"请为目标 {name} 设置真实 model")
            if not target.get("base_url"):
                raise ValueError(f"请为目标 {name} 设置 base_url")
            key_env = target.get("api_key_env")
            if key_env and not os.environ.get(key_env):
                raise ValueError(f"目标 {name} 缺少环境变量 {key_env}")
            api_payload(Case("preflight", "preflight", ""), target)
            identities[name] = {
                "protocol": target["kind"],
                "model": target["model"],
                "base_url": target["base_url"],
            }
    return identities


def cost_reservation(case, target, retries):
    # Deliberately conservative byte upper bound, plus protocol overhead; API only.
    body = api_payload(case, target)[1]
    input_bound = len(json.dumps(body, ensure_ascii=False).encode()) + 1024
    output_bound = target.get("max_output_tokens", 8192)
    return (
        (input_bound * target["input_price_per_million"] + output_bound * target["output_price_per_million"])
        / 1e6
        * (retries + 1)
    )


def validate_budget(config, targets):
    limit = config.get("cost_limit_usd")
    if limit is None:
        return
    if not isinstance(limit, (int, float)) or not math.isfinite(limit) or limit <= 0:
        raise ValueError("cost_limit_usd 必须为正数")
    for name in targets:
        target = config["targets"][name]
        if target["kind"] not in ("chat_completions", "responses"):
            raise ValueError("费用上限仅支持 API；CLI 无法保证计费上限")
        if any(k not in target for k in ("input_price_per_million", "output_price_per_million")):
            raise ValueError("费用上限需要配置输入和输出每百万 token 价格")


def measured_cost(response, target):
    u = response.usage
    if all(target.get(k) is not None for k in ("input_price_per_million", "output_price_per_million")):
        if all(isinstance(u.get(k), (int, float)) for k in ("input_tokens", "output_tokens")):
            return (
                u["input_tokens"] * target["input_price_per_million"]
                + u["output_tokens"] * target["output_price_per_million"]
            ) / 1e6
    return None


def read_records(directory):
    path = Path(directory) / "results.jsonl"
    if not path.exists():
        return []
    records = []
    content = path.read_text()
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                if index != len(lines) - 1 or content.endswith("\n"):
                    raise ValueError("results.jsonl 中间出现损坏记录，不能自动续跑") from None
                # A process can die during its last append. Earlier complete records remain usable.
    return records


def latest_records(records):
    return list({r["sample_id"]: r for r in records}.values())


def execute_sample(
    case,
    name,
    target,
    mode,
    config,
    identity,
    sample_id,
    repeat,
    signature,
    log_attempt,
    stop_event=None,
    fragment=None,
):
    attempts = []
    retry_waits = []
    sample_started = time.monotonic()
    sample_started_at = now()
    for attempt in range(config["retries"] + 1):
        attempt_identity = {
            "sample_id": sample_id,
            "target": name,
            "case_id": case.id,
            "repeat": repeat,
            "attempt": attempt + 1,
            "fragment_id": fragment.path.stem if fragment else None,
        }
        log_attempt({**attempt_identity, "event": "started", "time": now()})
        attempt_started_at = now()
        attempt_started = time.monotonic()
        if fragment:
            fragment.event("attempt_started", attempt_identity, attempt_started, attempt_started_at)
        try:
            response = (
                call_cli(case, target, mode, config["timeout"], identity)
                if target["kind"] in ("codex", "claude")
                else call_api(case, target, config["timeout"])
            )
        except Exception as exc:
            response = Response(status="harness_error", error=f"{type(exc).__name__}: {exc}")
        attempt_finished = time.monotonic()
        attempt_finished_at = now()
        response.elapsed = attempt_finished - attempt_started
        response.timing = {
            "started_at": attempt_started_at,
            "finished_at": attempt_finished_at,
            "elapsed_seconds": response.elapsed,
        }
        if fragment:
            fragment.event("attempt_finished", attempt_identity, attempt_finished, attempt_finished_at)
        attempts.append({**attempt_identity, **asdict(response), "cost_usd": measured_cost(response, target)})
        log_attempt({"event": "finished", "time": now(), **attempts[-1]})
        if response.status not in ("rate_limit", "server_error") or attempt == config["retries"]:
            break
        wait_started, wait_utc = time.monotonic(), now()
        interrupted_wait = False
        if stop_event is not None:
            interrupted_wait = stop_event.wait(min(2**attempt, 8))
        else:
            time.sleep(min(2**attempt, 8))
        retry_waits.append(
            {
                **attempt_identity,
                "started_at": wait_utc,
                "finished_at": now(),
                "seconds": time.monotonic() - wait_started,
                "interrupted": interrupted_wait,
            }
        )
        if interrupted_wait:
            break
    sample_finished, sample_finished_at = time.monotonic(), now()
    return {
        "sample_id": sample_id,
        "case_id": case.id,
        "case_hash": case.hash,
        "suite": case.suite,
        "kind": case.kind,
        "target": name,
        "target_signature": signature,
        "mode": mode,
        "repeat": repeat,
        "timestamp": now(),
        "timing": {
            **(fragment.dispatched[sample_id] if fragment else {}),
            "sample_started_at": sample_started_at,
            "sample_finished_at": sample_finished_at,
            "sample_seconds": sample_finished - sample_started,
            "retry_waits": retry_waits,
        },
        "response": asdict(response),
        "grade": score(case, response),
        "grader_signature": grading_hash(),
        "attempts": attempts,
        "cost_usd": sum(a["cost_usd"] or 0 for a in attempts),
        "cost_known": all(a["cost_usd"] is not None for a in attempts),
    }


def summarize(directory):
    directory = Path(directory)
    manifest = read_json(directory / "manifest.json")
    records = latest_records(read_records(directory))
    groups = defaultdict(list)
    for row in records:
        groups[(row["target"], row["suite"])].append(row)
    summaries = []
    for (target, suite), rows in sorted(groups.items()):
        graded = [r for r in rows if r["grade"]["score"] is not None]
        correct = sum(r["grade"]["score"] for r in graded)
        # Repetitions of a case are correlated. CI uses only one observation per distinct case.
        first = {}
        for r in sorted(graded, key=lambda x: x["repeat"]):
            first.setdefault(r["case_id"], r)
        ci_rows = list(first.values())
        summaries.append(
            {
                "target": target,
                "suite": suite,
                "completed": len(rows),
                "graded": len(graded),
                "correct": correct,
                "accuracy": correct / len(graded) if graded else None,
                "first_repeat_ci95": wilson(sum(r["grade"]["score"] for r in ci_rows), len(ci_rows)),
                "distinct_cases": len(first),
                "evidence": "screening_only" if len(first) < 30 else "descriptive",
                "statuses": dict(Counter(r["response"]["status"] for r in rows)),
                "pending_review": sum(r["grade"]["status"] == "pending_review" for r in rows),
                "case_repeat_scores": {
                    c: [r["grade"]["score"] for r in graded if r["case_id"] == c] for c in first
                },
            }
        )
    bank_path = directory / "fingerprint_bank.json"
    fingerprints = []
    if bank_path.exists():
        bank = load_bank(bank_path)
        cases = {c["id"]: c for c in manifest["cases"]}
        for target in manifest["plan"]["targets"]:
            for rep in range(manifest["plan"]["repetitions"]):
                found = {
                    r["case_id"]: r
                    for r in records
                    if r["target"] == target and r["repeat"] == rep and r["kind"] == "fingerprint"
                }
                if not found:
                    continue
                outputs = []
                for cid in ("modeltrace.probe-1", "modeltrace.probe-2", "modeltrace.probe-3"):
                    r = found.get(cid)
                    outputs.append(
                        {
                            **(r["response"] if r else {"text": "", "status": "not_run"}),
                            "expected_count": cases[cid]["metadata"]["expected_count"],
                        }
                    )
                fingerprints.append({"target": target, "repeat": rep, **analyze(outputs, bank)})
    reviews = read_json(directory / "reviews.json") if (directory / "reviews.json").exists() else []
    reviewed = {r["sample_id"]: r for r in reviews}
    # Manual scores are always a separate section, including partially reviewed runs.
    manual = []
    for (target, suite), rows in sorted(groups.items()):
        pending = [r for r in rows if r["kind"] in ("svg", "manual") and r["response"]["status"] == "ok"]
        if pending:
            values = [reviewed[r["sample_id"]] for r in pending if r["sample_id"] in reviewed]
            manual.append(
                {
                    "target": target,
                    "suite": suite,
                    "eligible": len(pending),
                    "reviewed": len(values),
                    "scores": values,
                }
            )
    result = {
        "schema_version": 1,
        "run_id": manifest["run_id"],
        "planned": manifest["plan"]["invocations"],
        "completed": len(records),
        "execution_complete": len(records) == manifest["plan"]["invocations"],
        "groups": summaries,
        "fingerprints": fingerprints,
        "manual": manual,
        "cost_usd_known_part": sum(r["cost_usd"] for r in records),
        "cost_coverage": sum(r["cost_known"] for r in records),
        "budget": manifest.get("budget"),
        "scheduler": manifest.get("scheduler"),
        "performance": performance.analyze(records, performance.load_fragments(directory)),
        "notes": [
            "没有统一智商分；能力、人工评阅、指纹与运行故障分别呈现。",
            "Wilson 区间仅描述不同题的首轮表现，不把重复题当作独立题；不是模型退化的因果证明。",
        ],
    }
    write_json(directory / "summary.json", result)
    from .report import render_report

    render_report(directory, manifest, records, result)
    return result


def run(config, level, targets, mode, resume=None, progress=print, control=None):
    import threading

    plan, cases = plan_run(config, level, targets, mode)
    validate_budget(config, targets)
    identities = preflight(config, targets, mode)
    secrets = secret_values(config)
    code_hash = digest({str(p.relative_to(PACKAGE)): p.read_text() for p in sorted(PACKAGE.rglob("*.py"))})
    signature = {
        name: digest(
            {
                "target": config["targets"][name],
                "identity": identities[name],
                "mode": mode,
                "harness_version": __version__,
                "harness_code_hash": code_hash,
            }
        )
        for name in targets
    }
    resume_hash = digest(
        {
            "config": config,
            "plan": plan,
            "cases": [c.hash for c in cases],
            "identity": identities,
            "code_hash": code_hash,
        }
    )
    if resume:
        directory = Path(resume).resolve()
        manifest = read_json(directory / "manifest.json")
        if manifest["resume_hash"] != resume_hash:
            raise ValueError("续跑配置/题目/CLI 版本已变化；请使用原配置或开始新运行")
    else:
        run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
        directory = Path(config["output_dir"]).resolve() / run_id
        directory.mkdir(parents=True)
        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "created_at": now(),
            "version": __version__,
            "code_hash": code_hash,
            "resume_hash": resume_hash,
            "plan": plan,
            "config": scrub(config, secrets),
            "identities": scrub(identities, secrets),
            "cases": [c.to_dict() for c in cases],
            "budget": {"limit_usd": config.get("cost_limit_usd"), "reserved_usd": 0.0},
        }
        if any(c.kind == "fingerprint" for c in cases):
            write_json(directory / "fingerprint_bank.json", load_bank(config.get("bank")))
            write_json(
                directory / "challenges.json",
                {
                    "seed": config["seed"],
                    "challenges": [
                        {"id": c.id, "prompt": c.prompt, "expected_count": c.metadata["expected_count"]}
                        for c in cases
                        if c.kind == "fingerprint"
                    ],
                },
            )
        write_json(directory / "manifest.json", manifest)
        latest = directory.parent / "latest"
        if latest.is_symlink():
            latest.unlink()
        if not latest.exists():
            latest.symlink_to(directory.name, target_is_directory=True)
    run_lock = (directory / ".lock").open("w")
    try:
        fcntl.flock(run_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        run_lock.close()
        raise ValueError("此运行仍在执行，不能同时续跑") from None
    saved = read_records(directory)
    result_path = directory / "results.jsonl"
    if result_path.exists() and not result_path.read_text().endswith("\n"):
        result_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in saved))
    done = {r["sample_id"] for r in saved}
    queues = {name: deque() for name in targets}
    for name in targets:
        for rep in range(plan["repetitions"]):
            for case in cases:
                sid = digest([name, case.hash, rep])[:24]
                if sid not in done:
                    queues[name].append((case, name, rep, sid))
    fragment = performance.ExecutionFragment(directory, config, targets)
    fragment.enqueue(task for tasks in queues.values() for task in tasks)
    lock = threading.Lock()

    def log_attempt(event):
        with lock, (directory / "attempts.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(scrub(event, secrets), ensure_ascii=False) + "\n")
            f.flush()

    limit = config.get("cost_limit_usd")
    control = control or RunControl()
    if limit and any(not r["cost_known"] for r in latest_records(saved)):
        control.stop("usage_unknown")

    def reserve(task):
        if not limit:
            return None
        case, name, _, _ = task
        reservation = cost_reservation(case, config["targets"][name], config["retries"])
        if manifest["budget"]["reserved_usd"] + reservation > limit:
            return "budget_exhausted"
        manifest["budget"]["reserved_usd"] += reservation
        write_json(directory / "manifest.json", manifest)
        return None

    def execute(task):
        case, name, rep, sid = task
        return execute_sample(
            case,
            name,
            config["targets"][name],
            mode,
            config,
            identities[name],
            sid,
            rep,
            signature[name],
            log_attempt,
            control.event,
            fragment,
        )

    def save(record):
        record = scrub(record, secrets)
        with (directory / "results.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            f.flush()
        progress(
            f"{record['target']} · {record['case_id']} · {record['response']['status']} · score={record['grade']['score']}"
        )
        return "usage_unknown" if limit and not record["cost_known"] else None

    manifest["scheduler"] = {"state": "running", "started_at": now()}
    write_json(directory / "manifest.json", manifest)
    try:
        with control:
            dispatch(
                queues,
                config["concurrency"],
                plan["target_concurrency"],
                execute,
                reserve,
                save,
                control,
                progress,
                plan["invocations"],
                len(done),
                config["progress_interval"],
                on_dispatch=fragment.dispatch,
            )
    except BaseException:
        manifest["scheduler"]["state"] = "harness_error"
        raise
    else:
        manifest["scheduler"]["state"] = control.reason or "complete"
    finally:
        try:
            fragment.finish(manifest["scheduler"]["state"])
            manifest["scheduler"]["finished_at"] = now()
            write_json(directory / "manifest.json", manifest)
            summary = summarize(directory)
        finally:
            run_lock.close()
    progress(f"报告: {directory / 'report.html'}")
    if control.reason == "interrupted":
        progress(f"中断结果已保存。保持相同配置，用 run --resume {directory} 补齐未发起的题目。")
        raise RunInterrupted(str(directory))
    return directory, summary, control.reason is not None
