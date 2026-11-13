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
COUNT_EVENT_FIELDS = {
    "wake_up_timer_thold_hit_cg": "wkup_count",
    "watchdog_timer_bark_thold_hit_cg": "wdog_count",
    "watchdog_timer_bite_thold_hit_cg": "wdog_count",
}


def validate_count_event_sample(sample: dict[str, Any]) -> bool:
    """Check the count-event trace shape and its independent RTL count probe."""
    group = sample.get("covergroup")
    if group not in COUNT_EVENT_FIELDS:
        return True
    field_name = COUNT_EVENT_FIELDS[group]
    fields = sample.get("fields")
    if not isinstance(fields, dict):
        return False
    expected_event_prefix = {
        "wake_up_timer_thold_hit_cg": "aon_countdown_wakeup_",
        "watchdog_timer_bark_thold_hit_cg": "aon_countdown_bark_",
        "watchdog_timer_bite_thold_hit_cg": "aon_countdown_bite_",
    }[group]
    event = sample.get("capture_event")
    if event not in {expected_event_prefix + "count", expected_event_prefix + "expiry"}:
        return False
    observed = fields.get(field_name)
    rtl_count = sample.get("rtl_count")
    target = sample.get("scoreboard_target_cycles")
    countdown = sample.get("scoreboard_countdown_cycles")
    integers = (observed, rtl_count, target, countdown)
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in integers):
        return False
    if observed != rtl_count or countdown > target:
        return False
    if event.endswith("_expiry") and countdown != target:
        return False
    if event.endswith("_count") and target == 0:
        return False
    return True


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


