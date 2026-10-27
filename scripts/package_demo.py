#!/usr/bin/env python3
"""Build a local demo snapshot from a strict source allowlist; never include runtime data."""

from hashlib import sha256
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = (".env.example", ".gitignore", "README.md", "compose.yaml", "pyproject.toml", "requirements.lock")
DIRECTORIES = ("studyagent", "migrations", "prompts", "docs", "data", "tests", "scripts", "evaluation")
SUFFIXES = {".py", ".sql", ".txt", ".md", ".json", ".xml", ".png", ".html", ".css", ".js"}
SKIP = {"__pycache__", ".pytest_cache", ".ruff_cache", ".DS_Store"}


def main():
    files = [ROOT / name for name in TOP_FILES]
    for directory in DIRECTORIES:
        files.extend(
            p for p in (ROOT / directory).rglob("*")
            if p.is_file() and p.suffix in SUFFIXES and not SKIP.intersection(p.parts)
        )
    payloads = {}
    for path in sorted(files):
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError("Refusing a source link outside the snapshot.")
        relative = path.relative_to(ROOT).as_posix()
        payloads[relative] = path.read_bytes()
    hashes = {name: sha256(data).hexdigest() for name, data in payloads.items()}
    canonical = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    manifest = {
        "scope": "local demo; not a complete course submission",
        "version_method": "SHA-256 of canonical sorted per-file SHA-256 map",
        "snapshot_sha256": sha256(canonical).hexdigest(),
        "files": hashes,
        "excluded": [".env", "credentials", "runtime uploads", "database dumps", "original coursework", "virtualenv", ".git"],
    }
    payloads["VERSION.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    output = ROOT / "output"
    output.mkdir(exist_ok=True)
    archive = output / "StudyAgent-demo.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for name, content in payloads.items():
            info = zipfile.ZipInfo("studyagent-demo/" + name, date_time=(2026, 10, 27, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zipped.writestr(info, content)
    digest = sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(digest + "  " + archive.name + "\n")
    print(json.dumps({"archive": str(archive), "source_files": len(hashes), "zip_sha256": digest,
                      "snapshot_sha256": manifest["snapshot_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
