import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from dummy_llm_test import performance as perf
from dummy_llm_test import runner
from dummy_llm_test.core import Case, Response, write_json


class Clock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds

    def utc(self):
        # Deliberately unsuitable for duration subtraction (clock adjustment).
        return f"2026-09-15T00:00:{59 - int(self.value) % 60:02d}+00:00"


def record(sid="a", status="ok", output=30, elapsed=3, total=6):
    response = Response(text="21", status=status, elapsed=elapsed, usage={"output_tokens": output})
    return {
        "sample_id": sid,
        "target": "fixture",
        "case_id": sid,
        "suite": "basic",
        "repeat": 0,
        "case_hash": "fixed-prompt",
        "mode": "controlled",
        "response": asdict(response),
        "timing": {"sample_seconds": total, "queue_wait_seconds": 1},
        "attempts": [{"attempt": 1, **asdict(response)}],
    }


def test_retry_clock_includes_wait_and_failed_attempt(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep))
    monkeypatch.setattr(runner, "now", clock.utc)
    responses = iter(
        [(2, Response(status="rate_limit")), (3, Response(text="21", usage={"output_tokens": 30}))]
    )

    def call(*_):
        seconds, response = next(responses)
        clock.sleep(seconds)
        return response

    monkeypatch.setattr(runner, "call_api", call)
    events = []
    result = runner.execute_sample(
        Case("candy", "candy", "prompt", expected="21"),
        "fixture",
        {"kind": "responses"},
        "controlled",
        {"timeout": 20, "retries": 1},
        {},
        "sample-a",
        2,
        "sig",
        events.append,
    )
    row = perf.observation(result)
    assert row["attempt_seconds"] == 3 and row["sample_seconds"] == 6
    assert row["final_attempt_tps"] == 10 and row["effective_tps"] == 5
    assert result["timing"]["retry_waits"][0]["seconds"] == 1
    assert [a["elapsed"] for a in result["attempts"]] == [2, 3]
    assert all(
        e["sample_id"] == "sample-a"
        and e["repeat"] == 2
        and e["target"] == "fixture"
        and e["case_id"] == "candy"
        and "attempt" in e
        for e in events
    )


def test_interrupted_backoff_is_in_sample_duration(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=clock.monotonic))

    def call(*_):
        clock.sleep(2)
        return Response(status="server_error")

    def wait(_):
        clock.sleep(0.5)
        return True

    monkeypatch.setattr(runner, "call_api", call)
    result = runner.execute_sample(
        Case("a", "b", "prompt"),
        "t",
        {"kind": "responses"},
        "controlled",
        {"timeout": 20, "retries": 1},
        {},
        "a",
        0,
        "s",
        lambda _: None,
        SimpleNamespace(wait=wait),
    )
    assert result["timing"]["sample_seconds"] == 2.5
    assert result["timing"]["retry_waits"][0]["interrupted"]
    assert len(result["attempts"]) == 1


def test_segments_measure_overlap_not_sum_of_tps_or_offline_gap(tmp_path):
    clock = Clock()
    config = {"concurrency": 2, "retries": 0, "timeout": 5, "targets": {"fixture": {}}}
    fragment = perf.ExecutionFragment(tmp_path, config, ["fixture"], clock.monotonic, clock.utc)
    tasks = [(Case(s, "basic", "q"), "fixture", 0, s) for s in ("a", "b")]
    fragment.enqueue(tasks)
    clock.value = 1
    fragment.dispatch(tasks[0])
    fragment.event("attempt_started", {"sample_id": "a", "attempt": 1})
    clock.value = 2
    fragment.dispatch(tasks[1])
    fragment.event("attempt_started", {"sample_id": "b", "attempt": 1})
    clock.value = 4
    fragment.event("attempt_finished", {"sample_id": "a", "attempt": 1})
    clock.value = 5
    fragment.event("attempt_finished", {"sample_id": "b", "attempt": 1})
    clock.value = 100
    fragment.finish("interrupted")
    rows = [perf.observation(record()), perf.observation(record("b", output=None))]
    for row in rows:
        row["fragment_id"] = fragment.path.stem
    values = perf.fragment_metrics(fragment.data, rows)
    assert values["duration_seconds"] == 4
    assert values["average_inflight_attempts"] == 1.5 and values["peak_inflight_attempts"] == 2
    assert values["attempts_per_minute"] == values["successful_samples_per_minute"] == 30
    assert values["effective_output_tokens_per_second"] is None
    assert values["known_output_tokens_per_second"] == 7.5 and values["output_usage_coverage"] == 0.5
    assert fragment.dispatched["b"]["queue_wait_seconds"] == 2
    # A second launch records its own origin and cannot include the preceding offline gap.
    clock.value = 10000
    second = perf.ExecutionFragment(tmp_path, config, ["fixture"], clock.monotonic, clock.utc)
    second.enqueue(tasks[:1])
    second.dispatch(tasks[0])
    second.event("attempt_started", {})
    clock.value += 2
    second.event("attempt_finished", {})
    second.finish("complete")
    assert perf.fragment_metrics(second.data, [])["duration_seconds"] == 2
    assert len(perf.load_fragments(tmp_path)) == 2


