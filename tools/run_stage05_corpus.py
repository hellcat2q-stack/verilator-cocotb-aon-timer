"""Run the frozen Stage 05 functional corpus sequentially and retain each attempt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from stage05_corpus import DEFAULT_FREEZE_PATH, DEFAULT_POOL_PATH, PINNED_REVISION, load_frozen_pool, sha256_file
except ModuleNotFoundError:  # Support importing this file as tools.run_stage05_corpus in unit tests.
    from tools.stage05_corpus import DEFAULT_FREEZE_PATH, DEFAULT_POOL_PATH, PINNED_REVISION, load_frozen_pool, sha256_file


ROOT = Path(__file__).resolve().parents[1]


def parse_results_xml(path: Path) -> tuple[list[dict[str, Any]], float]:
    if not path.is_file():
        return [], 0.0
    root = ET.parse(path).getroot()
    cases = []
    total_ns = 0.0
    for case in root.findall(".//testcase"):
        failure = case.find("failure")
        error = case.find("error")
        result = "FAIL" if failure is not None or error is not None else "PASS"
        cases.append({
            "name": case.get("name", "unknown"),
            "result": result,
            "simulation_time_ns": float(case.get("sim_time_ns", "0")),
        })
        total_ns += float(case.get("sim_time_ns", "0"))
    return cases, total_ns


def current_source_revision(source_root: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True
    ).strip()


def run(args: argparse.Namespace) -> int:
    pool, freeze, pool_hash = load_frozen_pool(args.pool, args.freeze)
    source_root = args.source_root.resolve()
    python_env = args.python_env.resolve()
    work_root = args.work_root.resolve()

    actual_revision = current_source_revision(source_root)
    if actual_revision != PINNED_REVISION:
        raise ValueError(f"SOURCE_ROOT is {actual_revision}; expected {PINNED_REVISION}")
    for executable in (python_env / "bin" / "fusesoc", python_env / "bin" / "cocotb-config"):
        if not executable.is_file():
            raise FileNotFoundError(f"missing stage02/stage04 Python environment command: {executable.name}")
    if shutil.which("verilator") is None or shutil.which("make") is None:
        raise FileNotFoundError("verilator and make must be available on PATH")

    if args.dry_run:
        print(json.dumps({
            "freeze_id": freeze["freeze_id"],
            "pool_id": pool["pool_id"],
            "pool_sha256": pool_hash,
            "source_revision": actual_revision,
            "seed_list": pool["seed_list"],
            "suite_runs": pool["budget"]["suite_runs"],
            "testcases": [case["name"] for case in pool["testcases"]],
        }, indent=2))
        return 0

    work_root.mkdir(parents=True, exist_ok=True)
    attempts = []
    timeout_seconds = pool["budget"]["wall_clock_timeout_seconds_per_run"]

    for seed in pool["seed_list"]:
        run_id = f"{freeze['freeze_id']}-seed{seed}"
        run_root = work_root / run_id
        run_root.mkdir(parents=True, exist_ok=False)
        env = os.environ.copy()
        env.update({
            "SOURCE_ROOT": str(source_root),
            "PYTHON_ENV": str(python_env),
            "WORK_ROOT": str(run_root),
            "RANDOM_SEED": str(seed),
            "RUN_ID": run_id,
            "AON_TIMER_TEST_POOL": str(args.pool.resolve()),
        })
        command = [
            "timeout", "--signal=TERM", "--kill-after=10s", f"{timeout_seconds}s",
            "bash", str(ROOT / "tools" / "run_stage04_tests.sh"),
        ]
        print(f"[{run_id}] running frozen pool {pool['pool_id']}", flush=True)
        try:
            completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
            shell_exit_code = completed.returncode
        except OSError as exc:
            shell_exit_code = 127
            (run_root / "launcher_error.txt").write_text(str(exc) + "\n", encoding="utf-8")

        runner_manifest_path = run_root / "run_manifest.json"
        runner_manifest = {}
        if runner_manifest_path.is_file():
            runner_manifest = json.loads(runner_manifest_path.read_text(encoding="utf-8"))
        results_path = run_root / "results.xml"
        testcase_results, total_sim_ns = parse_results_xml(results_path)
        passed = (
            shell_exit_code == 0
            and runner_manifest.get("result") == "PASS"
            and [test["name"] for test in testcase_results]
            == [case["name"] for case in pool["testcases"]]
            and all(test["result"] == "PASS" for test in testcase_results)
            and runner_manifest.get("source_revision") == PINNED_REVISION
            and total_sim_ns <= pool["budget"]["simulation_time_limit_ns_per_suite"]
        )
        attempt = {
            "run_id": run_id,
            "seed": seed,
            "result": "PASS" if passed else "FAIL",
            "shell_exit_code": shell_exit_code,
            "tests_run": len(testcase_results),
            "tests_passed": sum(test["result"] == "PASS" for test in testcase_results),
            "tests_failed": sum(test["result"] == "FAIL" for test in testcase_results),
            "testcases": testcase_results,
            "simulation_time_ns": round(total_sim_ns, 3),
            "randomized_stimulus": runner_manifest.get("randomized_stimulus"),
            "coverage_schema_id": runner_manifest.get("coverage_schema_id"),
            "toolchain": runner_manifest.get("toolchain"),
            "run_manifest_sha256": sha256_file(runner_manifest_path) if runner_manifest_path.is_file() else None,
            "results_xml_sha256": sha256_file(results_path) if results_path.is_file() else None,
            "stage04_log_sha256": sha256_file(run_root / "stage04.log") if (run_root / "stage04.log").is_file() else None,
        }
        attempts.append(attempt)

        attempt_path = run_root / "corpus_attempt.json"
        attempt_path.write_text(json.dumps(attempt, indent=2) + "\n", encoding="utf-8")
        print(f"[{run_id}] {attempt['result']} ({attempt['tests_passed']}/{attempt['tests_run']} tests)", flush=True)

    success = all(attempt["result"] == "PASS" for attempt in attempts)
    manifest = {
        "schema": "aon-timer-stage05-corpus-manifest-v1",
        "freeze_id": freeze["freeze_id"],
        "pool_id": pool["pool_id"],
        "pool_path": str(args.pool.resolve().relative_to(ROOT)),
        "pool_sha256": pool_hash,
        "freeze_sha256": sha256_file(args.freeze),
        "source_revision": actual_revision,
        "coverage_schema_id": "aon_timer_uvm_source_trace_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if success else "FAIL",
        "budget": pool["budget"],
        "workers_used": 1,
        "attempt_count": len(attempts),
        "attempts": attempts,
        "source_file_sha256": {
            "tools/test_sequences.py": sha256_file(ROOT / "tools" / "test_sequences.py"),
            "tools/run_stage04_tests.sh": sha256_file(ROOT / "tools" / "run_stage04_tests.sh"),
            "tools/stage05_corpus.py": sha256_file(ROOT / "tools" / "stage05_corpus.py"),
            "tools/run_stage05_corpus.py": sha256_file(ROOT / "tools" / "run_stage05_corpus.py"),
        },
        "coverage_vector_generated": False,
        "note": "This is a functional testcase corpus; it is not a canonical coverage vector.",
    }
    manifest_path = work_root / "corpus_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": manifest["status"],
        "manifest": str(manifest_path),
        "attempt_count": len(attempts),
        "tests_passed": sum(attempt["tests_passed"] for attempt in attempts),
        "tests_failed": sum(attempt["tests_failed"] for attempt in attempts),
        "pool_sha256": pool_hash,
    }, indent=2))
    return 0 if success else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, default=DEFAULT_POOL_PATH)
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE_PATH)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--python-env", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        raise SystemExit(run(args))
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"stage05 corpus runner: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
