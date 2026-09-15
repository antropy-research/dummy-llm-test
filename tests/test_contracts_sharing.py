import copy
import json
import shutil

import pytest
from click.testing import CliRunner

from dummy_llm_test import contracts, core, runner
from dummy_llm_test.cli import main
from dummy_llm_test.config import DEFAULT
from dummy_llm_test.core import Response, read_json
from dummy_llm_test.performance import conditions, load_fragments
from dummy_llm_test.report import compare
from dummy_llm_test.sharing import export_run


@pytest.fixture
def config(tmp_path, monkeypatch):
    config = copy.deepcopy(DEFAULT)
    config["output_dir"] = str(tmp_path / "runs")
    config["targets"]["fixture"] = {"kind": "responses", "model": "fixture"}
    monkeypatch.setattr(runner, "preflight", lambda *a: {"fixture": {"version": "fixture"}})
    monkeypatch.setattr(
        runner, "call_api", lambda *a: Response(text="3", elapsed=1, usage={"output_tokens": 5})
    )
    return config


def run(config, **kw):
    return runner.run(config, "quick", ["fixture"], "controlled", progress=lambda _: None, **kw)[0]


def test_signatures_ignore_presentation_but_track_semantics(tmp_path, monkeypatch):
    package = tmp_path / "package"
    shutil.copytree(core.PACKAGE, package)
    monkeypatch.setattr(core, "PACKAGE", package)
    monkeypatch.setattr(contracts, "PACKAGE", package)
    before = contracts.versions()
    for filename in ("report.py", "performance_report.py", "sharing.py", "__init__.py"):
        (package / filename).write_text("# presentation or package version change")
    assert before == contracts.versions()
    (package / "scoring.py").write_text("# intentional scorer change")
    after = contracts.versions()
    assert before["scorer"] != after["scorer"]
    assert before["adapter"] == after["adapter"]
    (package / "adapters.py").write_text("# parser change")
    assert after["adapter"] != contracts.versions()["adapter"]
    (package / "scheduler.py").write_text("# scheduling change")
    assert after["scheduler"] != contracts.versions()["scheduler"]


def test_resume_changes_concurrency_without_rewriting_original_conditions(config, tmp_path):
    original = run(config)
    records = runner.read_records(original)
    original_fragment = next((original / "segments").glob("*.json"))
    fragment_bytes = original_fragment.read_bytes()
    # A synthetic interrupted run: only two completed samples survived.
    (original / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records[:2]))
    changed = copy.deepcopy(config)
    changed.update(concurrency=3, progress_interval=2, output_dir=str(tmp_path / "elsewhere"))
    changed["targets"]["fixture"]["concurrency"] = 2
    changed["targets"]["unused"] = {"kind": "responses", "model": "unused"}
    run(changed, resume=original)
    result = runner.read_records(original)
    assert len(result) == 5
    assert result[:2] == records[:2]
    assert original_fragment.read_bytes() == fragment_bytes
    assert read_json(original / "manifest.json")["config"]["concurrency"] == 1
    assert [f["concurrency"] for f in load_fragments(original)] == [1, 3]
    assert conditions({}, result[0])["concurrency"] == 1
    assert conditions({}, result[-1])["concurrency"] == 3
    fresh = run(changed)
    comparison = compare(original, fresh, tmp_path / "comparison.json")
    assert all(p["status"] == "matched" for p in comparison["pairs"])
    pairs = comparison["performance"]["pairs"]
    assert [p["status"] for p in pairs] == ["conditions_differ"] * 2 + ["matched"] * 3


@pytest.mark.parametrize("key,value", [("retries", 1), ("timeout", 301), ("seed", 43), ("cost_limit_usd", 1)])
def test_resume_rejects_experiment_or_budget_change(config, key, value):
    original = run(config)
    config[key] = value
    with pytest.raises(ValueError):
        run(config, resume=original)


def test_resume_rejects_stream_and_derived_records(config):
    original = run(config)
    config["targets"]["fixture"]["stream"] = True
    with pytest.raises(ValueError, match="续跑"):
        run(config, resume=original)
    config["targets"]["fixture"].pop("stream")
    manifest = read_json(original / "manifest.json")
    manifest["derived_from"] = {"operation": "regrade"}
    core.write_json(original / "manifest.json", manifest)
    with pytest.raises(ValueError, match="续跑"):
        run(config, resume=original)


