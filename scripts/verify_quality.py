"""Repeatable quality gate. No daemon, schedule, credentials, or real-account writes."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
BACKEND_TESTS = [
    "test_agent_evaluation.py",
    "test_answer_quality_evaluation.py",
    "test_photo_quality_evaluation.py",
    "test_agent_multiturn_pipeline.py",
    "test_agent_language_boundaries.py",
    "test_meal_date_change.py",
    "test_confirmation_expiry_recovery.py",
    "test_agent_graph_nodes.py",
    "test_agent_response_synthesizer.py",
    "test_agent_reliability_increment.py",
    "test_food_photo_quality.py",
    "test_food_image_recognizer.py",
    "test_nutrition_image_route.py",
    "test_nutrition_image_draft_estimator.py",
    "test_nutrition_draft_calculator.py",
    "test_agent_service_vision.py",
    "test_nutrition_record_draft_branch_handler.py",
]


def junit_summary(path):
    if not path.is_file():
        return {
            "tests": 0,
            "passed": 0,
            "failed": ["missing-test-report"],
            "skipped": 0,
        }
    cases = list(ET.parse(path).getroot().iter("testcase"))
    failures, skipped = [], 0
    for case in cases:
        if case.find("failure") is not None or case.find("error") is not None:
            failures.append(f"{case.get('classname')}::{case.get('name')}")
        elif case.find("skipped") is not None:
            skipped += 1
    return {
        "tests": len(cases),
        "passed": len(cases) - len(failures) - skipped,
        "failed": failures,
        "skipped": skipped,
    }


def fingerprint():
    digest = hashlib.sha256()
    for folder in [ROOT / "backend/src", ROOT / "frontend/lib"]:
        for path in sorted(folder.rglob("*")):
            if (
                path.suffix not in {".py", ".dart", ".json"}
                or "__pycache__" in path.parts
            ):
                continue
            digest.update(str(path.relative_to(ROOT)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def run_step(name, command, cwd, output, environment, timeout):
    print(f"[quality] {name}", flush=True)
    started = time.monotonic()
    with (output / f"{name}.log").open("w", encoding="utf-8") as log:
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
        except OSError:
            code = 127
    return {
        "name": name,
        "exit_code": code,
        "passed": code == 0,
        "seconds": round(time.monotonic() - started, 3),
        "log": f"{name}.log",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use configured text/vision providers with a disposable account",
    )
    parser.add_argument(
        "--samples",
        type=Path,
        help="Explicitly consented meal-image manifest; requires --live",
    )
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument(
        "--database",
        action="store_true",
        help="Also run disposable real-database record and account regressions",
    )
    parser.add_argument(
        "--flutter",
        default=shutil.which("flutter") or "D:/develop/flutter/bin/flutter.bat",
    )
    parser.add_argument(
        "--baseline", type=Path, help="Previous report.json for failure comparison"
    )
    args = parser.parse_args()
    if args.samples and not args.live:
        parser.error(
            "--samples requires --live; images are never submitted by a regression-only run"
        )
    if args.samples and not args.samples.is_file():
        parser.error("sample manifest is unavailable")
    stamp = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    output = ROOT / ".local/quality-runs" / stamp
    output.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ, PYTHONIOENCODING="utf-8")
    python = ROOT / (
        "backend/.venv/Scripts/python.exe"
        if os.name == "nt"
        else "backend/.venv/bin/python"
    )
    pytest = [
        str(python),
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        str(output / "pytest-tmp"),
    ]
    steps = [
        run_step(
            "backend-regression",
            [
                *pytest,
                *["tests/" + p for p in BACKEND_TESTS],
                "--junitxml",
                str(output / "backend.xml"),
            ],
            ROOT / "backend",
            output,
            environment,
            180,
        )
    ]
    steps[0]["tests"] = junit_summary(output / "backend.xml")
    steps[0]["passed"] &= steps[0]["tests"]["passed"] > 0
    if not args.backend_only:
        steps.append(
            run_step(
                "flutter-tests",
                [
                    args.flutter,
                    "--no-version-check",
                    "test",
                    "--no-pub",
                    "--reporter",
                    "expanded",
                ],
                ROOT / "frontend",
                output,
                environment,
                240,
            )
        )
        steps.append(
            run_step(
                "flutter-analyze",
                [args.flutter, "--no-version-check", "analyze", "--no-pub"],
                ROOT / "frontend",
                output,
                environment,
                180,
            )
        )
    if args.database:
        environment["RUN_DATABASE_TESTS"] = "1"
        step = run_step(
            "database-records",
            [
                *pytest,
                "tests/test_offline_records_database.py",
                "tests/test_water_database.py",
                "tests/test_workout_controls_database.py",
                "tests/test_account_security_database.py",
                "tests/test_profile_weight_database_integration.py",
                "--junitxml",
                str(output / "database.xml"),
            ],
            ROOT / "backend",
            output,
            environment,
            180,
        )
        step["tests"] = junit_summary(output / "database.xml")
        step["passed"] &= step["tests"]["passed"] > 0
        steps.append(step)
    live_rows = []
    if args.live:
        environment.update(
            RUN_CONTINUOUS_QUALITY_LIVE="1",
            RUN_LIVE_AGENT_TESTS="1",
            QUALITY_REPEATS=str(args.repeats),
            QUALITY_EVIDENCE_PATH=str(output / "live-evidence.json"),
        )
        if args.samples:
            environment["QUALITY_PHOTO_MANIFEST"] = str(args.samples.resolve())
        else:
            environment.pop("QUALITY_PHOTO_MANIFEST", None)
        step = run_step(
            "live-quality",
            [
                *pytest,
                "tests/test_continuous_quality_live.py",
                "--junitxml",
                str(output / "live.xml"),
            ],
            ROOT / "backend",
            output,
            environment,
            600,
        )
        step["tests"] = junit_summary(output / "live.xml")
        step["passed"] &= step["tests"]["passed"] == 2 and step["tests"]["skipped"] == 0
        steps.append(step)
        path = output / "live-evidence.json"
        if path.exists():
            live_rows = json.loads(path.read_text(encoding="utf-8"))
    report = {
        "version": 1,
        "run_id": stamp,
        "source_sha256": fingerprint(),
        "passed": all(step["passed"] for step in steps),
        "steps": steps,
        "live_requested": args.live,
        "live_cases": live_rows,
        "accuracy_coverage": {
            "known_portion_observations": sum(
                row.get("weighed_items", 0) for row in live_rows
            ),
            "calorie_reference_observations": sum(
                row.get("calorie_reference_items", 0) for row in live_rows
            ),
            "note": "No weighed or calorie truth means those accuracies are unmeasured, even when all gates pass.",
        },
    }
    groups = {}
    for row in live_rows:
        if "case_id" in row and "seconds" in row:
            groups.setdefault(row["case_id"], []).append(row["seconds"])
    report["latency_seconds"] = {
        key: {
            "observations": len(values),
            "min": min(values),
            "max": max(values),
            "mean": round(sum(values) / len(values), 3),
        }
        for key, values in groups.items()
    }
    digest = hashlib.sha256(Path(__file__).read_bytes())
    suite_files = [ROOT / "backend/tests" / name for name in BACKEND_TESTS]
    suite_files += [
        ROOT / "backend/tests/test_continuous_quality_live.py",
        ROOT / "backend/tests/test_offline_records_database.py",
    ]
    suite_files += sorted((ROOT / "frontend/test").rglob("*.dart"))
    suite_files += sorted((ROOT / "frontend/integration_test").rglob("*.dart"))
    for path in suite_files:
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    report["suite_sha256"] = digest.hexdigest()
    if args.baseline:
        previous = json.loads(args.baseline.read_text(encoding="utf-8"))
        old = {
            x
            for step in previous["steps"]
            for x in step.get("tests", {}).get("failed", [])
        }
        new = {x for step in steps for x in step.get("tests", {}).get("failed", [])}
        report["comparison"] = {
            "baseline_run": previous["run_id"],
            "new_failures": sorted(new - old),
            "resolved_failures": sorted(old - new),
        }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        f"# NxtRep quality {stamp}",
        "",
        f"Overall: {'PASS' if report['passed'] else 'FAIL'}",
        "",
        "| Check | Result | Seconds |",
        "| --- | --- | --- |",
    ]
    lines += [
        f"| {step['name']} | {'PASS' if step['passed'] else 'FAIL'} | {step['seconds']} |"
        for step in steps
    ]
    lines += [
        "",
        f"Live provider checks: {'executed' if args.live else 'not requested'}.",
        f"Known-portion observations: {report['accuracy_coverage']['known_portion_observations']}.",
        f"Calorie-reference observations: {report['accuracy_coverage']['calorie_reference_observations']}.",
        "Missing truth is unmeasured. Regression PASS is not a claim of meal-portion accuracy.",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{'PASS' if report['passed'] else 'FAIL'}: {output / 'report.md'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
