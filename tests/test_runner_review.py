import copy
import json
from pathlib import Path

import pytest

from dummy_llm_test import runner
from dummy_llm_test.config import load_config
from dummy_llm_test.core import Response, read_json, scrub, write_json
from dummy_llm_test.report import compare, export_review, import_review


@pytest.fixture
def setup_run(tmp_path, monkeypatch):
    config = load_config(Path("config.yaml"))
    config.update(output_dir=str(tmp_path / "runs"), concurrency=2, retries=0)
    config["targets"]["fixture"] = {
        "kind": "responses",
        "model": "fixture",
        "base_url": "https://fixture.invalid/v1",
    }
    monkeypatch.setattr(runner, "preflight", lambda *a: {"fixture": {"version": "fixture-v1"}})
    calls = []

    def call(case, target, timeout):
        calls.append(case.id)
        text = {
            "candy.original": "Final Answer: 21",
            "svg.pelican-original": '<svg><circle r="4"/></svg>',
            "diagnostic.cutoff-zh": "我的知识截止日期是 2025年1月。",
            "basic.decimal": "9.9",
            "basic.strawberry": "3",
        }.get(case.id, "hello")
        return Response(text=text, usage={"input_tokens": 10, "output_tokens": 10}, actual_model="fixture")

    monkeypatch.setattr(runner, "call_api", call)
    return config, calls


def test_run_resume_and_report(setup_run):
    config, calls = setup_run
    directory, summary, _ = runner.run(config, "quick", ["fixture"], "controlled", progress=lambda x: None)
    assert summary["completed"] == 5 and len(calls) == 5
    assert len(runner.read_records(directory)) == 5
    assert (directory / "report.html").exists()
    assert summary["manual"][0]["reviewed"] == 0
    runner.run(config, "quick", ["fixture"], "controlled", resume=directory, progress=lambda x: None)
    assert len(calls) == 5
    # Simulate an interrupted run with two result records already durable.
    path = directory / "results.jsonl"
    path.write_text("\n".join(path.read_text().splitlines()[:2]) + "\n")
    runner.run(config, "quick", ["fixture"], "controlled", resume=directory, progress=lambda x: None)
    assert len(calls) == 8 and len(runner.read_records(directory)) == 5
    changed = copy.deepcopy(config)
    changed["seed"] = 99
    with pytest.raises(ValueError, match="续跑"):
        runner.run(changed, "quick", ["fixture"], "controlled", resume=directory, progress=lambda x: None)


def test_review_roundtrip_and_no_identity(setup_run, tmp_path):
    config, _ = setup_run
    directory, _, _ = runner.run(config, "quick", ["fixture"], "controlled", progress=lambda x: None)
    out = tmp_path / "review"
    assert export_review(directory, out) == 1
    package = read_json(out / "review.json")
    assert "target" not in package["items"][0]
    assert "fixture" not in (out / "index.html").read_text()
    package["reviewer"] = "reviewer-a"
    package["items"][0]["scores"] = {"subject": 1, "vehicle": 0, "riding": 0, "overall": 1}
    write_json(out / "scores.json", package)
    assert import_review(directory, out / "scores.json") == 1
    summary = read_json(directory / "summary.json")
    assert summary["manual"][0]["reviewed"] == 1
    svg_group = next(g for g in summary["groups"] if g["suite"] == "svg")
    assert svg_group["graded"] == 0
    package["items"][0]["scores"]["subject"] = 3
    write_json(out / "scores.json", package)
    with pytest.raises(ValueError, match="分值"):
        import_review(directory, out / "scores.json")


def test_incompatible_baseline_has_no_regression(setup_run, tmp_path):
    config, _ = setup_run
    old, _, _ = runner.run(config, "quick", ["fixture"], "controlled", progress=lambda x: None)
    new, _, _ = runner.run(config, "quick", ["fixture"], "controlled", progress=lambda x: None)
    result = compare(old, new, tmp_path / "compare.json")
    assert all(p["status"] == "matched" for p in result["pairs"])
    assert sum(p["delta"] or 0 for p in result["pairs"]) == 0
    records = runner.read_records(new)
    records[0]["target_signature"] = "different"
    (new / "results.jsonl").write_text("\n".join(map(json.dumps, records)) + "\n")
    result = compare(old, new, tmp_path / "compare.json")
    assert result["pairs"][0]["status"] == "incompatible" and result["pairs"][0]["delta"] is None


def test_retry_only_transport_failure(setup_run, monkeypatch):
    config, _ = setup_run
    config["levels"]["one"] = {"cases": ["basic.decimal"]}
    config["retries"] = 1
    responses = iter([Response(status="rate_limit"), Response(text="0")])
    monkeypatch.setattr(runner, "call_api", lambda *a: next(responses))
    monkeypatch.setattr(runner.time, "sleep", lambda n: None)
    directory, summary, _ = runner.run(config, "one", ["fixture"], "controlled", progress=lambda x: None)
    record = runner.read_records(directory)[0]
    assert len(record["attempts"]) == 2 and record["grade"]["score"] == 0
    assert summary["completed"] == 1


def test_budget_stops_before_dispatch(setup_run):
    config, calls = setup_run
    config["cost_limit_usd"] = 0.0000001
    config["targets"]["fixture"].update(input_price_per_million=10, output_price_per_million=10)
    _, summary, stopped = runner.run(config, "quick", ["fixture"], "controlled", progress=lambda x: None)
    assert stopped and not calls and summary["completed"] == 0


