from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import tomllib
from pathlib import Path

import httpx

from .core import Response, now
from .streaming import StreamCapture, unavailable_stream


def api_payload(case, target):
    kind = target["kind"]
    if kind == "chat_completions":
        messages = [{"role": "system", "content": case.system}] if case.system else []
        messages.append({"role": "user", "content": case.prompt})
        token_field = target.get("chat_token_field", "max_completion_tokens")
        if token_field not in ("max_tokens", "max_completion_tokens"):
            raise ValueError("chat_token_field 必须为 max_tokens/max_completion_tokens")
        body = {
            "model": target["model"],
            "messages": messages,
            token_field: target.get("max_output_tokens", 8192),
            "stream": target.get("stream", False),
        }
        if target.get("reasoning_effort") is not None:
            body["reasoning_effort"] = target["reasoning_effort"]
        if target.get("stream"):
            body["stream_options"] = {"include_usage": True}
        endpoint = "/chat/completions"
    else:
        body = {
            "model": target["model"],
            "input": [{"role": "user", "content": case.prompt}],
            "max_output_tokens": target.get("max_output_tokens", 8192),
            "store": False,
            "stream": target.get("stream", False),
        }
        if case.system:
            body["instructions"] = case.system
        if target.get("reasoning_effort") is not None:
            body["reasoning"] = {"effort": target["reasoning_effort"]}
        if target.get("seed") is not None:
            raise ValueError("Responses 协议不支持此适配器的 seed 参数；请移除")
        endpoint = "/responses"
    for k in ("temperature", "top_p", "seed"):
        if target.get(k) is not None:
            body[k] = target[k]
    return endpoint, body


