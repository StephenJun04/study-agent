#!/usr/bin/env python3
"""Fetch two public demo PDFs (or --all), validate them, and record their hashes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MAX_BYTES = 20 * 1024 * 1024
DOWNLOAD_SECONDS = 90
ALLOWED_HOSTS = {"arxiv.org", "export.arxiv.org"}


def allowed_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password:
        raise ValueError("Only public HTTPS arXiv URLs are allowed.")
    if parsed.port not in (None, 443):
        raise ValueError("Unexpected download port.")
    return url


def inspect_pdf(path: Path) -> dict:
    import pymupdf

    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("PDF is empty or exceeds the 20 MiB limit.")
    data = path.read_bytes()
    if b"%PDF-" not in data[:1024]:
        raise ValueError("Response is not a PDF.")
    with pymupdf.open(stream=data, filetype="pdf") as document:
        if document.needs_pass or not document.page_count:
            raise ValueError("PDF is encrypted or has no pages.")
        characters = sum(len(re.sub(r"\s", "", page.get_text())) for page in document)
        if not 40 <= characters <= 500_000:
            raise ValueError("Extractable PDF text is outside the app's 40–500,000 character range.")
        pages = document.page_count
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "pages": pages,
            "text_characters": characters}


def download_pdf(client, url: str, destination: Path) -> str:
    deadline = time.monotonic() + DOWNLOAD_SECONDS
    current = allowed_url(url)
    for _ in range(5):
        if time.monotonic() >= deadline:
            raise TimeoutError("Download exceeded its time limit.")
        with client.stream("GET", current) as response:
            if response.is_redirect:
                current = allowed_url(urljoin(current, response.headers["location"]))
                continue
            response.raise_for_status()
            length = response.headers.get("content-length")
            if length and int(length) > MAX_BYTES:
                raise ValueError("Download exceeds the 20 MiB limit.")
            total = 0
            with destination.open("wb") as output:
                for chunk in response.iter_bytes(chunk_size=64 * 1024):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Download exceeded its time limit.")
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ValueError("Download exceeds the 20 MiB limit.")
                    output.write(chunk)
            return current
    raise ValueError("Too many download redirects.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Fetch all entries in data/sources.json (default: transformer, rag).")
    args = parser.parse_args()
    import httpx

    manifest_source = json.loads((ROOT / "data/sources.json").read_text(encoding="utf-8"))
    selected = [item for item in manifest_source["documents"]
                if args.all or item["id"] in {"transformer", "rag"}]
    output_dir = ROOT / "runtime/materials"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    previous = {}
    if manifest_path.exists():
        previous = {item["id"]: item for item in json.loads(manifest_path.read_text())["documents"]}
    records = []
    with httpx.Client(timeout=httpx.Timeout(15, connect=10), follow_redirects=False,
                      trust_env=False, headers={"User-Agent": "StudyAgent-local-demo/0.1"}) as client:
        for item in selected:
            record = {"id": item["id"], "title": item["title"], "source_url": item["source_url"],
                      "download_url": item["download_url"], "initial_space": item["initial_space"],
                      "checked_at": datetime.now(timezone.utc).isoformat(),
                      "version_pinned": bool(re.search(r"v\d+$", item.get("arxiv_id", "")))}
            temporary = None
            try:
                if not re.fullmatch(r"[a-z0-9_-]+", item["id"]):
                    raise ValueError("Invalid material ID.")
                target = output_dir / f"{item['id']}.pdf"
                if target.exists():
                    record.update(inspect_pdf(target), status="reused")
                    prior = previous.get(item["id"], {})
                    if prior.get("sha256") == record["sha256"]:
                        for field in ("downloaded_at", "resolved_url"):
                            if field in prior:
                                record[field] = prior[field]
                else:
                    with tempfile.NamedTemporaryFile(dir=output_dir, suffix=".part", delete=False) as handle:
                        temporary = Path(handle.name)
                    record["resolved_url"] = download_pdf(client, item["download_url"], temporary)
                    record.update(inspect_pdf(temporary), status="downloaded")
                    record["downloaded_at"] = datetime.now(timezone.utc).isoformat()
                    temporary.replace(target)
                record["file"] = target.relative_to(ROOT).as_posix()
            except Exception as exc:
                record.update(status="failed", error_type=type(exc).__name__)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            records.append(record)
            print(f"{item['id']}: {record['status']}")
    previous.update({item["id"]: item for item in records})
    manifest = {"source_manifest": "data/sources.json", "documents": list(previous.values()),
                "note": "SHA-256 identifies downloaded bytes; unversioned arXiv URLs may change. Downloading is not human annotation or evaluation."}
    pending = manifest_path.with_suffix(".json.tmp")
    pending.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(manifest_path)
    print("Manifest: runtime/materials/manifest.json")
    return int(any(item["status"] == "failed" for item in records))


if __name__ == "__main__":
    raise SystemExit(main())
