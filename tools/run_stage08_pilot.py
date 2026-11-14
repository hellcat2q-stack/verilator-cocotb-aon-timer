"""Run a bounded real RTL / positive-hit feedback pilot, separately from paper gates.

The four testcase arms use fixed stimuli. Unknown canonical bins are never
converted to misses, and this pilot does not enable the paper scheduler.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

try:
    from coverage_model import load_bin_catalog
    from run_stage05_corpus import parse_results_xml, summarize_coverage_trace
    from stage05_corpus import PINNED_REVISION, load_frozen_pool, sha256_file
except ModuleNotFoundError:
    from tools.coverage_model import load_bin_catalog
    from tools.run_stage05_corpus import parse_results_xml, summarize_coverage_trace
    from tools.stage05_corpus import PINNED_REVISION, load_frozen_pool, sha256_file

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = ROOT / "configs/stage08-pilot.json"


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def input_sha256(path):
    """Repository text inputs use LF-normalized bytes across Windows/Linux."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_action_pool(path):
    with path.open(encoding="utf-8") as stream:
        pool = json.load(stream)
    if pool.get("schema") != "aon-timer-stage08-action-pool-v1":
        raise ValueError("unsupported Stage 08 action pool schema")
    if pool.get("source_revision") != PINNED_REVISION or pool.get("deterministic") is not True:
        raise ValueError("action pool source revision or deterministic flag is invalid")
    actions = pool.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("action pool must contain actions")
    names = [item.get("name") for item in actions]
    if len(set(names)) != len(names) or any(not isinstance(name, str) or not name for name in names):
        raise ValueError("action names must be unique non-empty strings")
    for action in actions:
        if not isinstance(action.get("base_test"), str) or not isinstance(action.get("stimulus"), dict):
            raise ValueError("each action needs base_test and stimulus")
    return pool


def export_results_xml(source_path, target_path, private_roots=()):
    """Keep the unmodified XML locally; publish an explicitly normalized copy."""
    tree = ET.parse(source_path)
    for node in tree.iter():
        if "file" in node.attrib:
            node.set("file", "tools/" + node.attrib["file"].replace("\\", "/").rsplit("/", 1)[-1])
        for private_root, label in private_roots:
            for key, value in node.attrib.items():
                node.set(key, value.replace(str(private_root), label))
            if node.text:
                node.text = node.text.replace(str(private_root), label)
            if node.tail:
                node.tail = node.tail.replace(str(private_root), label)
    ET.indent(tree)
    tree.write(target_path, encoding="unicode")


def select_action(arms, history, exploration=0.01):
    """Warm up each arm, then choose using *completed* attempts only."""
    counts = Counter(row["testcase"] for row in history)
    totals = {arm: sum(row["reward"] for row in history if row["testcase"] == arm) for arm in arms}
    for arm in arms:
        if counts[arm] == 0:
            return arm, "warmup", {}
    scores = {
        arm: totals[arm] / counts[arm]
        + exploration * math.sqrt(2 * math.log(len(history)) / counts[arm])
        for arm in arms
    }
    return max(arms, key=lambda arm: scores[arm]), "ucb", scores


def run_command(command, cwd, env, log_path, timeout):
    """Retain logs and terminate the entire simulator process group on timeout."""
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as exc:
            log.write(f"launch failed: {type(exc).__name__}: {exc}\n")
            return 127, False, round(time.monotonic() - started, 4)
        timed_out = False
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            code = 124
    return code, timed_out, round(time.monotonic() - started, 4)


def collect_attempt(run_root, run_id, testcase, seed, revision, schema, code):
    """Bind actual trace files to this one completed testcase and validate them."""
    files = {}
    for path in sorted((run_root / "coverage-traces").glob("*.json")):
        trace = json.loads(path.read_text(encoding="utf-8"))
        files[path.name] = {
            "sha256": sha256_file(path), "sample_count": trace.get("sample_count"),
            "sample_counts_by_covergroup": trace.get("sample_counts_by_covergroup", {}),
            "coverage_status": trace.get("coverage_status"),
        }
    runner = {
        "run_id": run_id, "seed": seed, "testcases": [testcase],
        "source_revision": revision, "coverage_schema_id": schema, "coverage_vector": None,
        "coverage_trace": {"status": "PARTIAL_SOURCE_SAMPLE_TRACE",
                           "canonical_vector_generated": False, "files": files},
    }
    trace_summary = summarize_coverage_trace(run_root, runner)
    cases, simulation_ns = parse_results_xml(run_root / "results.xml")
    passed = (code == 0 and [case["name"] for case in cases] == [testcase]
              and all(case["result"] == "PASS" for case in cases)
              and trace_summary["validated"])
    if (run_root / "results.xml").is_file():
        passed = passed and not ET.parse(run_root / "results.xml").findall(".//skipped")
    return passed, cases, simulation_ns, trace_summary


