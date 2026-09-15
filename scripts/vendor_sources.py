"""Fetch a reviewed, immutable allowlist. Never execute downloaded code here."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src/dummy_llm_test/data"
VENDOR = ROOT / "src/dummy_llm_test/vendor"
SOURCES = {
    "modeltrace": ("xqy2006/ModelTrace", "60949ef522a84f66b1236b459308b48028d36949"),
    "simplebench": ("simple-bench/SimpleBench", "fbc2e429085bdedad7d1a236d2bc9bc18c95f16e"),
    "bullshitbench": ("petergpt/bullshit-benchmark", "2678ac296fe6e234d391e0f4ab339f6a777ba2a3"),
    "openenv": ("huggingface/OpenEnv", "da5929566e99c8eb376a47042b316cb13c0aae29"),
    "collatz": ("unryuu/idiot", "01070f7854ff5c3b0722060a4e7e51417ebe2eba"),
    "candy": ("haowang02/codex-candy-eval", "4dde0a9e8043c9f84e5e810c4f7cdd555751a20c"),
}


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    VENDOR.mkdir(parents=True, exist_ok=True)
    manifest = []

    def fetch(source, remote, dest=None):
        repo, sha = SOURCES[source]
        url = f"https://raw.githubusercontent.com/{repo}/{sha}/{quote(remote)}"
        raw = urlopen(Request(url, headers={"User-Agent": "dummy-llm-test-vendor"}), timeout=60).read()
        record = {
            "source": source,
            "repo": repo,
            "commit": sha,
            "path": remote,
            "url": url,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        if dest:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            record["local"] = str(dest.relative_to(ROOT / "src/dummy_llm_test"))
        manifest.append(record)
        print(source, remote, len(raw), flush=True)
        return raw

    fetch("modeltrace", "fingerprint.py", VENDOR / "modeltrace.py")
    fetch("modeltrace", "data/unified_bank.json", DATA / "modeltrace_bank.json")
    fetch("simplebench", "simple_bench_public.json", DATA / "simplebench.json")
    fetch("simplebench", "system_prompt.txt", DATA / "simplebench_system.txt")
    fetch("bullshitbench", "questions.v2.json", DATA / "bullshitbench.json")
    fetch("openenv", "envs/pelican_svg_env/server/tasks.py", VENDOR / "openenv_tasks.py")
    # Discover the actual Collatz prompt path from this pinned tree, not a model's answer.
    repo, sha = SOURCES["collatz"]
    tree = json.loads(
        urlopen(
            Request(
                f"https://api.github.com/repos/{repo}/git/trees/{sha}?recursive=1",
                headers={"User-Agent": "dummy-llm-test-vendor"},
            ),
            timeout=60,
        ).read()
    )
    paths = [
        x["path"] for x in tree["tree"] if x["type"] == "blob" and x["path"].startswith("tests/collatz-16/")
    ]
    print("collatz paths:", paths, flush=True)
    for p in paths:
        fetch("collatz", p, DATA / "collatz" / p.removeprefix("tests/collatz-16/"))
    # Cache only the mathematical statement. Do not redistribute the unlicensed runner.
    raw = fetch("candy", "codex_candy_eval.py")
    module = ast.parse(raw.decode())
    prompt = next(
        ast.literal_eval(n.value)
        for n in module.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "CODEX_PROMPT" for t in n.targets)
    )
    (DATA / "candy_prompt.txt").write_text(prompt, encoding="utf-8")
    manifest[-1]["extracted_local"] = "data/candy_prompt.txt"
    manifest[-1]["extracted_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
    for source in ("modeltrace", "simplebench", "bullshitbench", "openenv", "collatz"):
        fetch(source, "LICENSE", DATA / "licenses" / f"{source}.txt")
    (DATA / "sources.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
