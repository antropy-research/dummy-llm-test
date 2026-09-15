"""Offline checks for contributors and coding agents; never invoke an LLM."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]


def validate_repo(root):
    errors = []
    documents = list(root.glob("*.md")) + list((root / "docs").rglob("*.md"))
    skills = list((root / ".agents/skills").glob("*/SKILL.md"))
    for path in documents + skills:
        for link in re.findall(r"\]\(([^\s)]+)\)", path.read_text()):
            parsed = urlsplit(link)
            if parsed.scheme or not parsed.path:
                continue
            if not (path.parent / unquote(parsed.path)).exists():
                errors.append(f"{path.relative_to(root)}: missing link {link}")
    for path in skills:
        content = path.read_text()
        try:
            if not content.startswith("---\n"):
                raise ValueError("missing YAML frontmatter")
            metadata = yaml.safe_load(content.split("---", 2)[1])
            if not isinstance(metadata, dict) or metadata.get("name") != path.parent.name:
                raise ValueError("skill name must match directory")
            if not isinstance(metadata.get("description"), str) or not metadata["description"].strip():
                raise ValueError("missing skill description")
        except (ValueError, yaml.YAMLError) as exc:
            errors.append(f"{path.relative_to(root)}: {exc}")
    package = root / "src/dummy_llm_test"
    for source in json.loads((package / "data/sources.json").read_text()):
        local = source.get("local") or source.get("extracted_local")
        checksum = source.get("sha256") if source.get("local") else source.get("extracted_sha256")
        if local:
            path = package / local
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
                errors.append(f"source checksum mismatch: {local}")
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    match = re.search(r'__version__ = "([^"]+)"', (package / "__init__.py").read_text())
    if not match or match[1] != version:
        errors.append("package and project versions differ")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts-only", action="store_true", help="skip lint and pytest")
    args = parser.parse_args()
    errors = validate_repo(ROOT)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Repository links, skill metadata, source checksums, and version: OK", flush=True)
    if not args.contracts_only:
        for command in (
            [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"],
            [sys.executable, "-m", "pytest", "-q"],
        ):
            result = subprocess.run(command, cwd=ROOT, check=False)
            if result.returncode:
                return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
