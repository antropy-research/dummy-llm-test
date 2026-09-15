"""Create a synthetic report for UI review. No network or model calls."""

import argparse
from dataclasses import asdict
from pathlib import Path

from dummy_llm_test.core import Response, write_json
from dummy_llm_test.performance import analyze, compare_performance
from dummy_llm_test.performance_report import render_comparison, render_performance, render_sample
from dummy_llm_test.report import page


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--shared", action="store_true", help="generate an anonymous synthetic share demo")
    args = parser.parse_args()
    output = args.output
    if output.exists():
        parser.error("output must not exist")
    rows, events = [], []
    for i, (duration, tokens, status) in enumerate(
        [
            (2, 120, "ok"),
            (6, 450, "ok"),
            (3, 150, "ok"),
            (12, 80, "ok"),
            (4, None, "ok"),
            (10, 20, "truncated"),
            (15, None, "timeout"),
            (1, 5, "refused"),
        ]
    ):
        sid = f"synthetic-{i}"
        response = Response(
            text="合成回答，仅用于报告示例",
            status=status,
            elapsed=duration,
            usage={"output_tokens": tokens},
            timing={"elapsed_seconds": duration},
        )
        rows.append(
            {
                "sample_id": sid,
                "target": "offline-fixture",
                "case_id": sid,
                "case_hash": sid,
                "mode": "controlled",
                "suite": "synthetic",
                "repeat": 0,
                "response": asdict(response),
                "attempts": [{"attempt": 1, **asdict(response)}],
                "timing": {
                    "sample_seconds": duration,
                    "queue_wait_seconds": i * 5,
                    "fragment_id": "synthetic-fragment",
                },
            }
        )
        for kind, at in (
            ("sample_dispatched", i * 5),
            ("attempt_started", i * 5),
            ("attempt_finished", i * 5 + duration),
        ):
            events.append(
                {
                    "type": kind,
                    "offset_seconds": at,
                    "at": f"2026-09-15T00:00:{at:02d}+00:00",
                    "index": len(events),
                    "sample_id": sid,
                    "target": "offline-fixture",
                    "case_id": sid,
                    "repeat": 0,
                    "attempt": 1,
                }
            )
    fragment = {
        "fragment_id": "synthetic-fragment",
        "created_at": "2026-09-15T00:00:00+00:00",
        "finished_at": "2026-09-15T00:00:46+00:00",
        "stop_reason": "complete",
        "events": events,
        "concurrency": 3,
        "target_concurrency": {"offline-fixture": 3},
        "retries": 0,
        "timeout": 15,
    }
    if args.shared:
        from dummy_llm_test.sharing import export_data, write_export

        for i, row in enumerate(rows):
            row["kind"] = "exact"
            row["grade"] = (
                {"status": "graded", "score": i % 2}
                if row["response"]["status"] == "ok"
                else {"status": row["response"]["status"], "score": None}
            )
        data = export_data(rows, [fragment])
        data["synthetic"] = True
        write_export(data, output)
        print((output / "index.html").resolve())
        return
    output.mkdir(parents=True)
    data = analyze(rows, [fragment])
    body = '<h1>性能报告示例</h1><p class="warning">完全离线合成数据，用于检查界面；不是真实模型成绩。</p>'
    body += render_performance(data)
    for row in rows:
        body += f"<details><summary>{row['sample_id']}</summary>{render_sample(row)}</details>"
    write_json(output / "performance.json", data)
    (output / "report.html").write_text(page("离线合成性能示例", body), encoding="utf-8")
    manifest = {
        "version": "synthetic",
        "config": {
            "targets": {"offline-fixture": {"kind": "responses"}},
            "concurrency": 3,
            "retries": 0,
            "timeout": 15,
        },
    }
    comparison = compare_performance(manifest, manifest, rows, rows)
    (output / "comparison.html").write_text(
        page("离线对照示例", "<h1>合成数据自比较</h1>" + render_comparison(comparison)), encoding="utf-8"
    )
    print((output / "report.html").resolve())


if __name__ == "__main__":
    main()
