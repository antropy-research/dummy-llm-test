import json
import sys

import httpx
import pytest

from dummy_llm_test import adapters
from dummy_llm_test.core import Case


def chat(text="21", finish="stop", **extra):
    return {
        "model": "test-model",
        "choices": [{"message": {"content": text, **extra}, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": 8,
            "completion_tokens": 3,
            "completion_tokens_details": {"reasoning_tokens": 1},
        },
    }


def test_api_wire_protocols_explicit():
    case = Case("x", "x", "question", system="instruction")
    target = {
        "kind": "chat_completions",
        "model": "fixed-model",
        "max_output_tokens": 500,
        "reasoning_effort": "high",
    }
    endpoint, payload = adapters.api_payload(case, target)
    assert endpoint == "/chat/completions"
    assert payload["model"] == "fixed-model" and payload["messages"][0]["role"] == "system"
    assert payload["max_completion_tokens"] == 500 and payload["reasoning_effort"] == "high"
    endpoint, payload = adapters.api_payload(case, {**target, "kind": "responses"})
    assert endpoint == "/responses" and payload["instructions"] == "instruction"
    assert payload["reasoning"] == {"effort": "high"} and payload["store"] is False
    assert "expected" not in json.dumps(payload)
    with pytest.raises(ValueError, match="seed"):
        adapters.api_payload(case, {**target, "kind": "responses", "seed": 42})


@pytest.mark.parametrize(
    "raw,status",
    [
        (chat(), "ok"),
        (chat(finish="length"), "truncated"),
        (chat(text=""), "empty_response"),
        (chat(refusal="refused"), "refused"),
        (chat(tool_calls=[{"id": "tool"}]), "protocol_violation"),
        ({"choices": []}, "protocol_error"),
    ],
)
def test_chat_status(raw, status):
    assert adapters.parse_api(raw, "chat_completions").status == status


@pytest.mark.parametrize(
    "status,expected",
    [("completed", "ok"), ("incomplete", "truncated"), ("failed", "api_error"), ("queued", "protocol_error")],
)
def test_responses_status(status, expected):
    raw = {
        "status": status,
        "output": [
            {"type": "reasoning"},
            {"type": "message", "content": [{"type": "output_text", "text": "21"}]},
        ],
    }
    response = adapters.parse_api(raw, "responses")
    assert response.status == expected
    assert response.text == "21"
    assert response.usage["input_tokens"] is None


@pytest.mark.parametrize(
    "http_status,expected",
    [(429, "rate_limit"), (503, "server_error"), (401, "api_error"), (400, "api_error"), (302, "api_error")],
)
def test_api_transport_failure(monkeypatch, http_status, expected):
    original = httpx.Client
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(http_status, json={"error": "test"})

    monkeypatch.setattr(
        adapters.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    target = {"kind": "chat_completions", "model": "fixed", "base_url": "https://fixture.invalid/v1"}
    assert adapters.call_api(Case("x", "x", "hello"), target, 1).status == expected
    assert len(seen) == 1  # No implicit retry, downgrade, redirect, or alternate protocol.
    assert str(seen[0].url) == "https://fixture.invalid/v1/chat/completions"


def test_timeout_and_invalid_json(monkeypatch):
    original = httpx.Client

    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)

    target = {"kind": "responses", "model": "fixed", "base_url": "https://fixture.invalid/v1"}
    monkeypatch.setattr(
        adapters.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(timeout), **kw)
    )
    assert adapters.call_api(Case("x", "x", "hello"), target, 1).status == "timeout"
    monkeypatch.setattr(
        adapters.httpx,
        "Client",
        lambda **kw: original(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, text="not JSON")), **kw
        ),
    )
    assert adapters.call_api(Case("x", "x", "hello"), target, 1).status == "protocol_error"


def codex_events(tool=False):
    events = [
        {"type": "thread.started", "thread_id": "new"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "preamble"}},
    ]
    if tool:
        events.append({"type": "item.completed", "item": {"type": "command_execution", "command": "tool"}})
    events += [
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Final Answer: 21"}},
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 90, "output_tokens": 8, "reasoning_output_tokens": 5},
        },
    ]
    return "\n".join(json.dumps(e) for e in events)


@pytest.mark.parametrize(
    "mode,fp,status",
    [
        ("controlled", False, "protocol_violation"),
        ("native", False, "ok"),
        ("native", True, "protocol_violation"),
    ],
)
def test_codex_tool_audit(mode, fp, status):
    response = adapters.parse_cli(codex_events(True), "", 0, False, "codex", mode, fp)
    assert response.status == status
    assert response.text == "Final Answer: 21" and response.usage["reasoning_tokens"] == 5


def test_cli_no_completion_is_not_success():
    stdout = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "21"}})
    assert adapters.parse_cli(stdout, "", 0, False, "codex", "controlled").status == "protocol_error"
    assert adapters.parse_cli(stdout, "", -9, True, "codex", "controlled").status == "timeout"


def test_claude_events():
    events = [
        {
            "type": "assistant",
            "message": {"model": "test-claude", "content": [{"type": "text", "text": "21"}]},
        },
        {
            "type": "result",
            "result": "21",
            "is_error": False,
            "usage": {"input_tokens": 20, "output_tokens": 2},
            "total_cost_usd": 0.01,
        },
    ]
    result = adapters.parse_cli("\n".join(map(json.dumps, events)), "", 0, False, "claude", "controlled")
    assert result.status == "ok" and result.actual_model == "test-claude"
    assert result.usage["reported_cost_usd"] == 0.01


def test_claude_refusal_not_mislabeled_success():
    events = [
        {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "stop_reason": "refusal",
            "terminal_reason": "api_error",
            "result": "Request refused",
        }
    ]
    result = adapters.parse_cli(json.dumps(events[0]), "", 1, False, "claude", "controlled")
    assert result.status == "refused" and result.error == "Request refused"


def test_controlled_cli_command(monkeypatch):
    monkeypatch.setattr(adapters, "codex_connection", lambda t: ("fixed-model", []))
    args = adapters.cli_command({"kind": "codex"}, "controlled", "/tmp/empty", {"executable": "codex"})
    assert "--ignore-user-config" in args and "--ephemeral" in args
    assert 'web_search="disabled"' in args and "memories" in args and "shell_tool" in args
    assert "--dangerously-bypass-approvals-and-sandbox" not in args
    args = adapters.cli_command({"kind": "claude"}, "controlled", "/tmp/empty", {"executable": "claude"})
    assert args[args.index("--tools") + 1] == ""
    assert "--safe-mode" in args and "--strict-mcp-config" in args


def test_process_timeout_terminates(tmp_path):
    code, _, _, timed_out = adapters.run_process(
        [sys.executable, "-c", "import time; time.sleep(60)"], cwd=tmp_path, timeout=0.05
    )
    assert timed_out and code != 0
