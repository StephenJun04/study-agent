#!/usr/bin/env python3
"""Run deterministic contract tests; keep real-model quality explicitly unmeasured."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read_cases(path: Path) -> list[dict]:
    if not path.exists():
        return []
    cases = []
    for item in ET.parse(path).iter("testcase"):
        status = "passed"
        for result in ("failure", "error", "skipped"):
            if item.find(result) is not None:
                status = {"failure": "failed", "error": "error", "skipped": "skipped"}[result]
                break
        module = item.get("classname", "")
        category = ("mocked_provider_and_context" if "test_providers_context" in module else
                    "deterministic_rules" if "test_learning" in module else
                    "deterministic_with_real_postgresql")
        cases.append({"name": item.get("name", ""), "module": module, "status": status,
                      "category": category, "seconds": float(item.get("time", "0"))})
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-real", action="store_true",
                        help="Also probe embedding + one DeepSeek completion using the current environment (may incur cost).")
    args = parser.parse_args()
    output_dir = ROOT / "evaluation/results"
    output_dir.mkdir(parents=True, exist_ok=True)
    xml_path = output_dir / "pytest.xml"
    xml_path.unlink(missing_ok=True)  # Never report an earlier run as the current result.
    environment = dict(os.environ, STUDYAGENT_PROVIDER="fake", DEEPSEEK_API_KEY="",
                       SEARCH_PROVIDER="disabled", USER_ID="evaluation-deterministic")
    started = time.monotonic()
    process = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests", "--junitxml", str(xml_path)],
                             cwd=ROOT, env=environment, check=False)
    deterministic_seconds = round(time.monotonic() - started, 3)
    cases = read_cases(xml_path)
    counts = {status: sum(case["status"] == status for case in cases)
              for status in ("passed", "failed", "error", "skipped")}
    scenarios = json.loads((ROOT / "evaluation/scenarios.json").read_text(encoding="utf-8"))
    coverage = []
    for scenario in scenarios["scenarios"]:
        matching = [case for case in cases if case["name"].split("[", 1)[0] == scenario["test"]]
        status = ("passed" if matching and all(case["status"] == "passed" for case in matching) else
                  "not_collected" if not matching else "not_passed")
        coverage.append({"id": scenario["id"], "name": scenario["name"],
                         "test": scenario["test"], "contract_test_status": status})
    real_probe = {"status": "not_run", "reason": "No explicit --probe-real request."}
    probe_exit = 0
    if args.probe_real:
        from preflight import run_checks
        checks, probe_exit = run_checks(probe_real=True)
        real_probe = dict(checks["real_probe"],
                          dependencies={key: checks[key] for key in ("provider", "database") if key in checks})
    report = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Deterministic workflow and contract verification; not model answer accuracy or learning outcomes.",
        "deterministic": {"status": "passed" if process.returncode == 0 else "failed",
                          "provider": "fake / explicit model doubles / mocked HTTP",
                          "database": "real PostgreSQL; tests create their own spaces",
                          "pytest_exit_code": process.returncode, "seconds": deterministic_seconds,
                          "counts": counts, "cases": cases, "scenarios": coverage},
        "real_service_probe": real_probe,
        "real_answer_quality": {"status": "not_run", "reason": "Requires fixed human-annotated questions and human review."},
        "baseline_comparison": {"status": "not_run", "scope": "Shared answer/citation capabilities only; baseline=true excludes mastery and preferences."},
        "human_review": "",
    }
    target = output_dir / "summary.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Results: evaluation/results/pytest.xml and evaluation/results/summary.json")
    print("Real answer quality and baseline comparison: not_run")
    return process.returncode or probe_exit


if __name__ == "__main__":
    raise SystemExit(main())
