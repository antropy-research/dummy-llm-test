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