def test_failure_missing_usage_and_percentiles_are_separate():
    records = [record("ok"), record("missing", output=None), record("timeout", "timeout", elapsed=100)]
    result = perf.analyze(records)
    group = result["groups"][0]
    assert group["successful_samples"] == 2
    assert group["success_output_usage_coverage"] == 0.5
    assert group["success_metrics"]["final_attempt_tps"]["n"] == 1
    assert group["success_metrics"]["attempt_seconds"]["p95"] == 3
    assert group["failure_rate"] == pytest.approx(1 / 3)
    assert result["observations"][2]["effective_tps"] is None
    assert perf.distribution([1, 2, 10])["p5"] < perf.distribution([1, 2, 10])["p95"]


def manifest():
    return {
        "version": "0.3.0",
        "config": {
            "concurrency": 2,
            "timeout": 10,
            "retries": 1,
            "targets": {
                "fixture": {"kind": "responses", "model": "fixed", "stream": False, "max_output_tokens": 100}
            },
        },
    }


@pytest.mark.parametrize(
    "key,value",
    [("concurrency", 4), ("timeout", 30), ("retries", 2), ("stream", True), ("max_output_tokens", 200)],
)
def test_performance_conditions_block_misleading_comparison(key, value):
    before, after = manifest(), manifest()
    dest = (
        after["config"]
        if key in ("concurrency", "timeout", "retries")
        else after["config"]["targets"]["fixture"]
    )
    dest[key] = value
    result = perf.compare_performance(before, after, [record()], [record(elapsed=1)])
    pair = result["pairs"][0]
    assert pair["status"] == "conditions_differ" and not pair["changes"]
    assert pair["before"]["attempt_seconds"] == 3 and pair["after"]["attempt_seconds"] == 1


def test_matched_comparison_tracks_length_and_failure_rate():
    result = perf.compare_performance(
        manifest(),
        manifest(),
        [record(), record("b")],
        [record(elapsed=1, total=2, output=10), record("b", "timeout")],
    )
    assert result["pairs"][0]["changes"]["sample_seconds"]["absolute"] == -4
    assert result["pairs"][0]["changes"]["output_tokens"]["percent"] == pytest.approx(-200 / 3)
    assert result["groups"][0]["failure_rate_change"]["absolute"] == 0.5
    assert not result["pairs"][1]["changes"]
    assert perf.change(0, 1)["percent"] is None


def test_legacy_derivation_never_changes_source_or_fabricates_timings(tmp_path):
    source, output = tmp_path / "source", tmp_path / "analysis"
    source.mkdir()
    old = record()
    old.pop("timing")
    old["response"].pop("stream")
    write_json(source / "manifest.json", {"run_id": "legacy"})
    (source / "results.jsonl").write_text(json.dumps(old) + "\n")
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    result = perf.derive(source, output)
    row = result["observations"][0]
    assert row["final_attempt_tps"] == 10
    assert row["sample_seconds"] is row["first_visible_text_seconds"] is row["queue_wait_seconds"] is None
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before
    assert (output / "report.html").exists()
    with pytest.raises(ValueError, match="覆盖"):
        perf.derive(source, output)


def test_html_escapes_labels_and_distinguishes_missing_from_zero():
    from dummy_llm_test.performance_report import render_performance, render_sample

    malicious = record("<script>alert(1)</script>", output=None)
    malicious["target"] = '<img src=x onerror="alert(2)">'
    result = render_performance(perf.analyze([malicious])) + render_sample(malicious)
    assert "<script>alert(1)</script>" not in result and "<img src=x" not in result
    assert "&lt;img" in result and "未提供／不支持" in result
    assert perf.observation(record(output=0))["final_attempt_tps"] == 0


def test_comparison_html_keeps_changed_conditions_and_failure_context_visible():
    from dummy_llm_test.performance_report import render_comparison

    before, after = manifest(), manifest()
    after["config"]["concurrency"] = 8
    compared = perf.compare_performance(before, after, [record()], [record(status="timeout")])
    report = render_comparison(compared)
    assert "conditions_differ" in report and "timeout" in report and "故障率" in report
    assert compared["groups"][0]["before_all"]["failure_rate"] == 0
    assert compared["groups"][0]["after_all"]["failure_rate"] == 1


def test_stream_boundaries_recomputed_from_evidence_without_mutating_record():
    row = record()
    row["response"]["stream"] = {
        "events": [
            {"type": "response.created", "offset_seconds": 1, "data": {}},
            {"type": "response.output_text.delta", "offset_seconds": 2, "data": {"delta": "a"}},
            {"type": "response.output_text.delta", "offset_seconds": 5, "data": {"delta": "b"}},
        ]
    }
    observed = perf.observation(row)
    assert observed["first_visible_text_seconds"] == 2 and observed["visible_text_receive_seconds"] == 3
    assert "first_visible_text_seconds" not in row["response"]["stream"]


def test_missing_current_samples_are_exposed_not_silently_dropped():
    from dummy_llm_test.performance_report import render_comparison

    result = perf.compare_performance(manifest(), manifest(), [record(), record("slow")], [record()])
    assert result["coverage"]["baseline_completed"] == 2 and result["coverage"]["current_completed"] == 1
    assert result["coverage"]["without_current_record"][0]["case_id"] == "slow"
    assert "未产生当前记录" in render_comparison(result)
