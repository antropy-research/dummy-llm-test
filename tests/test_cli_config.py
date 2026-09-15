import pytest
from click.testing import CliRunner

from dummy_llm_test.cli import main
from dummy_llm_test.config import load_config


def test_dry_run_does_not_require_credentials():
    result = CliRunner().invoke(
        main, ["--config", "config.yaml", "run", "--dry-run", "--level", "quick", "--target", "api"]
    )
    assert result.exit_code == 0 and '"invocations": 5' in result.output


@pytest.mark.parametrize(
    "content",
    [
        "concurrency: 0",
        "progress_interval: 0",
        "targets:\n  api:\n    concurrency: false",
        "targets:\n  codex:\n    concurrency: -1",
        "timeout: -1",
        "unknown_option: true",
        "levels:\n  mylevel:\n    suites: candy",
        "targets:\n  api:\n    base_url: https://user:password@example.com/v1",
        "targets:\n  api:\n    input_price_per_million: .nan",
        "levels: [",
    ],
)
def test_invalid_config_before_paid_calls(tmp_path, content):
    p = tmp_path / "config.yaml"
    p.write_text(content)
    with pytest.raises(ValueError):
        load_config(p)


def test_missing_cli_message(monkeypatch):
    from dummy_llm_test import adapters

    monkeypatch.setattr(adapters.shutil, "which", lambda x: None)
    with pytest.raises(ValueError, match="找不到"):
        adapters.cli_preflight({"kind": "codex"}, "controlled")


def test_cli_concurrency_override_in_dry_run(tmp_path):
    import json

    p = tmp_path / "config.yaml"
    p.write_text("concurrency: 2\ntargets:\n  codex:\n    concurrency: 3\n")
    result = CliRunner().invoke(main, ["--config", str(p), "run", "--dry-run", "--concurrency", "5"])
    assert result.exit_code == 0
    plan = json.loads(result.output)
    assert plan["concurrency"] == 5 and plan["target_concurrency"] == {"codex": 3}
    result = CliRunner().invoke(main, ["run", "--dry-run", "--concurrency", "0"])
    assert result.exit_code == 2


def test_cli_graceful_interrupt_exit_code(monkeypatch):
    from dummy_llm_test import cli
    from dummy_llm_test.scheduler import RunInterrupted

    def run(*_):
        raise RunInterrupted("saved")

    monkeypatch.setattr(cli, "execute_run", run)
    result = CliRunner().invoke(main, ["--config", "config.yaml", "run"])
    assert result.exit_code == 130
