import hashlib

import pytest

from dummy_llm_test.catalog import candy_solution, catalog, select
from dummy_llm_test.config import load_config
from dummy_llm_test.core import DATA, PACKAGE, Case, Response, read_json
from dummy_llm_test.scoring import final_answer, safe_svg, score


def test_pinned_sources():
    for source in read_json(DATA / "sources.json"):
        path = source.get("local") or source.get("extracted_local")
        expected = source["sha256"] if source.get("local") else source["extracted_sha256"]
        assert hashlib.sha256((PACKAGE / path).read_bytes()).hexdigest() == expected


def test_catalog_coverage():
    config = load_config()
    full = select(config, "full")
    assert len(select(config, "quick")) == 5
    assert len(select(config, "fingerprint")) == 3
    counts = {s: sum(c.suite == s for c in full) for s in {c.suite for c in full}}
    assert counts == {
        "candy": 10,
        "svg": 31,
        "diagnostic": 2,
        "basic": 12,
        "instruction": 12,
        "collatz": 1,
        "simplebench": 10,
        "bullshitbench": 100,
        "context": 8,
        "modeltrace": 3,
    }
    assert len(full) == 189
    assert [c.hash for c in full] == [c.hash for c in catalog(config)]


def test_filter_requires_whole_fingerprint_group():
    config = load_config()
    config["disabled_cases"] = ["modeltrace.probe-1"]
    with pytest.raises(ValueError, match="整组"):
        select(config, "full")
    config["levels"]["bad"] = {"cases": ["typo"]}
    with pytest.raises(ValueError, match="未知"):
        select(config, "bad")


def test_candy_independent_bounds():
    solved = candy_solution()
    assert solved == {"answer": 21, "selections": [[9, 12]], "blind_answer": 29}
    # A minimal known case: with one apple and peach in each shape, choosing all of one shape
    # and one of the other guarantees a cross-flavour pair; two total do not.
    assert candy_solution((1, 1, 0, 1, 1, 0))["answer"] == 3


def test_collatz_oracle():
    failures = []
    for n in range(1, 1001):
        start, hit = n, False
        while n != 1:
            hit |= n == 16
            n = n // 2 if n % 2 == 0 else n * 3 + 1
        if not hit:
            failures.append(start)
    assert failures == [1, 2, 4, 8]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("21 is a tempting answer.\nFinal Answer: 29", "29"),
        ("Some reasoning 21\nFinal Answer: 21", "21"),
        ("答案：**21**", "21"),
        ("最少需要 21 个糖果。", "21"),
        ("Final Answer: B", "B"),
        ("9.9 更大。", "9.9"),
        ("所以 **21 个是最少的保证数目**。", "21"),
        ("\\boxed{21}", "21"),
        ("21 or 29", None),
        ("Not 21, surely not 21.", None),
    ],
)
def test_strict_final(text, expected):
    assert final_answer(text) == expected


def test_candy_false_positive_is_visible():
    case = select(load_config(), "quick")[0]
    result = score(case, Response(text="21 is wrong.\nFinal Answer: 29"))
    assert result["score"] == 0 and result["compatibility_score"] == 1
    assert score(case, Response(text="21", status="truncated"))["score"] is None


@pytest.mark.parametrize(
    "svg",
    [
        "<svg><script>alert(1)</script></svg>",
        '<svg onload="alert(1)"><circle r="4"/></svg>',
        '<svg><image href="https://attacker.example/image"/></svg>',
        '<svg><use href="file:///etc/passwd"/></svg>',
        '<svg><style>@import "https://attacker.example";</style></svg>',
        '<svg><rect style="fill:url(//attacker.example/a)"/></svg>',
        "<svg><foreignObject><div>test</div></foreignObject></svg>",
        '<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg>&x;</svg>',
        "<svg><style>rect{fill:u\\72l(//x)}</style></svg>",
    ],
)
def test_unsafe_svg_rejected(svg):
    assert safe_svg(svg)["svg"] is None


def test_svg_safety_is_not_visual_grade():
    case = Case("svg", "svg", "draw", "svg")
    result = score(
        case, Response(text='```svg\n<svg xmlns="http://www.w3.org/2000/svg"><circle r="5"/></svg>\n```')
    )
    assert result["score"] is None
    assert result["status"] == "pending_review"
    assert result["preview"]["status"] == "valid_svg"


def test_rules_and_context():
    cases = catalog(load_config())
    case = next(c for c in cases if c.id == "instruction.json-0")
    assert score(case, Response(text='{"label":"orchid","count":3}'))["score"] == 1
    assert score(case, Response(text='```json\n{"label":"orchid","count":3}\n```'))["score"] == 0
    for c in cases:
        if c.suite == "context":
            assert c.prompt.count("TARGET-ACCESS-CODE:") == 1
            assert c.expected in c.prompt
            assert score(c, Response(text=c.expected))["score"] == 1
