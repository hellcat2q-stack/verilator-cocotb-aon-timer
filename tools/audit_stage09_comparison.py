"""Independently replay Stage 09 decisions, traces, vectors and evidence hashes."""

from __future__ import annotations

from collections import Counter
import argparse
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

from run_stage05_corpus import parse_results_xml
from run_stage08_pilot import input_sha256, write_json
from stage05_corpus import sha256_file
from stage09_protocol import ROOT, POLICIES, choose, validate_freeze
from run_stage09_comparison import replay_trace, source_files


def check_ledger(directory: Path):
    errors = []
    ledger_path = directory / "sha256.txt"
    if not ledger_path.is_file():
        return ["missing sha256.txt"]
    expected = {}
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        try:
            digest, name = line.split("  ", 1)
        except ValueError:
            errors.append("malformed sha256 ledger line")
            continue
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or name in expected:
            errors.append(f"invalid or duplicate ledger path: {name}")
            continue
        expected[name] = digest
    actual = {path.relative_to(directory).as_posix(): path for path in directory.rglob("*")
              if path.is_file() and path.name != "sha256.txt"}
    if set(actual) != set(expected):
        errors.append("sha256 ledger file set mismatch")
    for name, path in actual.items():
        if expected.get(name) != sha256_file(path):
            errors.append(f"sha256 mismatch: {name}")
    return errors


def write_ledger(directory: Path):
    files = sorted(path for path in directory.rglob("*") if path.is_file() and path.name != "sha256.txt")
    (directory / "sha256.txt").write_text("".join(
        f"{sha256_file(path)}  {path.relative_to(directory).as_posix()}\n" for path in files), encoding="utf-8")