def run(args):
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    if (protocol.get("schema") != "aon-timer-stage08-pilot-protocol-v1"
            or protocol.get("source_revision") != PINNED_REVISION
            or protocol.get("selection_policy") != "testcase_ucb_positive_novelty_v1"):
        raise ValueError("unsupported pilot protocol or source revision")
    pool_path = ROOT / protocol["pool_path"]
    pool = load_action_pool(pool_path)
    freeze_path = ROOT / protocol["freeze_path"]
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    pool_hash = input_sha256(pool_path)
    if freeze.get("action_pool_sha256") != pool_hash:
        raise ValueError("action pool does not match its freeze record")
    arms = [case["name"] for case in pool["actions"]]
    budget = protocol["attempt_budget"]
    if not isinstance(budget, int) or budget < len(arms):
        raise ValueError("budget must allow one real attempt per arm")
    if (protocol["coverage_schema_id"] != "aon_timer_uvm_source_trace_v2"
            or not isinstance(protocol["seed"], int) or protocol["seed"] < 0
            or not math.isfinite(protocol["exploration_coefficient"])
            or protocol["exploration_coefficient"] < 0
            or protocol["timeout_seconds_per_attempt"] <= 0
            or protocol["simulation_time_limit_ns_per_attempt"] <= 0):
        raise ValueError("invalid pilot schema, seed, exploration, or budget")
    source = args.source_root.resolve()
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != PINNED_REVISION:
        raise ValueError("source checkout is not the pinned revision")
    if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True).strip():
        raise ValueError("use a clean isolated pinned source checkout")
    catalog, ids = load_bin_catalog()
    id_set = set(ids)
    clusters = json.loads((ROOT / protocol["cluster_path"]).read_text(encoding="utf-8"))
    membership = {}
    for cluster, value in clusters.items():
        for identity in value["bins"]:
            if identity in membership:
                raise ValueError("duplicate identity in cluster map")
            membership[identity] = cluster
    if set(membership) != id_set:
        raise ValueError("cluster map differs from canonical identity universe")
    env = os.environ.copy()
    env["PATH"] = str(args.python_env.resolve() / "bin") + os.pathsep + env["PATH"]
    env["PYTHONPATH"] = str(ROOT / "tools")
    env["AON_TIMER_TEST_POOL"] = str(ROOT / protocol["pool_path"])
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
    for package in ("edalize", "cocotb"):
        versions[package + "_python_package"] = subprocess.check_output(
            [str(args.python_env.resolve() / "bin/python"), "-c",
             f"from importlib.metadata import version; print(version('{package}'))"],
            env=env, text=True).strip()
    if versions["edalize_python_package"] != "0.4.0":
        raise ValueError("expected OpenTitan-compatible Edalize 0.4.0")
    versions["launcher_python"] = sys.version.split()[0]
    versions["simulator_python"] = subprocess.check_output(
        [str(args.python_env.resolve() / "bin/python"), "--version"], text=True).strip()
    work = args.work_root.resolve()
    output = args.output.resolve()
    if work.exists() or output.exists():
        raise ValueError("work/output must be fresh directories; do not overwrite prior evidence")
    work.mkdir(parents=True)
    output.mkdir(parents=True)
    inputs = [args.protocol, pool_path, freeze_path,
              ROOT / protocol["cluster_path"], ROOT / "configs/coverage_schema.json",
              ROOT / "references/canonical_bin_catalog.json", ROOT / "references/canonical_bin_ids.txt"]
    inputs += [ROOT / "tools" / name for name in (
        "run_stage08_pilot.py", "test_sequences.py", "coverage_model.py", "cocotb_coverage_adapter.py",
        "run_stage05_corpus.py", "stage05_corpus.py", "AonMakefile", "aon_timer_tb.sv")]
    inputs += sorted((ROOT / "tools").glob("*.core"))
    report = {
        "schema": "aon-timer-stage08-positive-hit-pilot-v1", "status": "RUNNING",
        "started_utc": datetime.now(timezone.utc).isoformat(), "protocol": protocol,
        "source_revision": revision, "pool_sha256": pool_hash, "toolchain": versions,
        "project_commit_before_run": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "input_hash_policy": "sha256_of_lf_normalized_repository_text_bytes",
        "input_sha256": {path.relative_to(ROOT).as_posix(): input_sha256(path) for path in inputs},
        "canonical_identity_count": len(ids), "cluster_count": len(clusters),
        "paper_scheduler_enabled": False, "paper_equivalence_claimed": False,
        "attempts": [],
    }
    write_json(output / "protocol_snapshot.json", report)
    write_json(output / "summary.json", report)
    setup = ["fusesoc", f"--cores-root={source}", f"--cores-root={ROOT / 'tools'}", "run",
             "--target=default", "--tool=verilator", "--setup", f"--build-root={work / 'fusesoc'}",
             "lowrisc:ip:aon_timer"]
    code, timeout, elapsed = run_command(setup, ROOT, env, work / "setup.log", 300)
    report["setup"] = {"exit_code": code, "timed_out": timeout, "wall_seconds": elapsed,
                       "log_sha256": sha256_file(work / "setup.log")}
    if code:
        report["status"] = "SETUP_FAILED"
        write_json(output / "summary.json", report)
        return 1
    vc_files = list((work / "fusesoc").rglob("lowrisc_ip_aon_timer_0.1.vc"))
    if len(vc_files) != 1:
        raise ValueError("expected one FuseSoC Verilator file list")
    build = vc_files[0].parent
    lines = vc_files[0].read_text(encoding="utf-8").splitlines()
    filtered = [line for line in lines if not (line.startswith(("--Mdir ", "--top-module "))
                or line in {"--cc", "--exe", "--lint-only", "--Mdir", "--top-module"})]
    (build / "aon_timer_sources.vc").write_text("\n".join(filtered) + "\n", encoding="utf-8")
    report["generated_filelist_sha256"] = sha256_file(build / "aon_timer_sources.vc")
    observed = set()
    for number in range(1, budget + 1):
        testcase, phase, scores = select_action(arms, report["attempts"], protocol["exploration_coefficient"])
        run_id = f"{protocol['experiment_id']}-{number:03d}"
        attempt_out = output / f"attempt-{number:03d}"
        attempt_out.mkdir()
        attempt_work = work / f"attempt-{number:03d}"
        attempt_work.mkdir()
        trace_dir = attempt_work / "coverage-traces"
        trace_dir.mkdir()
        decision = {"run_id": run_id, "testcase": testcase, "seed": protocol["seed"], "phase": phase,
                    "completed_attempts_before_selection": len(report["attempts"]),
                    "observed_positive_count_before_selection": len(observed), "ucb_scores": scores,
                    "prior_attempt_sha256": (sha256_file(output / f"attempt-{number-1:03d}/attempt.json")
                                             if number > 1 else None)}
        write_json(attempt_out / "selection.json", decision)
        attempt_env = {**env, "RUN_ID": run_id, "RANDOM_SEED": str(protocol["seed"]),
                       "TESTCASE": testcase, "COVERAGE_TRACE_DIR": str(trace_dir)}
        result_path = build / "results.xml"
        if result_path.exists():
            result_path.unlink()  # A failed launch cannot inherit the preceding result.
        print(f"[{number}/{budget}] {phase}: {testcase}", flush=True)
        code, timed_out, elapsed = run_command(
            ["make", "-f", str(ROOT / "tools/AonMakefile"), "MODULE=test_sequences", "sim"],
            build, attempt_env, attempt_work / "simulation.log", protocol["timeout_seconds_per_attempt"])
        if result_path.is_file():
            shutil.copy2(result_path, attempt_work / "results.xml")
        error = None
        try:
            passed, cases, sim_ns, trace = collect_attempt(
                attempt_work, run_id, testcase, protocol["seed"], revision, protocol["coverage_schema_id"], code)
            hits = set(trace["resolved_canonical_bin_identity_hit_counts"])
            passed = passed and hits <= id_set and sim_ns <= protocol["simulation_time_limit_ns_per_attempt"]
        except (ValueError, KeyError, OSError, ET.ParseError) as exc:
            passed, cases, sim_ns, trace, hits = False, [], 0, {}, set()
            error = str(exc)
        if (attempt_work / "results.xml").is_file():
            try:
                export_results_xml(attempt_work / "results.xml", attempt_out / "results.xml",
                                   ((ROOT, "[project]"), (source, "[source]"),
                                    (work, "[work]"), (args.python_env.resolve(), "[python-env]")))
            except (OSError, ET.ParseError) as exc:
                passed, error = False, f"XML export failed: {type(exc).__name__}"
        new_hits = hits - observed if passed else set()
        if passed:
            observed.update(hits)
        sparse_vector = {
            "schema": "aon-timer-stage08-positive-only-vector-v1", "run_id": run_id,
            "source_revision": revision, "coverage_schema_id": protocol["coverage_schema_id"],
            "testcase": testcase, "seed": protocol["seed"], "result": "PASS" if passed else "FAIL",
            "canonical_identity_list_sha256": catalog["canonical_bin_ids_sha256"],
            "known_positive_identities": sorted(hits if passed else []),
            "unknown_count": len(ids) - (len(hits) if passed else 0), "inferred_misses": 0,
        }
        write_json(attempt_out / "positive_vector.json", sparse_vector)
        for path in sorted(trace_dir.glob("*.json")):
            target = attempt_out / "coverage-traces"
            target.mkdir(exist_ok=True)
            shutil.copy2(path, target / path.name)
        row = {**decision, "result": "PASS" if passed else "FAIL", "exit_code": code,
               "timed_out": timed_out, "wall_seconds": elapsed, "simulation_time_ns": sim_ns,
               "testcases": cases, "trace_summary": trace, "validation_error": error,
               "new_positive_identities": sorted(new_hits), "new_positive_count": len(new_hits),
               "cumulative_positive_count": len(observed), "cumulative_unknown_count": len(ids) - len(observed),
               "observed_cluster_ids": sorted({membership[identity] for identity in hits if identity in membership}),
               "reward": len(new_hits) / len(ids),
               "simulation_log_sha256": sha256_file(attempt_work / "simulation.log"),
               "raw_results_xml_sha256": (sha256_file(attempt_work / "results.xml")
                                          if (attempt_work / "results.xml").is_file() else None),
               "public_results_xml_sha256": (sha256_file(attempt_out / "results.xml")
                                             if (attempt_out / "results.xml").is_file() else None),
               "positive_vector_sha256": sha256_file(attempt_out / "positive_vector.json")}
        write_json(attempt_out / "attempt.json", row)
        report["attempts"].append(row)
        write_json(output / "summary.json", report)
        print(f"  {row['result']}; samples={trace.get('total_sample_count', 0)} new={len(new_hits)} total={len(observed)}", flush=True)
    report.update({"status": "PASS" if all(row["result"] == "PASS" for row in report["attempts"]) else "FAIL",
                   "completed_utc": datetime.now(timezone.utc).isoformat(), "attempts_used": len(report["attempts"]),
                   "known_positive_count": len(observed), "unknown_count": len(ids) - len(observed),
                   "inferred_misses": 0, "action_counts": dict(Counter(row["testcase"] for row in report["attempts"])),
                   "cumulative_positive_identities": sorted(observed)})
    report["inputs_unchanged_after_run"] = all(
        input_sha256(ROOT / name) == digest for name, digest in report["input_sha256"].items())
    if not report["inputs_unchanged_after_run"]:
        report["status"] = "FAIL_INPUT_CHANGED_DURING_RUN"
    write_json(output / "summary.json", report)
    with (output / "coverage_curve.csv").open("w", encoding="utf-8") as stream:
        stream.write("attempt,testcase,result,new_positives,cumulative_positives,unknown,reward\n")
        for index, row in enumerate(report["attempts"], 1):
            stream.write(f"{index},{row['testcase']},{row['result']},{row['new_positive_count']},{row['cumulative_positive_count']},{row['cumulative_unknown_count']},{row['reward']}\n")
    paths = sorted(path for path in output.rglob("*") if path.is_file())
    (output / "sha256.txt").write_text("".join(f"{sha256_file(path)}  {path.relative_to(output).as_posix()}\n" for path in paths), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "attempts_used", "known_positive_count", "unknown_count", "action_counts")}, indent=2))
    return 0 if report["status"] == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--python-env", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        return run(args)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"stage08 pilot: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
