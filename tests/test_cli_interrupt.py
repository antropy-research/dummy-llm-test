"""Exercise actual process signals, CLI persistence and resume without a provider."""

import json
import os
import signal
import subprocess
import sys
import time

import yaml


def test_cli_sigint_then_resume_in_separate_process(tmp_path):
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    executable = tmp_path / "fake-claude"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, sys, time\nfrom pathlib import Path\n"
        "if '--version' in sys.argv:\n print('fixture-cli 1'); sys.exit(0)\n"
        "if '--help' in sys.argv:\n"
        " print('--output-format --no-session-persistence --safe-mode --tools --strict-mcp-config'); sys.exit(0)\n"
        "sys.stdin.read()\n"
        f"Path({str(ready)!r}).touch()\n"
        "deadline = time.monotonic() + 10\n"
        f"while not Path({str(release)!r}).exists() and time.monotonic() < deadline: time.sleep(0.01)\n"
        "print(json.dumps({'type': 'result', 'result': '9.9', 'usage': {'input_tokens': 5, 'output_tokens': 2}}))\n"
    )
    executable.chmod(0o755)
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "default_target": "fixture",
                "output_dir": str(tmp_path / "runs"),
                "concurrency": 1,
                "timeout": 15,
                "targets": {"fixture": {"kind": "claude", "executable": str(executable)}},
                "levels": {"smoke": {"cases": ["basic.decimal", "basic.strawberry", "basic.count-r"]}},
            }
        )
    )
    command = [
        sys.executable,
        "-c",
        "from dummy_llm_test.cli import main; main()",
        "--config",
        str(config),
        "run",
        "--level",
        "smoke",
    ]
    # Installed console module is invoked from outside the source checkout.
    proc = subprocess.Popen(command, cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "Fixture never started"
        os.kill(proc.pid, signal.SIGINT)
        release.touch()
        stdout, stderr = proc.communicate(timeout=20)
        assert proc.returncode == 130, (stdout, stderr)
    finally:
        release.touch()
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=20)
    directory = (tmp_path / "runs/latest").resolve()
    records = (directory / "results.jsonl").read_text().splitlines()
    assert len(records) == 1
    assert json.loads(records[0])["response"]["status"] == "ok"
    assert json.loads((directory / "summary.json").read_text())["scheduler"]["state"] == "interrupted"
    result = subprocess.run(
        command + ["--resume", str(directory)], cwd=tmp_path, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in (directory / "results.jsonl").read_text().splitlines()]
    assert len(records) == len({row["sample_id"] for row in records}) == 3
    assert all(len(row["attempts"]) == 1 for row in records)
