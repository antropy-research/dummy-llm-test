import copy
import random

import pytest

from dummy_llm_test.core import write_json
from dummy_llm_test.fingerprint import analyze, challenges, load_bank, load_challenges
from dummy_llm_test.vendor import modeltrace


def outputs():
    rng = random.Random(19)
    return [
        {
            "text": ", ".join(str(rng.randint(1, 355)) for _ in range(310)),
            "expected_count": 310,
            "status": "ok",
            "tools": [],
        }
        for _ in range(3)
    ]


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_adapter_matches_unmodified_upstream(count):
    bank = load_bank()
    samples = outputs()
    for row in samples[count:]:
        row["text"] = "I cannot produce that sequence"
    result = analyze(samples, bank)
    assert result["used_outputs"] == count
    assert result["status"] == ("complete" if count == 3 else "incomplete")
    if count:
        upstream = modeltrace.analyze_global_outputs(samples, bank)
        assert result["results"] == upstream["results"]
        assert result["family_probabilities"] == upstream["family_probabilities"]
        assert result["diagnostics"] == upstream["diagnostics"]
        assert sum(x["probability"] for x in result["results"]) == pytest.approx(1)
    else:
        assert result["results"] == []


def test_tools_and_truncation_never_enter_fingerprint():
    samples = outputs()
    samples[0]["tools"] = [{"type": "command_execution"}]
    samples[1]["status"] = "truncated"
    assert analyze(samples)["used_outputs"] == 1


def test_upstream_gate_boundary():
    samples = [{"text": ",".join(["7"] * n), "expected_count": 300} for n in [164, 165, 166]]
    result = analyze(samples)
    assert [d["accepted"] for d in result["diagnostics"]] == [False, True, True]
    assert modeltrace.parse_numbers("300 numbers: 1, 2, 3. End 99") == [1, 2, 3]


def test_challenges_reproducible(tmp_path):
    assert challenges(10) == challenges(10)
    assert challenges(10) != challenges(11)
    assert all(292 <= p["expected_count"] <= 332 for p in challenges(10))
    path = tmp_path / "challenges.json"
    write_json(path, {"challenges": challenges(10)})
    assert load_challenges(path) == challenges(10)


@pytest.mark.parametrize("mutation", ["schema", "order", "temperature", "dimension"])
def test_reject_incompatible_banks(tmp_path, mutation):
    bank = copy.deepcopy(load_bank())
    if mutation == "schema":
        bank["schema"] = "other"
    elif mutation == "order":
        bank["robust"]["model_order"].reverse()
    elif mutation == "temperature":
        bank["calibration"]["1"]["beta"] = -1
    else:
        bank["robust"]["hellinger"]["feature_mean"] = [1, 2]
    path = tmp_path / "bad.json"
    write_json(path, bank)
    with pytest.raises(ValueError, match="不兼容"):
        load_bank(path)