def summarize_coverage_trace(run_root: Path, runner_manifest: dict[str, Any]) -> dict[str, Any]:
    """Verify and summarize partial raw traces without embedding sample data."""
    trace_manifest = runner_manifest.get("coverage_trace")
    result: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "canonical_vector_generated": False,
        "validated": False,
        "file_count": 0,
        "total_sample_count": 0,
        "sample_counts_by_covergroup": {},
        "resolved_canonical_bin_identity_hit_counts": {},
        "files": {},
    }
    if not isinstance(trace_manifest, dict):
        return result

    result["status"] = trace_manifest.get("status", "UNAVAILABLE")
    result["canonical_vector_generated"] = trace_manifest.get("canonical_vector_generated")
    declared_files = trace_manifest.get("files")
    if not isinstance(declared_files, dict) or not declared_files:
        return result

    valid = (
        result["status"] == "PARTIAL_SOURCE_SAMPLE_TRACE"
        and result["canonical_vector_generated"] is False
        and runner_manifest.get("coverage_vector") is None
    )
    totals: dict[str, int] = {}
    identity_hit_totals: dict[str, int] = {}
    trace_testcases: list[str] = []
    summarized_files: dict[str, Any] = {}

    for filename, declared in sorted(declared_files.items()):
        file_valid = (
            isinstance(filename, str)
            and Path(filename).name == filename
            and "/" not in filename
            and "\\" not in filename
            and isinstance(declared, dict)
        )
        trace_path = run_root / "coverage-traces" / filename if file_valid else None
        if trace_path is None or not trace_path.is_file():
            summarized_files[str(filename)] = {"validation": "FAIL", "reason": "missing_or_invalid_path"}
            valid = False
            continue

        trace_bytes = trace_path.read_bytes()
        digest = hashlib.sha256(trace_bytes).hexdigest()
        try:
            trace = json.loads(trace_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            summarized_files[filename] = {"sha256": digest, "validation": "FAIL", "reason": "invalid_json"}
            valid = False
            continue

        samples = trace.get("samples")
        if not isinstance(samples, list):
            samples = []
            file_valid = False
        sample_count = len(samples)
        counts: dict[str, int] = {}
        identity_hits: dict[str, int] = {}
        count_event_samples_valid = True
        for sample in samples:
            if not isinstance(sample, dict) or not isinstance(sample.get("covergroup"), str):
                valid = False
                file_valid = False
                continue
            group = sample["covergroup"]
            count_event_samples_valid = (
                validate_count_event_sample(sample) and count_event_samples_valid
            )
            counts[group] = counts.get(group, 0) + 1
            sample_hits = sample.get("resolved_canonical_bin_identity_hits", [])
            if not isinstance(sample_hits, list) or any(not isinstance(hit, str) for hit in sample_hits):
                valid = False
                file_valid = False
                continue
            for hit in sample_hits:
                identity_hits[hit] = identity_hits.get(hit, 0) + 1
        declared_count = trace.get("sample_counts_by_covergroup", {})
        declared_identity_hits = trace.get("resolved_canonical_bin_identity_hit_counts", {})
        file_checks = {
            "sha256": digest == declared.get("sha256"),
            "sample_count": sample_count == declared.get("sample_count") == trace.get("sample_count"),
            "sample_counts_by_covergroup": counts == declared_count,
            "resolved_identity_hit_counts": identity_hits == declared_identity_hits,
            "count_event_samples": count_event_samples_valid,
            "coverage_status": trace.get("coverage_status") == declared.get("coverage_status"),
            "run_id": trace.get("run_id") == runner_manifest.get("run_id"),
            "seed": trace.get("seed") == runner_manifest.get("seed"),
            "source_revision": trace.get("source_revision") == runner_manifest.get("source_revision"),
            "coverage_schema_id": trace.get("schema_id") == runner_manifest.get("coverage_schema_id"),
            "no_canonical_vector": trace.get("canonical_bin_vector") is None,
        }
        file_passed = file_valid and all(file_checks.values())
        valid = valid and file_passed
        testcase = trace.get("testcase")
        if isinstance(testcase, str):
            trace_testcases.append(testcase)
        for group, count in counts.items():
            totals[group] = totals.get(group, 0) + count
        for identity, count in identity_hits.items():
            identity_hit_totals[identity] = identity_hit_totals.get(identity, 0) + count
        result["total_sample_count"] += sample_count
        summarized_files[filename] = {
            "testcase": testcase,
            "sha256": digest,
            "sample_count": sample_count,
            "sample_counts_by_covergroup": counts,
            "coverage_status": trace.get("coverage_status"),
            "count_event_samples_valid": count_event_samples_valid,
            "validation": "PASS" if file_passed else "FAIL",
            "checks": file_checks,
        }

    expected_testcases = runner_manifest.get("testcases", [])
    actual_trace_names = {path.name for path in (run_root / "coverage-traces").glob("*.json")}
    valid = valid and actual_trace_names == set(declared_files)
    valid = (
        valid
        and len(trace_testcases) == len(set(trace_testcases))
        and set(trace_testcases) == set(expected_testcases)
        and len(summarized_files) == len(declared_files)
        and result["total_sample_count"] == sum(
            item.get("sample_count", 0) for item in summarized_files.values()
        )
    )
    result.update({
        "validated": valid,
        "file_count": len(summarized_files),
        "total_sample_count": result["total_sample_count"],
        "sample_counts_by_covergroup": totals,
        "resolved_canonical_bin_identity_hit_counts": dict(sorted(identity_hit_totals.items())),
        "files": summarized_files,
    })
    return result


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
        coverage_trace = summarize_coverage_trace(run_root, runner_manifest)
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
            and coverage_trace["validated"]
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
            "coverage_trace": coverage_trace,
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
        "coverage_schema_id": "aon_timer_uvm_source_trace_v2",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if success else "FAIL",
        "budget": pool["budget"],
        "workers_used": 1,
        "attempt_count": len(attempts),
        "attempts": attempts,
        "source_file_sha256": {
            "tools/test_sequences.py": sha256_file(ROOT / "tools" / "test_sequences.py"),
            "tools/aon_timer_tb.sv": sha256_file(ROOT / "tools" / "aon_timer_tb.sv"),
            "tools/coverage_model.py": sha256_file(ROOT / "tools" / "coverage_model.py"),
            "tools/cocotb_coverage_adapter.py": sha256_file(ROOT / "tools" / "cocotb_coverage_adapter.py"),
            "tools/run_stage04_tests.sh": sha256_file(ROOT / "tools" / "run_stage04_tests.sh"),
            "tools/stage05_corpus.py": sha256_file(ROOT / "tools" / "stage05_corpus.py"),
            "tools/run_stage05_corpus.py": sha256_file(ROOT / "tools" / "run_stage05_corpus.py"),
            "configs/coverage_schema.json": sha256_file(ROOT / "configs" / "coverage_schema.json"),
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
