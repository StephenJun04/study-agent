#!/usr/bin/env python3
"""Check local dependencies without printing secrets or generating by default."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_checks(probe_real: bool = False) -> tuple[dict, int]:
    from studyagent.config import Settings
    from studyagent.db import Database
    from studyagent.providers import Provider
    from studyagent.schemas import Answer

    report = {"database": {"connected": False}, "real_probe": {"status": "not_run"}}
    try:
        settings = Settings()
    except Exception as exc:
        report["configuration"] = {"status": "invalid", "error_type": type(exc).__name__}
        return report, 2

    provider = Provider(settings)
    report["provider"] = provider.health()
    report["mode"] = "deterministic_fake" if settings.provider == "fake" else "real_deepseek"
    try:
        row = Database(settings).one("SELECT 1 AS ok")
        report["database"] = {"connected": bool(row and row["ok"] == 1), "backend": "PostgreSQL"}
    except Exception as exc:
        # Driver errors may include credentials or addresses; never serialize them.
        report["database"]["error_type"] = type(exc).__name__

    ready = report["provider"].get("ready", False) and report["database"]["connected"]
    code = 0 if ready else 1
    if settings.provider == "deepseek" and not report["provider"].get("configured", False):
        code = 2
        report["real_probe"]["reason"] = "DEEPSEEK_API_KEY is not configured; no generation requested."
    elif probe_real and settings.provider != "deepseek":
        code = 2
        report["real_probe"]["reason"] = "--probe-real requires STUDYAGENT_PROVIDER=deepseek."
    elif probe_real and not ready:
        report["real_probe"]["reason"] = "Dependencies are not ready; no generation requested."
    elif probe_real:
        try:
            vectors = provider.embed(["A triangle has three sides."])
            provider.complete("answer", {
                "question": "How many sides does a triangle have? Use the supplied evidence.",
                "evidence": [{"id": "preflight-1", "text": "A triangle has three sides."}],
            }, Answer)
            report["real_probe"] = {
                "status": "passed", "embedding_count": len(vectors),
                "embedding_dimension": len(vectors[0]), "structured_generation": True,
                "answer_quality_assessed": False,
            }
        except Exception as exc:
            report["real_probe"] = {"status": "failed", "error_type": type(exc).__name__}
            code = 1
    else:
        report["real_probe"]["reason"] = "Not requested; health checks do not verify DeepSeek authentication."
    report["ready_for_requested_checks"] = code == 0
    return report, code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-real", action="store_true",
                        help="Explicitly run a local embedding and a real DeepSeek completion (may incur cost).")
    args = parser.parse_args()
    report, code = run_checks(args.probe_real)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