def test_package_version_changes_do_not_break_new_resume_or_comparison(config, monkeypatch, tmp_path):
    original = run(config)
    monkeypatch.setattr(runner, "__version__", "0.4.1-presentation-only")
    run(config, resume=original)
    fresh = run(config)
    result = compare(original, fresh, tmp_path / "comparison.json")
    assert all(p["status"] == "matched" for p in result["pairs"])
    assert all(p["status"] == "matched" for p in result["performance"]["pairs"])


def test_legacy_protocol_remains_conservative(config, tmp_path):
    original = run(config)
    manifest = read_json(original / "manifest.json")
    manifest.pop("contract_versions")
    manifest["resume_hash"] = "old-whole-config-source-hash"
    core.write_json(original / "manifest.json", manifest)
    with pytest.raises(ValueError, match="续跑"):
        run(config, resume=original)
    records = runner.read_records(original)
    legacy = copy.deepcopy(records[0])
    legacy.pop("performance_conditions")
    from dummy_llm_test.performance import compare_performance

    result = compare_performance(manifest, manifest, [legacy], [records[0]])
    assert result["pairs"][0]["status"] == "conditions_differ"
    # Swapping old/new must not drop keys that only occur in the baseline schema.
    reverse = compare_performance(manifest, manifest, [records[0]], [legacy])
    assert reverse["pairs"][0]["status"] == "conditions_differ"


def test_share_allowlist_blocks_private_and_untrusted_strings(config, tmp_path):
    original = run(config)
    records = runner.read_records(original)
    secret = "PRIVATE-SENTINEL-令牌 https://private.invalid /Users/private </script><script>alert(1)</script>"
    for record in records:
        for k in ("sample_id", "case_id", "suite", "target", "case_hash", "timestamp"):
            record[k] = secret + str(record["repeat"]) + k
        record["response"].update(
            text=secret, raw={secret: secret}, error=secret, actual_model=secret, stream={"reason": secret}
        )
        record["timing"]["sample_started_at"] = secret
        record["attempts"][0].update(error=secret, raw=secret)
        record["grade"].update(explanation=secret, preview={"svg": secret})
    records[0]["response"]["status"] = secret
    records[0]["attempts"][0]["status"] = secret
    records[0]["grade"]["status"] = secret
    # Keep distinct sample identities to avoid latest-record de-duplication.
    for i, record in enumerate(records):
        record["sample_id"] += str(i)
    (original / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    snapshot = {p: p.read_bytes() for p in original.rglob("*") if p.is_file()}
    output = tmp_path / "shared"
    data = export_run(original, output)
    assert len(data["performance"]["observations"]) == 5
    contents = "".join(p.read_text() for p in output.iterdir())
    for forbidden in ("PRIVATE-SENTINEL", "private.invalid", "/Users/private", "alert(1)", "<script"):
        assert forbidden not in contents
    assert data["performance"]["observations"][0]["status"] == "other"
    assert all(p.read_bytes() == b for p, b in snapshot.items())
    assert set(output.iterdir()) == {output / p for p in ("index.html", "share.json", "README.txt")}
    with pytest.raises(ValueError, match="已存在"):
        export_run(original, output)
    with pytest.raises(ValueError, match="之外"):
        export_run(original, original / "shared")


def test_share_preserves_missing_values_and_separates_manual(config, tmp_path):
    original = run(config)
    records = runner.read_records(original)
    records[0]["response"]["usage"] = {}
    records[1]["kind"] = "svg"
    records[1]["grade"] = {"score": None, "status": "pending_review"}
    (original / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    core.write_json(
        original / "reviews.json",
        [
            {
                "sample_id": records[1]["sample_id"],
                "rubric": "svg-v1",
                "reviewer": "private-reviewer",
                "scores": {"subject": 2, "overall": 1, "private-dimension": 2},
                "comment": "private-comment",
            }
        ],
    )
    output = tmp_path / "shared"
    result = CliRunner().invoke(main, ["share", "export", str(original), "--output", str(output)])
    assert result.exit_code == 0, result.output
    data = read_json(output / "share.json")
    row = data["performance"]["observations"][0]
    assert row["output_tokens"] is None and row["final_attempt_tps"] is None
    assert data["objective_grades"][1]["score"] is None
    assert data["human_reviews"][0]["scores"] == {"subject": 2, "overall": 1}
    assert "private-" not in (output / "share.json").read_text()
