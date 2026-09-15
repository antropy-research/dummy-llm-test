import hashlib
import json
import runpy
import zipfile
from pathlib import Path

import pytest

validate_repo = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/check_repo.py"))[
    "validate_repo"
]


@pytest.fixture
def repository(tmp_path):
    package = tmp_path / "src/dummy_llm_test"
    (package / "data").mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "0.1.0"')
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.0"')
    raw = b"pinned source"
    (package / "data/source.txt").write_bytes(raw)
    (package / "data/sources.json").write_text(
        json.dumps(
            [
                {"local": "data/source.txt", "sha256": hashlib.sha256(raw).hexdigest()},
            ]
        )
    )
    return tmp_path


def test_contract_check_catches_missing_link_but_ignores_private_runs(repository):
    (repository / "README.md").write_text("[missing](docs/missing.md) [web](https://example.com)")
    (repository / "runs").mkdir()
    (repository / "runs/private.md").write_text("[private](anything.md)")
    errors = validate_repo(repository)
    assert len(errors) == 1 and "missing link" in errors[0]


def test_contract_check_catches_altered_source_and_version(repository):
    (repository / "src/dummy_llm_test/data/source.txt").write_text("changed")
    (repository / "pyproject.toml").write_text('[project]\nversion = "0.2.0"')
    errors = validate_repo(repository)
    assert len(errors) == 2
    assert any("checksum mismatch" in error for error in errors)
    assert any("versions differ" in error for error in errors)


def test_contract_check_rejects_invalid_skill_metadata(repository):
    skill = repository / ".agents/skills/example/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: wrong\ndescription: Example workflow.\n---\nContent")
    assert len(validate_repo(repository)) == 1
    skill.write_text("---\nname: example\ndescription: Example workflow.\n---\nContent")
    assert validate_repo(repository) == []


@pytest.mark.parametrize("name", ["runs/private.json", "pkg/.env", "pkg/config.local.yaml", "../escape"])
def test_distribution_check_rejects_private_or_unsafe_members(tmp_path, name):
    inspect_archive = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/check_dist.py"))[
        "inspect_archive"
    ]
    wheel = tmp_path / "unsafe.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(name, "synthetic private content")
    with pytest.raises(ValueError, match="private/cache/unsafe"):
        inspect_archive(wheel, "0.4.0")
