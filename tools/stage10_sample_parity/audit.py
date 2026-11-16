"""Compare independently captured actual samples; preserve all discrepancies."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from .instrument import GROUP_FIELDS


def canonical_samples(records: list[dict], cocotb: bool = False) -> list[dict]:
    result = []
    for record in records:
        if cocotb:
            group = record["covergroup"]
            fields = record["fields"]
            time = round(record["simulation_time_ns"] * 1000)
        else:
            if record["kind"] != "sample":
                continue
            group = record["group"]
            fields = {key: record[key] for key in GROUP_FIELDS[group]}
            time = record["time_ps"]
        result.append({"group": group, "time_ps": time, "fields": fields})
    return result


def compare_samples(left: list[dict], right: list[dict]) -> dict:
    groups = sorted({r["group"] for r in left + right})
    result = {}
    for group in groups:
        uvm = [r for r in left if r["group"] == group]
        python = [r for r in right if r["group"] == group]
        a_times = Counter(r["time_ps"] for r in uvm)
        b_times = Counter(r["time_ps"] for r in python)
        a_buckets, b_buckets = defaultdict(list), defaultdict(list)
        for r in uvm:
            a_buckets[r["time_ps"]].append(r["fields"])
        for r in python:
            b_buckets[r["time_ps"]].append(r["fields"])
        diffs = []
        for time in sorted(a_buckets.keys() & b_buckets.keys()):
            for index, (a, b) in enumerate(zip(a_buckets[time], b_buckets[time])):
                different = {k: {"uvm": a[k], "cocotb": b[k]} for k in a if a[k] != b[k]}
                if different:
                    diffs.append({"time_ps": time, "same_time_index": index, "fields": different})
        result[group] = {"uvm_count": len(uvm), "cocotb_count": len(python),
            "ordered_tuples_and_times_equal": uvm == python,
            "same_time_multisets_equal": Counter(json.dumps(r, sort_keys=True) for r in uvm) == Counter(json.dumps(r, sort_keys=True) for r in python),
            "only_uvm_times_ps": list((a_times - b_times).elements()),
            "only_cocotb_times_ps": list((b_times - a_times).elements()),
            "matched_time_field_differences": diffs}
    return {"groups": result, "global_invocation_order_equal": left == right,
            "same_time_multisets_equal": Counter(json.dumps(r, sort_keys=True) for r in left) == Counter(json.dumps(r, sort_keys=True) for r in right)}


def compare_case(vcs: dict, replay: dict, trace: dict) -> dict:
    begin, end = (next(r["time_ps"] for r in vcs["records"] if r["kind"] == kind) for kind in ("begin", "end"))
    uvm_samples = [r for r in canonical_samples(vcs["records"]) if begin <= r["time_ps"] <= end]
    python_samples = [r for r in canonical_samples(trace["samples"], True) if begin <= r["time_ps"] <= end]
    edges = {r["time_ps"]: r for r in vcs["records"] if r["kind"] == "edge" and begin <= r["time_ps"] <= end}
    other = {r["time_ps"]: r for r in replay["edge_records"] if begin <= r["time_ps"] <= end}
    edge_diffs = [{"time_ps": time, "fields": {key: {"uvm": edges[time][key], "cocotb": other[time][key]}
                  for key in edges[time] if edges[time][key] != other[time][key]}}
                  for time in sorted(edges.keys() & other.keys()) if edges[time] != other[time]]
    key = lambda r: (r["time_ps"], r["channel"], r["write"], r["address"], r["data"], r["response"] if not r["write"] and r["channel"] == 1 else 0)
    uvm_bus = [r for r in vcs["records"] if r["kind"] == "tl"]
    expected_a = [key(r) for r in uvm_bus if r["channel"] == 0]
    actual_a = [key(r) for r in replay["bus_records"] if r["channel"] == 0]
    expected_d = [key(r) for r in uvm_bus if r["channel"] == 1]
    actual_d = [key(r) for r in replay["bus_records"] if r["channel"] == 1]
    controls = defaultdict(list)
    for r in vcs["control_events"]:
        controls[(r["label"], r["time_ps"])].append(r["kind"])
    label_group = {"WKUP": "wake_up_timer_thold_hit_cg", "WDOG Bark": "watchdog_timer_bark_thold_hit_cg", "WDOG Bite": "watchdog_timer_bite_thold_hit_cg"}
    simultaneous = [{"label": label, "time_ps": time, "control_events": kinds,
        "actual_sample_invocations": sum(r["group"] == label_group[label] and r["time_ps"] == time for r in uvm_samples)}
        for (label, time), kinds in controls.items() if "count" in kinds and "expiry" in kinds]
    return {"case": vcs["case"], "reference_status": vcs["run_status"],
        "uvm_sample_count_in_body": len(uvm_samples), "cocotb_sample_count_in_body": len(python_samples),
        "accepted_tl_inputs_and_times_equal": expected_a == actual_a,
        "tl_response_callbacks_and_read_values_equal": expected_d == actual_d,
        "edge_observation_count": len(edges),
        "aon_edge_timestamps_equal": edges.keys() == other.keys(),
        "rtl_counters_and_output_pins_at_aon_edges_equal": edges.keys() == other.keys() and not edge_diffs,
        "edge_differences": edge_diffs, "simultaneous_count_expiry": simultaneous,
        "samples": compare_samples(uvm_samples, python_samples)}


def audit_evidence(root: Path) -> dict:
    root = Path(root)
    manifest = json.loads((root / "cocotb-manifest.json").read_text())
    export = json.loads((root / "cocotb-export.json").read_text())
    attempts = json.loads((root / "attempts.json").read_text())
    instrumentation = json.loads((root / "instrumentation.json").read_text())
    inputs = {}
    for name in ("cocotb-manifest.json", "cocotb-export.json", "attempts.json", "instrumentation.json", "instrumentation.patch", "source-attestation.json", "simv.sha256", "toolchain.json", "post-build-source.json"):
        inputs[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    for name, expected in manifest["tools_sha256"].items():
        actual = hashlib.sha256((Path(__file__).resolve().parents[2] / name).read_bytes()).hexdigest()
        if expected != actual:
            raise ValueError("Cocotb runtime tool changed since capture: " + name)
    for name in ("instrument.py", "run_vcs.sh", "collect_vcs.py", "aon_timer_smoke_vseq.sv"):
        actual = hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        if actual != attempts["attempts"][-1]["inputs_sha256"][name]:
            raise ValueError("VCS capture tool changed since execution: " + name)
    cases = []
    for case in range(3):
        paths = [root / f"vcs-case-{case}.json", root / f"cocotb-case-{case}" / "replay.json"]
        replay = json.loads(paths[1].read_text())
        paths.append(paths[1].with_name(replay["raw_adapter_trace_filename"]))
        for path in paths:
            inputs[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        case_result = compare_case(json.loads(paths[0].read_text()), replay, json.loads(paths[2].read_text()))
        run = manifest["cases"][case]
        case_result["cocotb_status"] = run["run_status"]
        # Verify exported files against original execution manifest hashes.
        if inputs[str(paths[1].relative_to(root))] != run["files_sha256"]["replay.json"]:
            raise ValueError("Replay evidence does not match execution hash")
        if inputs[str(paths[2].relative_to(root))] != run["files_sha256"]["traces/" + paths[2].name]:
            raise ValueError("Trace evidence does not match execution hash")
        xml_path = paths[1].with_name("results.xml")
        xml_hash = hashlib.sha256(xml_path.read_bytes()).hexdigest()
        inputs[str(xml_path.relative_to(root))] = xml_hash
        if export["cases"][case]["original_xml_sha256"] != run["files_sha256"]["results.xml"] or export["cases"][case]["public_xml_sha256"] != xml_hash:
            raise ValueError("Result XML export hash mismatch")
        tests = ET.parse(xml_path).findall(".//testcase")
        if len(tests) != 1 or tests[0].find("failure") is not None or tests[0].find("error") is not None:
            raise ValueError("Public Cocotb XML does not confirm a passing testcase")
        cases.append(case_result)
    attestation = json.loads((root / "source-attestation.json").read_text())
    post_build = json.loads((root / "post-build-source.json").read_text())
    if (not post_build["all_source_blobs_match_except_declared_patch"] or
        instrumentation["reference_logic_fixes"] or
        instrumentation["files"] != post_build["declared_changed_files"]):
        raise ValueError("Post-build source differs from the declared pinned variant")
    valid_pairs = (attestation["revision"] == manifest["source_revision"] == "9f20940d494a223cc950a5b98f748fb28109d458"
        and attestation["all_exported_git_blobs_match"] and manifest["source_clean"]
        and all(c["reference_status"] == c["cocotb_status"] == "PASS" and c["accepted_tl_inputs_and_times_equal"] for c in cases))
    result = {"schema": "aon-timer-independent-actual-sample-audit-v1",
        "source_revision": attestation["revision"],
        "audit_tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_export_verified_before_declared_instrumentation": attestation["all_exported_git_blobs_match"],
        "post_build_source_matches_declared_variant": True,
        "valid_independent_short_pairs": valid_pairs,
        "status": ("DIFFERENCES_OBSERVED" if any(not c["samples"]["same_time_multisets_equal"] for c in cases) else "BOUNDED_CASES_MATCH") if valid_pairs else "VALIDATION_FAILED",
        "complete_parity_verified": False, "full_simulation_started": False,
        "coverage_credit_granted": 0, "full_coverage_rate": None,
        "alignment": "Absolute ps timeline replay, translation 0; same AON and fast clock phase and accepted TL timestamps. RTL probes are observed after settling; UVM samples retain their original simulator region.",
        "scope": "Three explicit short cases with original reference logic, all nine AON scoreboard sample sites instrumented; shared covergroups and update/sleep/prescaler matrix remain outside this diagnostic.",
        "inputs_sha256": inputs, "cases": cases}
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit_evidence(args.evidence_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    args.output.with_suffix(args.output.suffix + ".sha256").write_text(
        hashlib.sha256(args.output.read_bytes()).hexdigest() + "  " + args.output.name + "\n")


if __name__ == "__main__":
    main()
