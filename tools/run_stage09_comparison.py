"""Run a reproducible Stage 09 engineering comparison on the pinned RTL."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

try:
    from coverage_model import CoverageTrace, load_bin_catalog
    from run_stage05_corpus import parse_results_xml
    from run_stage08_pilot import export_results_xml, input_sha256, run_command, write_json
    from stage05_corpus import PINNED_REVISION, sha256_file
    from stage09_protocol import ROOT, REVISION, POLICIES, choose, validate_freeze
except ModuleNotFoundError:
    from tools.coverage_model import CoverageTrace, load_bin_catalog
    from tools.run_stage05_corpus import parse_results_xml
    from tools.run_stage08_pilot import export_results_xml, input_sha256, run_command, write_json
    from tools.stage05_corpus import PINNED_REVISION, sha256_file
    from tools.stage09_protocol import ROOT, REVISION, POLICIES, choose, validate_freeze


ARRAY_PATH = ROOT / "references/array_bin_ranges.v1.json"


def source_files(protocol_path: Path, pool_path: Path, freeze_path: Path) -> list[Path]:
    files = [protocol_path, pool_path, freeze_path, ARRAY_PATH,
             ARRAY_PATH.with_suffix(".json.sha256"), ROOT / "configs/coverage_schema.json",
             ROOT / "references/canonical_bin_catalog.json", ROOT / "references/canonical_bin_ids.txt",
             ROOT / "tools/stage09_protocol.py", ROOT / "tools/run_stage09_comparison.py",
             ROOT / "tools/audit_stage09_comparison.py", ROOT / "tools/test_stage09_sequences.py",
             ROOT / "tools/test_sequences.py", ROOT / "tools/coverage_model.py",
             ROOT / "tools/cocotb_coverage_adapter.py", ROOT / "tools/run_stage05_corpus.py",
             ROOT / "tools/stage05_corpus.py", ROOT / "tools/run_stage08_pilot.py",
             ROOT / "tools/AonMakefile", ROOT / "tools/aon_timer_tb.sv"]
    files.extend(sorted((ROOT / "tools").glob("*.core")))
    if len(files) != len(set(files)):
        raise ValueError("duplicate stage09 input path")
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise ValueError("missing experiment inputs: " + ", ".join(missing))
    return files


def replay_trace(trace_path: Path, run_id: str, testcase: str, seed: int,
                 expected_revision: str, expected_schema: str, expected_checkpoints: int):
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    for key, expected in (("run_id", run_id), ("testcase", testcase), ("seed", seed),
                          ("source_revision", expected_revision), ("schema_id", expected_schema)):
        if trace.get(key) != expected:
            raise ValueError(f"trace {trace_path.name} has wrong {key}")
    samples = trace.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("empty or malformed trace cannot pass")
    if trace.get("sample_count") != len(samples):
        raise ValueError("trace sample count mismatch")

    model = CoverageTrace(run_id, testcase, seed)
    source_named: set[str] = set()
    reference_arrays: set[str] = set()
    checkpoint_count = 0
    for sample in samples:
        group = sample.get("covergroup")
        fields = sample.get("fields")
        if not isinstance(fields, dict):
            raise ValueError("sample has no fields")
        derived = model._record(group, fields)
        for key in ("resolved_explicit_bin_memberships", "resolved_canonical_bin_identity_hits",
                    "reference_array_bin_memberships", "unpartitioned_array_declarations"):
            if sample.get(key) != derived[key]:
                raise ValueError(f"sample-derived {key} mismatch")
        array_hits = set(derived["reference_array_bin_memberships"])
        all_hits = set(derived["resolved_canonical_bin_identity_hits"])
        source_named.update(all_hits - array_hits)
        reference_arrays.update(array_hits)
        checkpoint = sample.get("configuration_checkpoint")
        if checkpoint is not None:
            checkpoint_count += 1
            expected = checkpoint.get("expected")
            readback = checkpoint.get("rtl_readback")
            names = {"wkup_thold", "bark_thold", "bite_thold", "prescale", "pause_in_sleep"}
            observed = {key: fields[key] for key in names}
            if not isinstance(expected, dict) or expected != readback or expected != observed:
                raise ValueError("RTL configuration checkpoint does not match traced sample")
    if checkpoint_count != expected_checkpoints:
        raise ValueError(f"expected {expected_checkpoints} configuration checkpoints, got {checkpoint_count}")
    replayed = model.to_dict()
    if trace.get("resolved_canonical_bin_identity_hit_counts") != replayed["resolved_canonical_bin_identity_hit_counts"]:
        raise ValueError("trace aggregate canonical hits do not replay from samples")
    identities = set(replayed["resolved_canonical_bin_identity_hit_counts"])
    return trace, identities, source_named, reference_arrays


def validate_attempt(work: Path, run_id: str, testcase: str, seed: int,
                     revision: str, schema: str, exit_code: int, expected_checkpoints: int,
                     per_attempt_cap: float):
    cases, simulation_ns = parse_results_xml(work / "results.xml")
    if (exit_code != 0 or len(cases) != 1 or cases[0]["name"] != testcase
            or cases[0]["result"] != "PASS" or simulation_ns <= 0
            or simulation_ns > per_attempt_cap):
        raise ValueError("RTL result did not meet testcase, exit-status, or time-cap requirements")
    xml_root = ET.parse(work / "results.xml").getroot()
    if xml_root.findall(".//skipped"):
        raise ValueError("simulator skipped testcase")
    trace_files = sorted((work / "coverage-traces").glob("*.json"))
    if len(trace_files) != 1:
        raise ValueError("expected exactly one testcase trace")
    trace, hits, source_named, reference_arrays = replay_trace(
        trace_files[0], run_id, testcase, seed, revision, schema, expected_checkpoints)
    return cases, simulation_ns, trace_files[0], trace, hits, source_named, reference_arrays


def configure_build(source: Path, work: Path, env: dict[str, str]) -> Path:
    setup_log = work / "setup.log"
    setup = ["fusesoc", f"--cores-root={source}", f"--cores-root={ROOT / 'tools'}", "run",
             "--target=default", "--tool=verilator", "--setup",
             f"--build-root={work / 'fusesoc'}", "lowrisc:ip:aon_timer"]
    code, timed_out, elapsed = run_command(setup, ROOT, env, setup_log, 300)
    if code != 0 or timed_out:
        raise RuntimeError(f"FuseSoC setup failed ({code}); log retained at {setup_log}")
    vc_files = list((work / "fusesoc").rglob("lowrisc_ip_aon_timer_0.1.vc"))
    if len(vc_files) != 1:
        raise RuntimeError("expected exactly one FuseSoC Verilator file list")
    build = vc_files[0].parent
    lines = vc_files[0].read_text(encoding="utf-8").splitlines()
    filtered = [line for line in lines if not (line.startswith(("--Mdir ", "--top-module "))
                or line in {"--cc", "--exe", "--lint-only", "--Mdir", "--top-module"})]
    (build / "aon_timer_sources.vc").write_text("\n".join(filtered) + "\n", encoding="utf-8")
    return build


def run(args) -> int:
    protocol_path = args.protocol.resolve()
    if protocol_path != ROOT / "configs/stage09/protocol.json":
        raise ValueError("protocol must be the frozen Stage 09 protocol")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    freeze = validate_freeze()
    pool_path = ROOT / protocol["pool_path"]
    freeze_path = ROOT / protocol["freeze_path"]
    pool = json.loads(pool_path.read_text(encoding="utf-8"))
    if (protocol.get("schema") != "aon-timer-stage09-engineering-comparison-v1"
            or protocol.get("source_revision") != REVISION
            or protocol.get("policies") != list(POLICIES)
            or pool.get("source_revision") != REVISION
            or pool.get("pool_id") != "stage09-array-partition-blocks-v1"):
        raise ValueError("unsupported Stage 09 protocol or action pool")
    actions = pool["actions"]
    arms = [item["name"] for item in actions]
    if not arms or len(arms) != len(set(arms)):
        raise ValueError("action pool names must be unique and non-empty")
    action_by_name = {item["name"]: item for item in actions}
    catalog, identities = load_bin_catalog()
    identity_set = set(identities)
    if catalog["canonical_bin_count"] != 4507:
        raise ValueError("unexpected canonical identity universe")

    source = args.source_root.resolve()
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != PINNED_REVISION or revision != REVISION:
        raise ValueError("source checkout is not the pinned revision")
    if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True).strip():
        raise ValueError("use a clean isolated pinned source checkout")

    env = os.environ.copy()
    python_env = args.python_env.resolve()
    env["PATH"] = str(python_env / "bin") + os.pathsep + env["PATH"]
    env["PYTHONPATH"] = str(ROOT / "tools")
    env["AON_TIMER_TEST_POOL"] = str(pool_path)
    for key in ("TESTCASE", "COCOTB_TEST_FILTER", "COCOTB_RESULTS_FILE", "SIM_BUILD"):
        env.pop(key, None)
    versions = {}
    for name, command, expected in (
        ("verilator", ["verilator", "--version"], "Verilator 5.020"),
        ("cocotb", ["cocotb-config", "--version"], "1.9.2"),
        ("fusesoc", ["fusesoc", "--version"], "0.5.dev0"),
    ):
        versions[name] = subprocess.check_output(command, env=env, text=True).strip()
        if not versions[name].startswith(expected):
            raise ValueError(f"unexpected {name} version: {versions[name]}")
    for package, expected in (("edalize", "0.4.0"), ("cocotb", "1.9.2")):
        actual = subprocess.check_output([str(python_env / "bin/python"), "-c",
            f"from importlib.metadata import version; print(version('{package}'))"], env=env, text=True).strip()
        versions[package + "_python_package"] = actual
        if actual != expected:
            raise ValueError(f"unexpected {package} package version: {actual}")

    work = args.work_root.resolve()
    output = args.output.resolve()
    if work.exists() or output.exists():
        raise ValueError("work/output must be fresh directories; preserve existing evidence")
    work.mkdir(parents=True)
    output.mkdir(parents=True)
    files = source_files(protocol_path, pool_path, freeze_path)
    input_hashes = {path.relative_to(ROOT).as_posix(): input_sha256(path) for path in files}
    report = {"schema": "aon-timer-stage09-engineering-comparison-v1", "status": "RUNNING",
              "started_utc": datetime.now(timezone.utc).isoformat(), "protocol": protocol,
              "freeze": freeze, "source_revision": revision, "coverage_schema_id": protocol["coverage_schema_id"],
              "canonical_identity_count": len(identities), "canonical_identity_list_sha256": catalog["canonical_bin_ids_sha256"],
              "toolchain": versions, "project_commit_before_run": subprocess.check_output(
                  ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "input_hash_policy": "sha256_of_lf_normalized_repository_text_bytes",
              "input_sha256": input_hashes, "precompile": None, "attempts": [],
              "paper_scheduler_enabled": False, "paper_equivalence_claimed": False,
              "full_functional_coverage_claimed": False, "inferred_misses": 0}
    write_json(output / "summary.json", report)

    try:
        build = configure_build(source, work, env)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        report["status"] = "SETUP_FAILED"
        report["setup_error"] = str(exc)
        write_json(output / "summary.json", report)
        raise
    report["generated_filelist_sha256"] = sha256_file(build / "aon_timer_sources.vc")
    code, timed_out, compile_wall = run_command(
        ["make", "-f", str(ROOT / "tools/AonMakefile"),
         "MODULE=test_stage09_sequences", "sim_build/Vtop"],
        build, env, work / "precompile.log", 600)
    report["precompile"] = {"exit_code": code, "timed_out": timed_out,
                            "wall_seconds": compile_wall,
                            "log_sha256": sha256_file(work / "precompile.log")}
    if code != 0 or timed_out or not (build / "sim_build/Vtop").is_file():
        report["status"] = "PRECOMPILE_FAILED"
        write_json(output / "summary.json", report)
        raise RuntimeError("Verilator precompile failed; log and partial evidence retained")
    report["compile_wall_seconds_excluded_from_simulation_cost"] = compile_wall
    write_json(output / "summary.json", report)

    global_observed = 0
    global_order = 0
    policy_order = list(POLICIES)
    for seed_index, selection_seed in enumerate(protocol["selection_seeds"]):
        rotated = policy_order[seed_index:] + policy_order[:seed_index]
        states = {policy: {"history": [], "observed": set(), "source_named": set(),
                           "reference_arrays": set(), "total_simulation_ns": 0.0}
                  for policy in POLICIES}
        for attempt_index in range(protocol["attempt_budget_per_policy_seed"]):
            for policy in rotated:
                state = states[policy]
                testcase, phase, scores = choose(arms, state["history"], policy, selection_seed,
                                                 protocol["exploration_coefficient"])
                global_order += 1
                run_id = f"{protocol['experiment_id']}-{policy}-s{selection_seed}-{attempt_index + 1:03d}"
                rel = Path(policy) / f"selection-seed-{selection_seed}" / f"attempt-{attempt_index + 1:03d}"
                attempt_out = output / rel
                attempt_out.mkdir(parents=True)
                attempt_work = work / rel
                (attempt_work / "coverage-traces").mkdir(parents=True)
                selection = {"run_id": run_id, "policy": policy, "selection_seed": selection_seed,
                             "simulation_seed": protocol["simulation_seed"], "testcase": testcase,
                             "phase": phase, "completed_attempts_before_selection": len(state["history"]),
                             "positive_count_before_selection": len(state["observed"]),
                             "scores": scores,
                             "prior_attempt_sha256": (sha256_file(output / report["attempts"][-1]["attempt_record_path"])
                                                       if report["attempts"] else None),
                             "global_order": global_order}
                write_json(attempt_out / "selection.json", selection)
                trace_dir = attempt_work / "coverage-traces"
                attempt_env = {**env, "RUN_ID": run_id,
                               "RANDOM_SEED": str(protocol["simulation_seed"]),
                               "TESTCASE": testcase, "COVERAGE_TRACE_DIR": str(trace_dir)}
                result_path = build / "results.xml"
                if result_path.exists():
                    result_path.unlink()
                print(f"[{global_order}/288] {policy} seed={selection_seed} {attempt_index + 1}/24 {testcase}", flush=True)
                exit_code, timed_out, wall_seconds = run_command(
                    ["make", "-f", str(ROOT / "tools/AonMakefile"),
                     "MODULE=test_stage09_sequences", "sim"], build, attempt_env,
                    attempt_work / "simulation.log", protocol["timeout_seconds_per_attempt"])
                if result_path.is_file():
                    shutil.copy2(result_path, attempt_work / "results.xml")

                failure = None
                cases, simulation_ns, trace_path, trace, hits, source_hits, array_hits = [], 0.0, None, {}, set(), set(), set()
                expected_checkpoints = len(action_by_name[testcase]["stimulus"].get("steps", []))
                try:
                    cases, simulation_ns, trace_path, trace, hits, source_hits, array_hits = validate_attempt(
                        attempt_work, run_id, testcase, protocol["simulation_seed"], revision,
                        protocol["coverage_schema_id"], exit_code, expected_checkpoints,
                        protocol["simulation_time_limit_ns_per_attempt"])
                    if not hits <= identity_set:
                        raise ValueError("sample replay produced an unknown canonical identity")
                    if state["total_simulation_ns"] + simulation_ns > protocol["total_simulation_time_cap_ns_per_policy_seed"]:
                        raise ValueError("policy-seed simulation-time cap exceeded")
                except (ValueError, KeyError, OSError, ET.ParseError) as exc:
                    failure = str(exc)
                    hits, source_hits, array_hits = set(), set(), set()

                observed_before = set(state["observed"])
                new_hits = hits - observed_before
                if failure is None:
                    state["observed"].update(hits)
                    state["source_named"].update(source_hits)
                    state["reference_arrays"].update(array_hits)
                    state["total_simulation_ns"] += simulation_ns
                reward = len(new_hits) / len(identities) if failure is None else 0.0
                state["history"].append({"testcase": testcase, "reward": reward,
                                         "result": "PASS" if failure is None else "FAIL"})

                if (attempt_work / "results.xml").is_file():
                    export_results_xml(attempt_work / "results.xml", attempt_out / "results.xml",
                                       ((ROOT, "[project]"), (source, "[source]"),
                                        (work, "[work]"), (python_env, "[python-env]")))
                produced_traces = sorted((attempt_work / "coverage-traces").glob("*.json"))
                if produced_traces:
                    public_trace_dir = attempt_out / "coverage-traces"
                    public_trace_dir.mkdir(exist_ok=True)
                    for produced_trace in produced_traces:
                        shutil.copy2(produced_trace, public_trace_dir / produced_trace.name)
                vector = {"schema": "aon-timer-stage09-positive-only-vector-v1", "run_id": run_id,
                          "source_revision": revision, "coverage_schema_id": protocol["coverage_schema_id"],
                          "testcase": testcase, "seed": protocol["simulation_seed"],
                          "result": "PASS" if failure is None else "FAIL",
                          "known_positive_identities": sorted(hits if failure is None else []),
                          "source_named_positive_identities": sorted(source_hits if failure is None else []),
                          "reference_array_positive_identities": sorted(array_hits if failure is None else []),
                          "unknown_count": len(identities) - len(hits if failure is None else []),
                          "inferred_misses": 0}
                write_json(attempt_out / "positive_vector.json", vector)
                attempt_record = {**selection, "result": vector["result"], "exit_code": exit_code,
                                  "timed_out": timed_out, "wall_seconds": wall_seconds,
                                  "simulation_time_ns": simulation_ns, "testcases": cases,
                                  "sample_count": trace.get("sample_count", 0),
                                  "new_positive_count": len(new_hits), "new_positive_identities": sorted(new_hits),
                                  "cumulative_positive_count": len(state["observed"]),
                                  "source_named_positive_count": len(state["source_named"]),
                                  "reference_array_positive_count": len(state["reference_arrays"]),
                                  "cumulative_unknown_count": len(identities) - len(state["observed"]),
                                  "reward": reward, "validation_error": failure,
                                  "trace_sha256": sha256_file(attempt_out / "coverage-traces" / trace_path.name)
                                      if trace_path is not None and (attempt_out / "coverage-traces" / trace_path.name).is_file() else None,
                                  "raw_results_xml_sha256": sha256_file(attempt_work / "results.xml")
                                      if (attempt_work / "results.xml").is_file() else None,
                                  "public_results_xml_sha256": sha256_file(attempt_out / "results.xml")
                                      if (attempt_out / "results.xml").is_file() else None,
                                  "positive_vector_sha256": sha256_file(attempt_out / "positive_vector.json"),
                                  "simulation_log_sha256": sha256_file(attempt_work / "simulation.log"),
                                  "attempt_record_path": (attempt_out / "attempt.json").relative_to(output).as_posix()}
                write_json(attempt_out / "attempt.json", attempt_record)
                report["attempts"].append(attempt_record)
                report["status"] = "RUNNING"
                write_json(output / "summary.json", report)
                print(f"  {attempt_record['result']} samples={attempt_record['sample_count']} "
                      f"new={len(new_hits)} known={len(state['observed'])} sim_ns={simulation_ns:.0f}", flush=True)

    summaries = []
    for policy in POLICIES:
        for selection_seed in protocol["selection_seeds"]:
            rows = [row for row in report["attempts"]
                    if row["policy"] == policy and row["selection_seed"] == selection_seed]
            positives = set()
            source_positive = set()
            array_positive = set()
            cumulative = []
            total_ns = 0.0
            area = 0
            for row in rows:
                vector_path = output / Path(row["attempt_record_path"]).parent / "positive_vector.json"
                vector = json.loads(vector_path.read_text(encoding="utf-8"))
                current = set(vector["known_positive_identities"])
                positives.update(current)
                source_positive.update(vector["source_named_positive_identities"])
                array_positive.update(vector["reference_array_positive_identities"])
                total_ns += row["simulation_time_ns"] if row["result"] == "PASS" else 0.0
                cumulative.append(len(positives))
                area += len(positives)
            summaries.append({"policy": policy, "selection_seed": selection_seed,
                              "attempts": len(rows), "passed": sum(row["result"] == "PASS" for row in rows),
                              "failed": sum(row["result"] != "PASS" for row in rows),
                              "known_positive_count": len(positives),
                              "source_named_positive_count": len(source_positive),
                              "reference_array_positive_count": len(array_positive),
                              "unknown_count": len(identities) - len(positives), "inferred_misses": 0,
                              "total_simulation_time_ns": total_ns,
                              "mean_cumulative_positive_count_auc": area / len(rows) if rows else 0.0,
                              "action_counts": dict(Counter(row["testcase"] for row in rows)),
                              "cumulative_positive_curve": cumulative})
    report["policy_seed_summaries"] = summaries
    report["status"] = "PASS" if all(row["result"] == "PASS" for row in report["attempts"]) else "FAIL"
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    report["attempts_used"] = len(report["attempts"])
    report["inputs_unchanged_after_run"] = all(
        input_sha256(ROOT / name) == digest for name, digest in input_hashes.items())
    if not report["inputs_unchanged_after_run"]:
        report["status"] = "FAIL_INPUT_CHANGED_DURING_RUN"
    write_json(output / "summary.json", report)
    with (output / "comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["policy", "selection_seed", "attempts", "passed", "failed", "known_positive_count",
                  "source_named_positive_count", "reference_array_positive_count", "unknown_count",
                  "inferred_misses", "total_simulation_time_ns", "mean_cumulative_positive_count_auc"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row[key] for key in fields} for row in summaries)
    files = sorted(path for path in output.rglob("*") if path.is_file() and path.name != "sha256.txt")
    (output / "sha256.txt").write_text("".join(
        f"{sha256_file(path)}  {path.relative_to(output).as_posix()}\n" for path in files), encoding="utf-8")
    print(json.dumps({"status": report["status"], "attempts_used": report["attempts_used"],
                      "policy_seed_summaries": summaries}, indent=2))
    return 0 if report["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=ROOT / "configs/stage09/protocol.json")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--python-env", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        return run(args)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"stage09 comparison: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