def parse_api(raw, kind):
    tools = []
    if kind == "chat_completions":
        choices = raw.get("choices") or []
        if not choices:
            return Response(status="protocol_error", raw=raw, error="missing choices")
        choice = choices[0]
        message = choice.get("message", {})
        content = message.get("content") or ""
        text = (
            content
            if isinstance(content, str)
            else "".join(c.get("text", "") for c in content if c.get("type") == "text")
        )
        tools = message.get("tool_calls") or (
            [message["function_call"]] if message.get("function_call") else []
        )
        reason = choice.get("finish_reason")
        status = (
            "truncated"
            if reason == "length"
            else "refused"
            if reason == "content_filter" or message.get("refusal")
            else "ok"
        )
        usage = raw.get("usage") or {}
        normalized = {
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            "cached_input_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
        }
    else:
        text_parts, refused = [], False
        for item in raw.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        text_parts.append(content.get("text", ""))
                    elif content.get("type") == "refusal":
                        refused = True
            elif item.get("type") != "reasoning":
                tools.append(item)
        text = "\n".join(text_parts)
        response_status = raw.get("status")
        status = (
            "truncated"
            if response_status == "incomplete"
            else "api_error"
            if response_status == "failed"
            else "ok"
        )
        if response_status not in ("completed", "incomplete", "failed"):
            status = "protocol_error"
        if refused:
            status = "refused"
        usage = raw.get("usage") or {}
        normalized = {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "reasoning_tokens": (usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
            "cached_input_tokens": (usage.get("input_tokens_details") or {}).get("cached_tokens"),
        }
    if tools:
        status = "protocol_violation"
    elif status == "ok" and not text.strip():
        status = "empty_response"
    return Response(
        text=text, status=status, usage=normalized, tools=tools, raw=raw, actual_model=raw.get("model")
    )


def call_api(case, target, timeout):
    endpoint, body = api_payload(case, target)
    key = os.environ.get(target.get("api_key_env", "OPENAI_API_KEY"))
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    start = time.monotonic()
    started_at = now()
    capture = None
    request_started_at = None
    response = Response(request=body)
    try:
        if target.get("stream"):
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                request_started_at = now()
                capture = StreamCapture(target["kind"], time.monotonic())
                with client.stream(
                    "POST", target["base_url"].rstrip("/") + endpoint, json=body, headers=headers
                ) as reply:
                    if reply.status_code != 200:
                        reply.read()
                        response.status = (
                            "rate_limit"
                            if reply.status_code == 429
                            else "server_error"
                            if reply.status_code >= 500
                            else "api_error"
                        )
                        response.error = f"HTTP {reply.status_code}"
                        response.raw = {"http_status": reply.status_code, "body": reply.text[:32000]}
                    elif "text/event-stream" not in reply.headers.get("content-type", "").lower():
                        reply.read()
                        response.raw = {"http_status": reply.status_code, "body": reply.text[:32000]}
                        response.status, response.error = (
                            "protocol_error",
                            "stream:true requires text/event-stream; no fallback",
                        )
                    else:
                        capture.consume(reply.iter_lines())
                        response = capture.response(parse_api)
        else:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                reply = client.post(target["base_url"].rstrip("/") + endpoint, json=body, headers=headers)
            if reply.status_code >= 400 or reply.status_code < 200 or reply.status_code >= 300:
                response.status = (
                    "rate_limit"
                    if reply.status_code == 429
                    else "server_error"
                    if reply.status_code >= 500
                    else "api_error"
                )
                response.error = f"HTTP {reply.status_code}"
                response.raw = {"http_status": reply.status_code, "body": reply.text[:32000]}
            else:
                try:
                    response = parse_api(reply.json(), target["kind"])
                except ValueError:
                    response.status = "protocol_error"
                    response.error = "响应不是有效 JSON（未切换协议或重试）"
                    response.raw = {"http_status": reply.status_code, "body": reply.text[:32000]}
    except httpx.TimeoutException as exc:
        response.status, response.error = "timeout", str(exc)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        response.status, response.error = "protocol_error", str(exc)
    if capture is not None and capture.events and not response.stream:
        partial = capture.response(parse_api)
        partial.status, partial.error = response.status, response.error
        response = partial
    if not response.stream:
        response.stream = unavailable_stream("no_stream_events" if target.get("stream") else "non_streaming")
    response.stream["request_started_at"] = request_started_at
    response.elapsed = time.monotonic() - start
    response.timing = {"started_at": started_at, "finished_at": now(), "elapsed_seconds": response.elapsed}
    response.request = body
    return response


def run_process(args, prompt="", cwd=None, timeout=300, env=None):
    """No shell; on timeout kill the process group, including agent child commands."""
    proc = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(prompt, timeout=timeout)
        return proc.returncode, stdout, stderr, False
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        stdout, stderr = proc.communicate()
        return proc.returncode, stdout, stderr, True


def codex_connection(target):
    """Carry only connection/model fields across --ignore-user-config, never user instructions/hooks."""
    path = Path.home() / ".codex/config.toml"
    conf = tomllib.loads(path.read_text()) if path.exists() else {}
    provider = target.get("codex_provider") or conf.get("model_provider")
    model = target.get("model") or conf.get("model")
    overrides = []
    if provider:
        overrides.extend(["-c", "model_provider=" + json.dumps(provider)])
        spec = conf.get("model_providers", {}).get(provider, {})
        if spec.get("http_headers"):
            raise ValueError(
                "受控 Codex 不复制 http_headers 凭据；请使用 provider 的 env_key 或现有 CLI 登录"
            )
        allowed = ("name", "base_url", "env_key", "wire_api", "requires_openai_auth", "supports_websockets")
        for k in allowed:
            if k in spec:
                overrides.extend(["-c", f"model_providers.{provider}.{k}=" + json.dumps(spec[k])])
    return model, overrides


def cli_preflight(target, mode):
    kind = target["kind"]
    exe = shutil.which(target.get("executable", kind))
    if not exe:
        raise ValueError(f"找不到 {kind}，请先安装并登录")
    _, version, _, _ = run_process([exe, "--version"], timeout=20)
    _, help_text, _, _ = run_process(
        [exe, "exec", "--help"] if kind == "codex" else [exe, "--help"], timeout=20
    )
    required = (
        ["--json", "--ephemeral"] if kind == "codex" else ["--output-format", "--no-session-persistence"]
    )
    if mode == "controlled":
        required += (
            ["--ignore-user-config"] if kind == "codex" else ["--safe-mode", "--tools", "--strict-mcp-config"]
        )
    missing = [flag for flag in required if flag not in help_text]
    if missing:
        raise ValueError(f"{kind} 不支持所需限制: {', '.join(missing)}")
    if kind == "codex" and mode == "controlled":
        _, features, _, _ = run_process([exe, "features", "list"], timeout=20)
        required_features = ("shell_tool", "unified_exec", "memories", "apps", "plugins", "multi_agent")
        missing = [
            f
            for f in required_features
            if f not in {line.split()[0] for line in features.splitlines() if line.split()}
        ]
        if missing:
            raise ValueError(f"Codex 版本缺少受控模式特性: {missing}")
    unsupported = [k for k in ("temperature", "top_p", "seed") if target.get(k) is not None]
    if unsupported:
        raise ValueError(f"CLI 不支持参数 {unsupported}；不会静默忽略")
    return {
        "executable": exe,
        "version": version.strip(),
        "mode": mode,
        "system_note": "CLI 内建/托管系统提示未必可完全移除；不是 API 裸模型等价环境",
    }


def cli_command(target, mode, temp, identity):
    exe = identity["executable"]
    if target["kind"] == "codex":
        args = [
            exe,
            "exec",
            "--json",
            "--ephemeral",
            "--skip-git-repo-check",
            "--color",
            "never",
            "-s",
            "read-only",
            "-c",
            'approval_policy="never"',
            "-C",
            temp,
        ]
        model = target.get("model")
        if mode == "controlled":
            model, connection = codex_connection(target)
            args += [
                "--ignore-user-config",
                "--ignore-rules",
                *connection,
                "-c",
                'web_search="disabled"',
                "-c",
                "project_doc_max_bytes=0",
            ]
            for feature in ("shell_tool", "unified_exec", "memories", "apps", "plugins", "multi_agent"):
                args += ["--disable", feature]
        if model:
            args += ["-m", model]
        if target.get("reasoning_effort"):
            args += ["-c", "model_reasoning_effort=" + json.dumps(target["reasoning_effort"])]
        args += ["-"]
    else:
        args = [exe, "--print", "--output-format", "stream-json", "--verbose", "--no-session-persistence"]
        if mode == "controlled":
            args += [
                "--safe-mode",
                "--tools",
                "",
                "--strict-mcp-config",
                "--mcp-config",
                '{"mcpServers":{}}',
                "--disable-slash-commands",
            ]
        if target.get("model"):
            args += ["--model", target["model"]]
        if target.get("reasoning_effort"):
            args += ["--effort", target["reasoning_effort"]]
    return args


def parse_cli(stdout, stderr, code, timed_out, kind, mode, is_fingerprint=False):
    events, malformed = [], []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            malformed.append(line[:500])
    text, usage, model, tools, completed = "", {}, None, [], False
    status, error = "ok", None
    for event in events:
        if kind == "codex":
            if event.get("type") == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "agent_message":
                    text = item.get("text", text)
                elif item.get("type") not in ("reasoning",):
                    tools.append(item)
            elif event.get("type") == "turn.completed":
                completed = True
                u = event.get("usage") or {}
                usage = {
                    "input_tokens": u.get("input_tokens"),
                    "output_tokens": u.get("output_tokens"),
                    "reasoning_tokens": u.get("reasoning_output_tokens"),
                    "cached_input_tokens": u.get("cached_input_tokens"),
                }
            elif event.get("type") in ("turn.failed", "error"):
                status, error = "cli_error", json.dumps(event, ensure_ascii=False)
        else:
            if event.get("type") == "assistant":
                message = event.get("message", {})
                model = message.get("model", model)
                for content in message.get("content", []):
                    if content.get("type") == "text":
                        text = content.get("text", text)
                    elif content.get("type") == "tool_use":
                        tools.append(content)
                if message.get("stop_reason") == "max_tokens":
                    status = "truncated"
                elif message.get("stop_reason") == "refusal":
                    status = "refused"
            elif event.get("type") == "result":
                completed = True
                text = event.get("result", text)
                u = event.get("usage") or {}
                usage = {
                    "input_tokens": u.get("input_tokens"),
                    "output_tokens": u.get("output_tokens"),
                    "cached_input_tokens": u.get("cache_read_input_tokens"),
                    "cache_creation_input_tokens": u.get("cache_creation_input_tokens"),
                    "reported_cost_usd": event.get("total_cost_usd"),
                }
                if event.get("stop_reason") == "max_tokens":
                    status = "truncated"
                elif event.get("stop_reason") == "refusal":
                    status, error = "refused", text
                elif event.get("is_error"):
                    status, error = (
                        "cli_error",
                        str(event.get("errors") or event.get("terminal_reason") or event.get("subtype")),
                    )
    if timed_out:
        status, error = "timeout", "CLI 超时；已终止进程组"
    elif code and status not in ("refused", "truncated"):
        status, error = "cli_error", stderr[-8000:] or error or f"exit {code}"
    elif not completed or malformed:
        status, error = "protocol_error", "缺少完成事件或包含非 JSON 输出"
    elif status == "ok" and not text.strip():
        status = "empty_response"
    if tools and (mode == "controlled" or is_fingerprint):
        status = "protocol_violation"
    return Response(
        text=text,
        status=status,
        usage=usage,
        actual_model=model,
        tools=tools,
        error=error,
        raw={"events": events, "stderr": stderr, "non_json": malformed, "exit_code": code},
    )


def call_cli(case, target, mode, timeout, identity):
    start = time.monotonic()
    started_at = now()
    with tempfile.TemporaryDirectory(
        prefix="dummy-llm-test-", dir="/private/tmp" if Path("/private/tmp").exists() else None
    ) as temp:
        args = cli_command(target, mode, temp, identity)
        # Claude supports a per-invocation system prompt; Codex's developer layer is separate.
        if case.system:
            if target["kind"] == "claude":
                args += ["--append-system-prompt", case.system]
            else:
                args[-1:-1] = ["-c", "developer_instructions=" + json.dumps(case.system)]
        env = dict(os.environ)
        if target["kind"] == "claude":
            env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(target.get("max_output_tokens", 8192))
        try:
            code, stdout, stderr, timed_out = run_process(
                args, case.prompt, cwd=temp, timeout=timeout, env=env
            )
            response = parse_cli(
                stdout, stderr, code, timed_out, target["kind"], mode, case.kind == "fingerprint"
            )
        except OSError as exc:
            response = Response(status="cli_error", error=str(exc))
        response.elapsed = time.monotonic() - start
        response.timing = {
            "started_at": started_at,
            "finished_at": now(),
            "elapsed_seconds": response.elapsed,
        }
        response.stream = unavailable_stream("cli_incremental_arrival_not_observed")
        response.request = {
            "argv": args,
            "stdin": case.prompt,
            "output_limit": target.get("max_output_tokens") if target["kind"] == "claude" else None,
            "output_limit_note": "Codex exec 未提供可验证的每次输出上限"
            if target["kind"] == "codex"
            else None,
        }
        return response
