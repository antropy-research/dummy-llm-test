from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).parent
DATA = PACKAGE / "data"


def digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def grading_hash():
    return digest({name: (PACKAGE / name).read_text() for name in ("scoring.py", "adapters.py")})


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


@dataclass
class Case:
    id: str
    suite: str
    prompt: str
    kind: str = "exact"
    expected: Any = None
    system: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def hash(self):
        return digest(asdict(self))

    def to_dict(self):
        return asdict(self)


@dataclass
class Response:
    text: str = ""
    status: str = "ok"
    usage: dict = field(default_factory=dict)
    elapsed: float = 0.0
    raw: Any = None
    error: str | None = None
    tools: list = field(default_factory=list)
    actual_model: str | None = None
    request: dict = field(default_factory=dict)


def wilson(correct: int, total: int):
    if not total:
        return None
    z = 1.95996398454
    p = correct / total
    center = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return [max(0, center - half), min(1, center + half)]


def scrub(value, secrets=()):
    """Redact configured secrets in all persisted strings, including provider errors."""
    if isinstance(value, dict):
        return {
            k: (
                "[REDACTED]"
                if re.search(r"(?i)(authorization|api.?key|access_token|auth_token|password|secret)$", k)
                and not k.endswith("_env")
                else scrub(v, secrets)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [scrub(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED]", value)
    return value