def audit(directory: Path):
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    summary_path = directory / "summary.json"
    if not summary_path.is_file():
        return {"schema": "aon-timer-stage09-comparison-replay-audit-v1", "status": "FAIL",
                "attempts_replayed": 0, "errors": ["missing summary.json"]}
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    protocol = summary.get("protocol", {})
    try:
        freeze = validate_freeze()
        check(summary.get("freeze") == freeze, "frozen configuration snapshot")
        pool_path = ROOT / protocol["pool_path"]
        pool = json.loads(pool_path.read_text(encoding="utf-8"))
        actions = pool["actions"]
        action_by_name = {row["name"]: row for row in actions}
        arms = [row["name"] for row in actions]
        catalog_ids = (ROOT / "references/canonical_bin_ids.txt").read_text(encoding="utf-8").splitlines()
        check(len(catalog_ids) == 4507 and len(set(catalog_ids)) == 4507,
              "canonical identity universe")
        check(summary.get("canonical_identity_count") == len(catalog_ids), "summary identity count")
        files = source_files(ROOT / protocol["protocol_path"] if "protocol_path" in protocol else ROOT / "configs/stage09/protocol.json",
                             pool_path, ROOT / protocol["freeze_path"])
        actual_inputs = {path.relative_to(ROOT).as_posix(): input_sha256(path) for path in files}
        check(summary.get("input_sha256") == actual_inputs, "current repository input hashes")
        check(summary.get("inputs_unchanged_after_run") is True, "run input stability flag")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return {"schema": "aon-timer-stage09-comparison-replay-audit-v1", "status": "FAIL",
                "attempts_replayed": 0, "errors": [f"cannot load frozen inputs: {exc}"]}

    rows = summary.get("attempts", [])
    expected_count = len(POLICIES) * len(protocol.get("selection_seeds", [])) * protocol.get("attempt_budget_per_policy_seed", 0)
    check(summary.get("attempts_used") == expected_count == len(rows), "fixed attempt budget")
    check(summary.get("source_revision") == "9f20940d494a223cc950a5b98f748fb28109d458",
          "pinned source revision")
    check(summary.get("paper_scheduler_enabled") is False
          and summary.get("paper_equivalence_claimed") is False
          and summary.get("full_functional_coverage_claimed") is False,
          "engineering-only scope")

    states = {(policy, seed): {"history": [], "observed": set(), "source": set(), "arrays": set(), "total_ns": 0.0,
                               "action_counts": Counter(), "curve": [], "area": 0}
              for policy in POLICIES for seed in protocol.get("selection_seeds", [])}
    previous_record_hash = None
    global_seen = set()
    all_passed = 0
    for ordinal, row in enumerate(rows, 1):
        prefix = f"attempt {ordinal}"
        policy, seed = row.get("policy"), row.get("selection_seed")
        check(row.get("global_order") == ordinal, f"{prefix}: global order")
        check(policy in POLICIES and (policy, seed) in states, f"{prefix}: policy/seed")
        if (policy, seed) not in states:
            continue
        state = states[(policy, seed)]
        selection, phase, scores = choose(arms, state["history"], policy, seed,
                                           protocol["exploration_coefficient"])
        check(row.get("testcase") == selection and row.get("phase") == phase
              and row.get("scores") == scores, f"{prefix}: replayed policy choice")
        check(row.get("completed_attempts_before_selection") == len(state["history"]),
              f"{prefix}: selection history length")
        check(row.get("positive_count_before_selection") == len(state["observed"]),
              f"{prefix}: prior positives")
        check(row.get("prior_attempt_sha256") == previous_record_hash, f"{prefix}: hash chain")
        run_id = row.get("run_id")
        check(run_id not in global_seen, f"{prefix}: duplicate run id")
        global_seen.add(run_id)
        relative = PurePosixPath(row.get("attempt_record_path", ""))
        check(not relative.is_absolute() and ".." not in relative.parts, f"{prefix}: unsafe attempt path")
        attempt_dir = directory.joinpath(*relative.parent.parts)
        record_path = attempt_dir / "attempt.json"
        selection_path = attempt_dir / "selection.json"
        vector_path = attempt_dir / "positive_vector.json"
        check(record_path.is_file() and json.loads(record_path.read_text(encoding="utf-8")) == row,
              f"{prefix}: attempt record copy")
        check(selection_path.is_file(), f"{prefix}: missing selection record")
        if selection_path.is_file():
            selection_doc = json.loads(selection_path.read_text(encoding="utf-8"))
            check(all(selection_doc.get(key) == row.get(key) for key in (
                "run_id", "policy", "selection_seed", "simulation_seed", "testcase", "phase",
                "completed_attempts_before_selection", "positive_count_before_selection", "scores",
                "prior_attempt_sha256", "global_order")), f"{prefix}: selection record mismatch")
        check(vector_path.is_file(), f"{prefix}: missing positive vector")
        if not vector_path.is_file():
            continue
        vector = json.loads(vector_path.read_text(encoding="utf-8"))
        check(sha256_file(vector_path) == row.get("positive_vector_sha256"), f"{prefix}: vector checksum")
        check(vector.get("run_id") == run_id and vector.get("testcase") == selection
              and vector.get("seed") == protocol["simulation_seed"], f"{prefix}: vector metadata")
        hits, source_hits, array_hits = set(), set(), set()
        passed = row.get("result") == "PASS"
        if passed:
            xml_path = attempt_dir / "results.xml"
            check(xml_path.is_file() and sha256_file(xml_path) == row.get("public_results_xml_sha256"),
                  f"{prefix}: public XML checksum")
            if xml_path.is_file():
                try:
                    cases, simulation_ns = parse_results_xml(xml_path)
                    check(len(cases) == 1 and cases[0]["name"] == selection and cases[0]["result"] == "PASS",
                          f"{prefix}: actual simulator result")
                    check(simulation_ns == row.get("simulation_time_ns") and simulation_ns > 0,
                          f"{prefix}: simulation time")
                except (OSError, ValueError, Exception) as exc:
                    check(False, f"{prefix}: XML parse: {type(exc).__name__}")
            trace_files = sorted((attempt_dir / "coverage-traces").glob("*.json"))
            check(len(trace_files) == 1, f"{prefix}: trace file count")
            if len(trace_files) == 1:
                check(sha256_file(trace_files[0]) == row.get("trace_sha256"), f"{prefix}: trace checksum")
                try:
                    _, hits, source_hits, array_hits = replay_trace(
                        trace_files[0], run_id, selection, protocol["simulation_seed"],
                        summary["source_revision"], protocol["coverage_schema_id"],
                        len(action_by_name[selection]["stimulus"].get("steps", [])))
                except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
                    check(False, f"{prefix}: trace replay: {exc}")
            all_passed += 1
        else:
            check(vector.get("known_positive_identities") == []
                  and vector.get("source_named_positive_identities") == []
                  and vector.get("reference_array_positive_identities") == [],
                  f"{prefix}: failed attempt has no positive vector")
            check(row.get("reward") == 0 and row.get("new_positive_count") == 0,
                  f"{prefix}: failed attempt reward")
        check(vector.get("known_positive_identities") == sorted(hits), f"{prefix}: canonical vector")
        check(vector.get("source_named_positive_identities") == sorted(source_hits), f"{prefix}: source-named vector")
        check(vector.get("reference_array_positive_identities") == sorted(array_hits), f"{prefix}: array vector")
        check(vector.get("unknown_count") == 4507 - len(hits) and vector.get("inferred_misses") == 0,
              f"{prefix}: unknown count")
        new_hits = hits - state["observed"] if passed else set()
        expected_reward = len(new_hits) / 4507 if passed else 0.0
        check(row.get("new_positive_count") == len(new_hits)
              and row.get("new_positive_identities") == sorted(new_hits), f"{prefix}: novelty")
        check(row.get("reward") == expected_reward, f"{prefix}: reward")
        if passed:
            state["observed"].update(hits)
            state["source"].update(source_hits)
            state["arrays"].update(array_hits)
            state["total_ns"] += row["simulation_time_ns"]
        state["history"].append({"testcase": selection, "reward": expected_reward,
                                 "result": "PASS" if passed else "FAIL"})
        state["action_counts"][selection] += 1
        state["curve"].append(len(state["observed"]))
        state["area"] += len(state["observed"])
        check(row.get("cumulative_positive_count") == len(state["observed"])
              and row.get("cumulative_unknown_count") == 4507 - len(state["observed"]),
              f"{prefix}: cumulative positives")
        previous_record_hash = sha256_file(record_path) if record_path.is_file() else None

    expected_summaries = []
    for policy in POLICIES:
        for seed in protocol["selection_seeds"]:
            state = states[(policy, seed)]
            rows_here = [row for row in rows if row.get("policy") == policy and row.get("selection_seed") == seed]
            expected_summaries.append({"policy": policy, "selection_seed": seed, "attempts": len(rows_here),
                "passed": sum(row.get("result") == "PASS" for row in rows_here),
                "failed": sum(row.get("result") != "PASS" for row in rows_here),
                "known_positive_count": len(state["observed"]),
                "source_named_positive_count": len(state["source"]),
                "reference_array_positive_count": len(state["arrays"]),
                "unknown_count": 4507 - len(state["observed"]), "inferred_misses": 0,
                "total_simulation_time_ns": state["total_ns"],
                "mean_cumulative_positive_count_auc": state["area"] / len(rows_here) if rows_here else 0.0,
                "action_counts": dict(state["action_counts"]), "cumulative_positive_curve": state["curve"]})
    check(summary.get("policy_seed_summaries") == expected_summaries, "policy-seed aggregate summaries")
    expected_status = "PASS" if all(row.get("result") == "PASS" for row in rows) else "FAIL"
    check(summary.get("status") == expected_status, "overall run status")
    check(summary.get("inferred_misses") == 0, "no inferred misses")

    comparison_path = directory / "comparison.csv"
    if comparison_path.is_file():
        try:
            with comparison_path.open(encoding="utf-8", newline="") as stream:
                csv_rows = list(csv.DictReader(stream))
            check(len(csv_rows) == len(expected_summaries), "comparison CSV row count")
            for csv_row, expected in zip(csv_rows, expected_summaries):
                for key in ("policy", "selection_seed", "attempts", "passed", "failed", "known_positive_count",
                            "source_named_positive_count", "reference_array_positive_count", "unknown_count", "inferred_misses"):
                    check(csv_row.get(key) == str(expected[key]), f"comparison CSV {key}")
                check(float(csv_row["total_simulation_time_ns"]) == expected["total_simulation_time_ns"],
                      "comparison CSV simulation time")
                check(float(csv_row["mean_cumulative_positive_count_auc"]) == expected["mean_cumulative_positive_count_auc"],
                      "comparison CSV cumulative-positive AUC")
        except (OSError, ValueError, KeyError, csv.Error) as exc:
            check(False, f"comparison CSV parse: {exc}")
    else:
        check(False, "missing comparison.csv")

    errors.extend(check_ledger(directory))
    return {"schema": "aon-timer-stage09-comparison-replay-audit-v1",
            "status": "PASS" if not errors else "FAIL",
            "summary_sha256": sha256_file(summary_path), "attempts_replayed": len(rows),
            "real_tests_passed": all_passed,
            "known_positive_counts_by_policy_seed": [row["known_positive_count"] for row in expected_summaries],
            "unknowns_never_inferred_as_misses": True,
            "errors": errors,
            "note": "Integrity replay of an engineering comparison; no paper-algorithm or UVM/VCS coverage parity claim."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.evidence_dir.resolve())
    output = args.output.resolve() if args.output else args.evidence_dir.resolve() / "replay-audit.json"
    write_json(output, result)
    write_ledger(args.evidence_dir.resolve())
    post_write_errors = check_ledger(args.evidence_dir.resolve())
    if post_write_errors:
        result["status"] = "FAIL"
        result["errors"].extend(post_write_errors)
        write_json(output, result)
        write_ledger(args.evidence_dir.resolve())
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
