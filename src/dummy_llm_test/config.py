from __future__ import annotations

import copy
import math
import os
from pathlib import Path
from urllib.parse import urlsplit

import yaml

DEFAULT = {
    "default_target": "codex",
    "seed": 42,
    "concurrency": 1,
    "progress_interval": 10,
    "repetitions": 1,
    "timeout": 300,
    "retries": 0,
    "mode": "controlled",
    "output_dir": "runs",
    "levels": {
        "quick": {
            "cases": [
                "candy.original",
                "svg.pelican-original",
                "diagnostic.cutoff-zh",
                "basic.decimal",
                "basic.strawberry",
            ]
        },
        "full": {"suites": ["*"]},
        "fingerprint": {"suites": ["modeltrace"]},
    },
    "targets": {
        "codex": {"kind": "codex", "model": None, "max_output_tokens": 8192},
        "claude": {"kind": "claude", "model": None, "max_output_tokens": 8192},
        "api": {
            "kind": "chat_completions",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "model": "SET_MODEL",
            "max_output_tokens": 8192,
        },
    },
}


def merge(base, override):
    result = copy.deepcopy(base)
    for k, v in override.items():
        result[k] = merge(result[k], v) if isinstance(v, dict) and isinstance(result.get(k), dict) else v
    return result


def load_config(path: Path | None = None):
    path = path or (Path("config.local.yaml") if Path("config.local.yaml").exists() else Path("config.yaml"))
    if not path.exists() and path.name not in ("config.yaml", "config.local.yaml"):
        raise ValueError(f"配置文件不存在: {path}")
    try:
        data = yaml.safe_load(path.read_text()) if path.exists() else {}
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML 配置解析失败: {exc}") from exc
    if not isinstance(data or {}, dict):
        raise ValueError("配置必须是 YAML 对象")
    config = merge(DEFAULT, data or {})
    allowed = set(DEFAULT) | {
        "cost_limit_usd",
        "bank",
        "challenges",
        "custom_cases",
        "disabled_suites",
        "disabled_cases",
    }
    if set(config) - allowed:
        raise ValueError(f"未知配置项: {sorted(set(config) - allowed)}")
    for key in ("concurrency", "repetitions", "timeout", "progress_interval"):
        if not isinstance(config[key], int) or isinstance(config[key], bool) or config[key] < 1:
            raise ValueError(f"{key} 必须是正整数")
    if not isinstance(config["retries"], int) or not 0 <= config["retries"] <= 5:
        raise ValueError("retries 必须为 0..5")
    if config["mode"] not in ("controlled", "native"):
        raise ValueError("mode 必须为 controlled/native")
    if not isinstance(config["seed"], int):
        raise ValueError("seed 必须为整数")
    if not isinstance(config["targets"], dict) or not isinstance(config["levels"], dict):
        raise ValueError("targets 和 levels 必须是对象")
    for name, spec in config["levels"].items():
        if not isinstance(spec, dict) or set(spec) - {"cases", "suites", "repetitions"}:
            raise ValueError(f"level {name} 包含未知配置项")
        for field in ("cases", "suites"):
            if field in spec and (
                not isinstance(spec[field], list) or not all(isinstance(s, str) for s in spec[field])
            ):
                raise ValueError(f"level {name} 的 {field} 必须是字符串列表")
    for key in ("custom_cases", "disabled_cases", "disabled_suites"):
        if key in config and (
            not isinstance(config[key], list) or not all(isinstance(s, str) for s in config[key])
        ):
            raise ValueError(f"{key} 必须是字符串列表")
    for name, target in config["targets"].items():
        validate_target(name, target)
    return config


def validate_target(name, target):
    allowed = {
        "kind",
        "model",
        "base_url",
        "api_key_env",
        "max_output_tokens",
        "reasoning_effort",
        "temperature",
        "top_p",
        "seed",
        "input_price_per_million",
        "output_price_per_million",
        "executable",
        "codex_provider",
        "chat_token_field",
        "concurrency",
    }
    if not isinstance(target, dict) or set(target) - allowed:
        raise ValueError(f"目标 {name} 包含未知配置项")
    if target.get("kind") not in ("chat_completions", "responses", "codex", "claude"):
        raise ValueError(f"目标 {name} 的 kind 不支持")
    if "concurrency" in target and (
        not isinstance(target["concurrency"], int)
        or isinstance(target["concurrency"], bool)
        or target["concurrency"] < 1
    ):
        raise ValueError(f"目标 {name} 的 concurrency 必须是正整数")
    for key in ("api_key_env", "model", "base_url", "executable", "codex_provider"):
        if target.get(key) is not None and not isinstance(target[key], str):
            raise ValueError(f"目标 {name} 的 {key} 必须是字符串")
    if (
        not isinstance(target.get("max_output_tokens", 8192), int)
        or target.get("max_output_tokens", 8192) < 1
    ):
        raise ValueError("max_output_tokens 必须是正整数")
    if target.get("base_url"):
        url = urlsplit(target["base_url"])
        if (
            url.scheme not in ("https", "http")
            or not url.netloc
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("base_url 必须是无凭据、查询参数和片段的 HTTP(S) URL")
    for key in ("input_price_per_million", "output_price_per_million"):
        if key in target and (
            not isinstance(target[key], (int, float)) or not math.isfinite(target[key]) or target[key] < 0
        ):
            raise ValueError(f"{key} 必须是非负数")


def secret_values(config):
    names = {t.get("api_key_env") for t in config["targets"].values()}
    names |= {k for k in os.environ if any(x in k for x in ("API_KEY", "AUTH_TOKEN", "ACCESS_TOKEN"))}
    return [os.environ[k] for k in names if k and os.environ.get(k)]
