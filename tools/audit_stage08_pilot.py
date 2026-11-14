"""Replay saved online decisions against raw simulator traces and result XML.

This checks the open-source pilot's event chain, not UVM/VCS equivalence.
"""

import argparse
from collections import Counter
import csv
import io
import json
from pathlib import Path

try:
    from run_stage08_pilot import ROOT, collect_attempt, input_sha256, select_action, sha256_file, write_json
except ModuleNotFoundError:
    from tools.run_stage08_pilot import ROOT, collect_attempt, input_sha256, select_action, sha256_file, write_json


def audit(directory):
    directory = Path(directory)
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    protocol = summary["protocol"]
    pool = json.loads((ROOT / protocol["pool_path"]).read_text(encoding="utf-8"))
    entries = pool.get("testcases", pool.get("actions"))
    arms = [case["name"] for case in entries]
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    check(summary["input_hash_policy"] == "sha256_of_lf_normalized_repository_text_bytes", "input hash policy")
    for name, digest in summary["input_sha256"].items():
        check(input_sha256(ROOT / name) == digest, f"input changed: {name}")
    for line in (directory / "sha256.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        path = (directory / name).resolve()
        check(path.is_relative_to(directory.resolve()), f"unsafe checksum path: {name}")
        if path.is_relative_to(directory.resolve()):
            check(path.is_file() and sha256_file(path) == digest, f"evidence hash: {name}")
    rows = summary["attempts"]
    check(len(rows) == protocol["attempt_budget"] == summary["attempts_used"], "attempt budget")
    observed = set()
    history = []
    total_samples = 0
    passed_count = 0
    for number, row in enumerate(rows, 1):
        prefix = f"attempt {number}"
        current = directory / f"attempt-{number:03d}"
        recorded = json.loads((current / "attempt.json").read_text(encoding="utf-8"))
        selection = json.loads((current / "selection.json").read_text(encoding="utf-8"))
        vector = json.loads((current / "positive_vector.json").read_text(encoding="utf-8"))
        action, phase, scores = select_action(arms, history, protocol["exploration_coefficient"])
        check(row == recorded, f"{prefix}: summary/attempt mismatch")
        check(action == row["testcase"] and phase == row["phase"] and scores == row["ucb_scores"], f"{prefix}: replay choice")
        check(all(row.get(key) == value for key, value in selection.items()), f"{prefix}: persisted pre-run decision")
        check(selection["completed_attempts_before_selection"] == len(history), f"{prefix}: future feedback")
        check(selection["observed_positive_count_before_selection"] == len(observed), f"{prefix}: pre-run positive count")
        prior = sha256_file(directory / f"attempt-{number-1:03d}/attempt.json") if number > 1 else None
        check(row["prior_attempt_sha256"] == prior, f"{prefix}: event-chain hash")
        passed, cases, sim_ns, trace = collect_attempt(
            current, row["run_id"], action, protocol["seed"], summary["source_revision"],
            protocol["coverage_schema_id"], row["exit_code"])
        passed = passed and sim_ns <= protocol["simulation_time_limit_ns_per_attempt"]
        check((row["result"] == "PASS") == passed, f"{prefix}: actual simulation outcome")
        check(trace == row["trace_summary"] and cases == row["testcases"], f"{prefix}: raw trace/XML summary")
        hits = set(trace["resolved_canonical_bin_identity_hit_counts"]) if passed else set()
        new_hits = hits - observed
        check(vector["known_positive_identities"] == sorted(hits), f"{prefix}: sparse positive vector")
        check(vector["unknown_count"] == summary["canonical_identity_count"] - len(hits)
              and vector["inferred_misses"] == 0, f"{prefix}: unknown bins must not become misses")
        check(row["positive_vector_sha256"] == sha256_file(current / "positive_vector.json"), f"{prefix}: vector hash")
        if (current / "results.xml").is_file():
            check(row["public_results_xml_sha256"] == sha256_file(current / "results.xml"), f"{prefix}: public XML hash")
        check(row["new_positive_identities"] == sorted(new_hits) and row["new_positive_count"] == len(new_hits), f"{prefix}: novelty")
        check(row["reward"] == len(new_hits) / summary["canonical_identity_count"], f"{prefix}: reward")
        observed.update(hits)
        check(row["cumulative_positive_count"] == len(observed), f"{prefix}: cumulative positives")
        check(row["cumulative_unknown_count"] == summary["canonical_identity_count"] - len(observed), f"{prefix}: cumulative unknowns")
        history.append(row)
        total_samples += trace["total_sample_count"]
        passed_count += passed
    curve = list(csv.DictReader(io.StringIO((directory / "coverage_curve.csv").read_text(encoding="utf-8"))))
    check(len(curve) == len(rows), "coverage curve row count")
    for record, row in zip(curve, rows):
        check(record["testcase"] == row["testcase"] and record["result"] == row["result"]
              and int(record["new_positives"]) == row["new_positive_count"]
              and int(record["cumulative_positives"]) == row["cumulative_positive_count"]
              and int(record["unknown"]) == row["cumulative_unknown_count"]
              and float(record["reward"]) == row["reward"], "coverage curve data")
    check(summary["known_positive_count"] == len(observed)
          and summary["cumulative_positive_identities"] == sorted(observed), "final positive union")
    check(summary["unknown_count"] == summary["canonical_identity_count"] - len(observed)
          and summary["inferred_misses"] == 0, "final unknowns")
    check(summary["action_counts"] == dict(Counter(row["testcase"] for row in rows)), "action counts")
    check(summary["status"] == ("PASS" if passed_count == len(rows) else "FAIL"), "final status")
    check(summary["paper_scheduler_enabled"] is False and summary["paper_equivalence_claimed"] is False, "pilot scope")
    return {"schema": "aon-timer-stage08-pilot-replay-audit-v1", "status": "PASS" if not errors else "FAIL",
            "summary_sha256": sha256_file(directory / "summary.json"), "attempts_replayed": len(rows),
            "real_tests_passed": passed_count, "raw_samples_revalidated": total_samples,
            "ucb_decisions_replayed": sum(row["phase"] == "ucb" for row in rows),
            "known_positive_count": len(observed), "unknown_count": summary["canonical_identity_count"] - len(observed),
            "errors": errors, "note": "Pilot integrity replay only; no claim of paper scheduling efficiency or UVM/VCS coverage parity."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.evidence_dir)
    write_json(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
