import json

import httpx
import pytest

from dummy_llm_test import adapters, streaming
from dummy_llm_test.config import validate_target
from dummy_llm_test.core import Case


class ScheduledStream(httpx.SyncByteStream):
    def __init__(self, events, clock):
        self.events, self.clock = events, clock

    def __iter__(self):
        for at, payload in self.events:
            self.clock[0] = at
            if isinstance(payload, Exception):
                raise payload
            if payload == "heartbeat":
                yield b": heartbeat\n\n"
            else:
                text = payload if isinstance(payload, str) else json.dumps(payload)
                yield ("data: " + text + "\n\n").encode()


def call(monkeypatch, kind, events, content_type="text/event-stream"):
    clock = [0]
    real_client = httpx.Client
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200, headers={"content-type": content_type}, stream=ScheduledStream(events, clock)
        )

    monkeypatch.setattr(adapters.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        adapters.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
    )
    response = adapters.call_api(
        Case("a", "b", "q"),
        {"kind": kind, "model": "fixed", "base_url": "https://local.invalid/v1", "stream": True},
        10,
    )
    return response, seen


def chunk(delta=None, finish=None, usage=None):
    return {"choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}], "usage": usage}


def terminal(status="completed", text="ab", usage=None):
    return {
        "type": "response." + status,
        "response": {
            "status": status,
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "usage": usage,
        },
    }


def test_chat_visible_events_and_reasoning_tokens(monkeypatch):
    response, requests = call(
        monkeypatch,
        "chat_completions",
        [
            (0.1, chunk({"role": "assistant"})),
            (0.2, "heartbeat"),
            (1, chunk({"reasoning_content": "hidden"})),
            (2, chunk({"content": "a"})),
            (4, chunk({"content": "b"})),
            (5, chunk(finish="stop")),
            (
                6,
                {
                    "choices": [],
                    "usage": {
                        "completion_tokens": 100,
                        "completion_tokens_details": {"reasoning_tokens": 90},
                    },
                },
            ),
            (7, "[DONE]"),
        ],
    )
    assert requests[0]["stream"] and requests[0]["stream_options"] == {"include_usage": True}
    assert response.text == "ab" and response.status == "ok"
    assert response.elapsed == 7
    assert response.stream["first_visible_text_seconds"] == 2
    assert response.stream["visible_text_receive_seconds"] == 2
    assert response.usage["output_tokens"] == 100 and response.usage["reasoning_tokens"] == 90
    assert response.stream["generation_tokens_per_second"] is None
    assert [e["index"] for e in response.stream["events"]] == list(range(8))
    assert response.stream["events"][1]["type"] == "heartbeat"


def test_responses_stream_preserves_terminal_usage(monkeypatch):
    response, requests = call(
        monkeypatch,
        "responses",
        [
            (0.1, {"type": "response.created"}),
            (1, {"type": "response.reasoning_text.delta", "delta": "thought"}),
            (2, {"type": "response.output_text.delta", "delta": "a"}),
            (5, {"type": "response.output_text.delta", "delta": "b"}),
            (7, terminal(usage={"output_tokens": 20, "output_tokens_details": {"reasoning_tokens": 18}})),
        ],
    )
    assert requests[0]["stream"] and "stream_options" not in requests[0]
    assert response.status == "ok" and response.text == "ab"
    assert (
        response.stream["first_visible_text_seconds"] == 2
        and response.stream["visible_text_receive_seconds"] == 3
    )
    assert response.usage["output_tokens"] == 20


def test_terminal_text_is_not_first_token(monkeypatch):
    response, _ = call(monkeypatch, "responses", [(5, terminal())])
    assert response.status == "ok" and response.text == "ab"
    assert response.stream["first_visible_text_seconds"] is None
    assert response.stream["reason"] == "no_visible_text_delta"


@pytest.mark.parametrize(
    "kind,events,status",
    [
        (
            "chat_completions",
            [(1, chunk({"content": "a"})), (2, chunk(finish="length")), (3, "[DONE]")],
            "truncated",
        ),
        ("chat_completions", [(1, chunk({"content": "a"}))], "truncated"),
        (
            "chat_completions",
            [
                (1, chunk({"tool_calls": [{"function": {"name": "tool"}}]})),
                (2, chunk(finish="tool_calls")),
                (3, "[DONE]"),
            ],
            "protocol_violation",
        ),
        (
            "chat_completions",
            [(1, chunk({"refusal": "no"})), (2, chunk(finish="stop")), (3, "[DONE]")],
            "refused",
        ),
        ("chat_completions", [(1, chunk(finish="stop")), (2, "[DONE]")], "empty_response"),
        (
            "responses",
            [(1, {"type": "response.function_call_arguments.delta", "delta": "{}"}), (2, terminal())],
            "protocol_violation",
        ),
        ("responses", [(1, terminal("incomplete"))], "truncated"),
        ("responses", [(1, terminal("failed"))], "api_error"),
    ],
)
def test_stream_failure_classes(monkeypatch, kind, events, status):
    response, _ = call(monkeypatch, kind, events)
    assert response.status == status
    assert response.usage.get("output_tokens") is None


def test_timeout_preserves_partial_text_and_arrivals(monkeypatch):
    response, _ = call(
        monkeypatch,
        "chat_completions",
        [(2, chunk({"content": "a"})), (5, httpx.ReadTimeout("fixture timeout"))],
    )
    assert response.status == "timeout" and response.text == "a"
    assert response.stream["first_visible_text_seconds"] == 2
    assert response.stream["visible_text_receive_seconds"] == 0  # one observed chunk: real zero
    assert len(response.raw["stream_events"]) == 1


def test_stream_mode_never_falls_back_to_json(monkeypatch):
    response, requests = call(monkeypatch, "responses", [(1, terminal())], "application/json")
    assert response.status == "protocol_error" and len(requests) == 1
    assert response.stream["first_visible_text_seconds"] is None


def test_cli_and_nonboolean_stream_configuration_rejected():
    with pytest.raises(ValueError, match="CLI"):
        validate_target("t", {"kind": "claude", "stream": True})
    with pytest.raises(ValueError, match="布尔"):
        validate_target("t", {"kind": "responses", "stream": "true"})


def test_sse_multiline_and_invalid_data_keep_audit_order():
    capture = streaming.StreamCapture("responses", 0, lambda: 1, lambda: "UTC")
    capture.consume(
        ["event: response.created", 'data: {"type":', 'data: "response.created"}', "", "data: invalid", ""]
    )
    result = capture.response(adapters.parse_api)
    assert result.status == "protocol_error"
    assert [e["type"] for e in result.stream["events"]] == ["response.created", "invalid_json"]


def test_terminal_event_does_not_wait_for_connection_timeout(monkeypatch):
    response, _ = call(monkeypatch, "responses", [(1, terminal()), (5, httpx.ReadTimeout("after done"))])
    assert response.status == "ok" and response.elapsed == 1


def test_text_is_observed_before_terminal_event_with_barrier(monkeypatch):
    import threading

    arrived = threading.Event()
    release = threading.Event()
    original_frame = streaming.StreamCapture.frame

    def frame(self, lines):
        original_frame(self, lines)
        if self.first is not None and not self.terminal:
            arrived.set()
            assert release.wait(3)

    monkeypatch.setattr(streaming.StreamCapture, "frame", frame)
    result = []
    errors = []

    def run():
        try:
            capture = streaming.StreamCapture("responses", 0, lambda: 1)
            capture.consume(
                [
                    'data: {"type":"response.output_text.delta","delta":"ab"}',
                    "",
                    "data: " + json.dumps(terminal()),
                    "",
                ]
            )
            result.append(capture.response(adapters.parse_api))
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert arrived.wait(3)
        assert not result
    finally:
        release.set()
        thread.join(3)
    assert not errors and not thread.is_alive()
    assert result[0].stream["first_visible_text_seconds"] == 1