def test_scrub_credentials_recursively():
    result = scrub(
        {"api_key_env": "MY_KEY", "authorization": "Bearer xyz", "raw": ["leaked supersecret"]},
        ["supersecret"],
    )
    assert result["api_key_env"] == "MY_KEY"
    assert result["authorization"] == "[REDACTED]"
    assert "supersecret" not in json.dumps(result)


def test_all_suites_execute_offline_without_dropping_samples(setup_run):
    config, calls = setup_run
    config["concurrency"] = 8
    directory, summary, _ = runner.run(config, "full", ["fixture"], "controlled", progress=lambda x: None)
    assert len(calls) == len(set(calls)) == 189
    assert summary["execution_complete"] and summary["completed"] == 189
    assert summary["fingerprints"][0]["used_outputs"] == 0
    assert summary["fingerprints"][0]["status"] == "incomplete"
    assert len(read_json(directory / "challenges.json")["challenges"]) == 3


def test_recover_partial_last_result(setup_run):
    config, calls = setup_run
    directory, _, _ = runner.run(config, "quick", ["fixture"], "controlled", progress=lambda x: None)
    path = directory / "results.jsonl"
    complete = path.read_text().splitlines()
    path.write_text("\n".join(complete[:4]) + '\n{"sample_id":')
    assert len(runner.read_records(directory)) == 4
    runner.run(config, "quick", ["fixture"], "controlled", resume=directory, progress=lambda x: None)
    assert len(calls) == 6 and len(runner.read_records(directory)) == 5


def test_regrade_preserves_source_and_makes_no_calls(setup_run, tmp_path):
    from dummy_llm_test.report import regrade

    config, calls = setup_run
    source, _, _ = runner.run(config, "quick", ["fixture"], "controlled", progress=lambda x: None)
    before = (source / "results.jsonl").read_bytes()
    output = tmp_path / "derived"
    summary = regrade(source, output)
    assert summary["completed"] == 5 and len(calls) == 5
    assert (source / "results.jsonl").read_bytes() == before
    assert read_json(output / "manifest.json")["derived_from"]["operation"] == "offline-regrade"
    assert all("original_grade" in r for r in runner.read_records(output))
    with pytest.raises(ValueError, match="覆盖"):
        regrade(source, output)


def test_interrupted_run_saves_responses_and_resumes_only_missing(setup_run):
    from dummy_llm_test.scheduler import RunControl, RunInterrupted

    config, calls = setup_run
    config["concurrency"] = 1
    control = RunControl()

    def progress(message):
        if "score=" in message:
            control.stop()

    with pytest.raises(RunInterrupted) as exc:
        runner.run(config, "quick", ["fixture"], "controlled", progress=progress, control=control)
    directory = Path(str(exc.value))
    assert len(calls) == len(runner.read_records(directory)) == 1
    summary = read_json(directory / "summary.json")
    assert summary["scheduler"]["state"] == "interrupted"
    assert "用户中断" in (directory / "report.html").read_text()
    _, summary, stopped = runner.run(
        config,
        "quick",
        ["fixture"],
        "controlled",
        resume=directory,
        progress=lambda _: None,
    )
    assert not stopped and summary["execution_complete"]
    assert len(calls) == len(set(calls)) == 5


def test_budget_reserves_per_request_and_never_overshoots(setup_run):
    config, calls = setup_run
    config["targets"]["fixture"].update(input_price_per_million=1, output_price_per_million=1)
    _, cases = runner.plan_run(config, "quick", ["fixture"], "controlled")
    first_two = sum(runner.cost_reservation(c, config["targets"]["fixture"], 0) for c in cases[:2])
    config["cost_limit_usd"] = first_two + 0.00000001
    directory, summary, stopped = runner.run(
        config, "quick", ["fixture"], "controlled", progress=lambda _: None
    )
    assert stopped and len(calls) == summary["completed"] == 2
    assert summary["budget"]["reserved_usd"] <= config["cost_limit_usd"]
    assert read_json(directory / "manifest.json")["scheduler"]["state"] == "budget_exhausted"


def test_interrupt_suppresses_transport_retry(setup_run, monkeypatch):
    from dummy_llm_test.scheduler import RunControl, RunInterrupted

    config, _ = setup_run
    config.update(concurrency=1, retries=3)
    control = RunControl()
    calls = []

    def call(*_):
        calls.append(1)
        control.stop()
        return Response(status="rate_limit")

    monkeypatch.setattr(runner, "call_api", call)
    with pytest.raises(RunInterrupted) as exc:
        runner.run(config, "quick", ["fixture"], "controlled", progress=lambda _: None, control=control)
    records = runner.read_records(Path(str(exc.value)))
    assert len(calls) == len(records[0]["attempts"]) == 1
    assert records[0]["response"]["status"] == "rate_limit"


def test_resume_does_not_spend_more_after_unknown_usage(setup_run, monkeypatch):
    config, calls = setup_run
    config.update(concurrency=1, cost_limit_usd=100)
    config["targets"]["fixture"].update(input_price_per_million=1, output_price_per_million=1)

    def call(case, *_):
        calls.append(case.id)
        return Response(text="21")

    monkeypatch.setattr(runner, "call_api", call)
    directory, summary, stopped = runner.run(
        config, "quick", ["fixture"], "controlled", progress=lambda _: None
    )
    assert stopped and summary["scheduler"]["state"] == "usage_unknown"
    runner.run(config, "quick", ["fixture"], "controlled", resume=directory, progress=lambda _: None)
    assert len(calls) == 1
