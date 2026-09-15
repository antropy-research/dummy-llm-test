"""Inspect distribution members and bundled provenance without extracting archives."""

import argparse
import hashlib
import json
import tarfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path, PurePosixPath


def inspect_archive(path, version):
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            files = {n: archive.read(n) for n in archive.namelist() if not n.endswith("/")}
        prefix = "dummy_llm_test/"
        metadata = next((v for k, v in files.items() if k.endswith(".dist-info/METADATA")), None)
    else:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            if any(m.issym() or m.islnk() for m in members):
                raise ValueError("archive contains links")
            files = {m.name: archive.extractfile(m).read() for m in members if m.isfile()}
        root = f"dummy_llm_test-{version}/"
        prefix = root + "src/dummy_llm_test/"
        metadata = files.get(root + "PKG-INFO")
    for name in files:
        parts = PurePosixPath(name).parts
        if (
            name.startswith("/")
            or ".." in parts
            or any(
                p
                in {
                    "runs",
                    ".git",
                    ".venv",
                    "__pycache__",
                    ".pytest_cache",
                    ".ruff_cache",
                    "config.local.yaml",
                }
                or p.startswith(".env")
                or p.endswith(".pyc")
                for p in parts
            )
        ):
            raise ValueError(f"private/cache/unsafe archive path: {name}")
    if metadata is None:
        raise ValueError("missing package metadata")
    fields = Parser().parsestr(metadata.decode())
    if fields["Name"] != "dummy-llm-test" or fields["Version"] != version:
        raise ValueError("distribution name/version mismatch")
    if not fields.get_all("Project-URL") or not fields.get("Requires-Python"):
        raise ValueError("missing public metadata")
    notices = [v for k, v in files.items() if k.endswith("THIRD_PARTY_NOTICES.md")]
    if not notices or not any(b"BSD-3-Clause" in n for n in notices):
        raise ValueError("missing third-party notices")
    if not any(k.endswith("/LICENSE") for k in files):
        raise ValueError("missing harness license")
    for filename in ("cli.py", "contracts.py", "sharing.py"):
        if prefix + filename not in files:
            raise ValueError(f"missing installed module: {filename}")
    sources = json.loads(files[prefix + "data/sources.json"])
    for source in sources:
        local = source.get("local") or source.get("extracted_local")
        checksum = source.get("sha256") if source.get("local") else source.get("extracted_sha256")
        if local and hashlib.sha256(files[prefix + local]).hexdigest() != checksum:
            raise ValueError(f"bundled source checksum mismatch: {local}")
    licenses = [k for k in files if k.startswith(prefix + "data/licenses/")]
    if len(licenses) != 5:
        raise ValueError("expected five preserved upstream license files")
    return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    if args.version != project["version"]:
        parser.error("requested version differs from pyproject.toml")
    stem = "dummy_llm_test-" + args.version
    archives = [args.dist / (stem + "-py3-none-any.whl"), args.dist / (stem + ".tar.gz")]
    for archive in archives:
        count = inspect_archive(archive, args.version)
        print(f"{archive.name}: {count} files; metadata, privacy paths, sources and licenses OK")


if __name__ == "__main__":
    main()
