"""SSE capture: arrival timestamps describe client observations, never token generation."""

from __future__ import annotations

import json
import math
import time

from .core import Response, now


def unavailable_stream(reason):
    return {
        "first_visible_text_seconds": None,
        "visible_text_receive_seconds": None,
        "generation_tokens_per_second": None,
        "reason": reason,
        "generation_rate_reason": "token_range_and_generation_time_boundaries_unavailable",
        "events": [],
    }


def visible_metrics(events):
    """Recompute client-visible boundaries from recorded, ordered SSE frames."""
    arrivals = []
    for event in events:
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        texts = []
        if event.get("type") == "response.output_text.delta":
            texts.append(data.get("delta"))
        elif event.get("type") == "chat.completion.chunk":
            choices = data.get("choices") or []
            if isinstance(choices, list):
                for choice in choices:
                    if isinstance(choice, dict) and choice.get("index", 0) == 0:
                        delta = choice.get("delta") or {}
                        if isinstance(delta, dict):
                            texts.append(delta.get("content"))
        offset = event.get("offset_seconds")
        if (
            any(isinstance(t, str) and t.strip() for t in texts)
            and isinstance(offset, (int, float))
            and not isinstance(offset, bool)
            and math.isfinite(offset)
            and offset >= 0
        ):
            arrivals.append(offset)
    if not arrivals or arrivals != sorted(arrivals):
        return {"first_visible_text_seconds": None, "visible_text_receive_seconds": None}
    return {
        "first_visible_text_seconds": arrivals[0],
        "visible_text_receive_seconds": arrivals[-1] - arrivals[0],
    }


class StreamCapture:
    def __init__(self, kind, started, clock=None, utc=None):
        self.kind, self.started = kind, started
        self.clock, self.utc = clock or time.monotonic, utc or now
        self.events = []
        self.parts, self.tools = [], []
        self.first = self.last = None
        self.usage, self.model = None, None
        self.finish, self.done, self.terminal, self.refused = None, False, None, False
        self.error = None

    def event(self, event_type, data):
        offset = self.clock() - self.started
        self.events.append(
            {
                "index": len(self.events),
                "type": event_type,
                "offset_seconds": offset,
                "received_at": self.utc(),
                "data": data,
            }
        )
        return offset

    def frame(self, lines):
        data = "\n".join(line[5:].removeprefix(" ") for line in lines if line.startswith("data:"))
        label = next((line[6:].strip() for line in lines if line.startswith("event:")), "message")
        if not data:
            self.event("heartbeat", "\n".join(lines))
            return
        if data == "[DONE]":
            self.event("done", data)
            self.done = True
            return
        try:
            payload = json.loads(data)
        except ValueError:
            self.event("invalid_json", data)
            self.error = "invalid SSE JSON"
            return
        if not isinstance(payload, dict):
            self.event("invalid_event", payload)
            self.error = "SSE data must be an object"
            return
        event_type = payload.get("type", label if self.kind == "responses" else "chat.completion.chunk")
        at = self.event(event_type, payload)
        if self.done or self.terminal is not None:
            self.error = "data received after terminal event"
            return
        visible = ""
        if self.kind == "chat_completions":
            self.model = payload.get("model", self.model)
            if payload.get("usage") is not None:
                self.usage = payload["usage"]
            if payload.get("error"):
                self.error = "stream returned an error event"
            for choice in payload.get("choices", []):
                if choice.get("index", 0) != 0:
                    continue
                delta = choice.get("delta") or {}
                content = delta.get("content")
                if isinstance(content, str):
                    visible += content
                self.tools.extend(delta.get("tool_calls") or [])
                if delta.get("function_call"):
                    self.tools.append(delta["function_call"])
                self.refused |= bool(delta.get("refusal"))
                self.finish = choice.get("finish_reason") or self.finish
                if choice.get("finish_reason") in ("tool_calls", "function_call") and not self.tools:
                    self.tools.append({"finish_reason": choice["finish_reason"]})
        else:
            if event_type == "response.output_text.delta" and isinstance(payload.get("delta"), str):
                visible = payload["delta"]
            elif event_type in ("response.completed", "response.incomplete", "response.failed"):
                self.terminal = payload.get("response")
                if not isinstance(self.terminal, dict):
                    self.error = "missing terminal response"
                elif self.terminal.get("status") != event_type.removeprefix("response."):
                    self.error = "terminal event and response status differ"
            elif event_type == "response.refusal.delta":
                self.refused = True
            elif event_type == "response.output_item.added":
                item = payload.get("item", {})
                if item.get("type") not in ("message", "reasoning"):
                    self.tools.append(item)
            elif event_type == "error":
                self.error = "stream returned an error event"
            elif any(
                name in event_type
                for name in (
                    "function_call",
                    "web_search_call",
                    "file_search_call",
                    "code_interpreter_call",
                    "mcp_call",
                )
            ):
                self.tools.append(payload)
        if visible:
            self.parts.append(visible)
            # Whitespace is retained in answers but does not establish a visible-text boundary.
            if visible.strip():
                self.first = at if self.first is None else self.first
                self.last = at

    def consume(self, lines):
        frame = []
        for line in lines:
            if not line:
                if frame:
                    self.frame(frame)
                    frame = []
                    if self.done or self.terminal is not None:
                        return
            else:
                frame.append(line)
        if frame:
            self.frame(frame)

    def response(self, parser):
        if self.kind == "chat_completions":
            raw = {
                "model": self.model,
                "usage": self.usage,
                "choices": [
                    {
                        "finish_reason": self.finish,
                        "message": {
                            "content": "".join(self.parts),
                            "tool_calls": self.tools,
                            "refusal": "refused" if self.refused else None,
                        },
                    }
                ],
            }
            complete = self.finish is not None and self.done
        else:
            raw = self.terminal or {
                "status": "incomplete",
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "".join(self.parts)}]},
                    *self.tools,
                ],
            }
            complete = isinstance(self.terminal, dict)
        try:
            result = parser(raw, self.kind)
        except (ValueError, TypeError, KeyError, AttributeError):
            result = Response(
                text="".join(self.parts), status="protocol_error", error="invalid stream schema"
            )
        if self.refused:
            result.status = "refused"
        if self.tools:
            result.tools = result.tools or self.tools
            result.status = "protocol_violation"
        if not complete and result.status == "ok":
            result.status = "truncated"
        if self.error:
            result.status, result.error = "protocol_error", self.error
        result.raw = {"assembled": raw, "stream_events": self.events}
        result.stream = unavailable_stream("no_visible_text_delta" if self.first is None else None)
        result.stream.update(
            events=self.events,
            first_visible_text_seconds=self.first,
            visible_text_receive_seconds=self.last - self.first if self.first is not None else None,
        )
        return result
