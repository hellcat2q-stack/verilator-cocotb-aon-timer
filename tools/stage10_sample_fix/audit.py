"""Validate a declared reference fix and compare independent RTL samples, fail closed."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

try:
    from tools.stage10_sample_parity.audit import compare_case
except ModuleNotFoundError:
    from stage10_sample_parity.audit import compare_case

PROJECT = Path(__file__).resolve().parents[2]
FIXES = ["reset-fork-isolation", "wakeup-high-word-read", "named-event-wait"]
VARIANT = "pinned-sampling-fixes-v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def bounded_match(cases: list[dict]) -> bool:
    return len(cases) == 3 and all(
        c["reference_status"] == c["cocotb_status"] == "PASS"
        and c["accepted_tl_inputs_and_times_equal"]
        and c["tl_response_callbacks_and_read_values_equal"]
        and c["aon_edge_timestamps_equal"]
        and c["rtl_counters_and_output_pins_at_aon_edges_equal"]
        and c["producer_events_are_unique"]
        and c["samples"]["same_time_multisets_equal"]
        and bool(c["samples"]["groups"])
        and all(g["ordered_tuples_and_times_equal"] for g in c["samples"]["groups"].values())
        for c in cases)


def audit_evidence(root: Path) -> dict:
    root = Path(root)
    read = lambda name: json.loads((root / name).read_text())
    manifest, execution = read("cocotb-manifest.json"), read("execution.json")
    instrument, post, attest = (read(name) for name in ("instrumentation.json", "post-build-source.json", "source-attestation.json"))
    export, probe = read("cocotb-export.json"), read("event-probe.json")
    require(attest["revision"] == manifest["source_revision"] == "9f20940d494a223cc950a5b98f748fb28109d458", "Pinned revision mismatch")
    require(attest["all_exported_git_blobs_match"] and post["all_source_blobs_match_except_declared_patch"] and manifest["source_clean"], "Source attestation failed")
    require(instrument["reference_logic_fixes"] == FIXES and instrument["files"] == post["declared_changed_files"], "Undeclared reference changes")
    require(instrument["reference_variant"] == execution["reference_variant"] == manifest["reference_variant"] == VARIANT, "Reference variant mismatch")
    require(execution["process_exit_code"] == execution["build_exit_code"] == 0, "Reference build/runner failed")
    require(execution["cdc_disable_define_in_actual_compile_argv"], "CDC build define missing")
    require(probe["process_exit_code"] == probe["build_exit_code"] == 0 and probe["producer_count"] == probe["named_event_wait_count"] == 5, "Native event probe failed")
    require(probe["property_wait_count"] == 1, "Event-property observation differs from this VCS diagnostic")
    require(probe["source_sha256"] == sha(Path(__file__).with_name("event_wait_probe.sv")), "Event probe source changed")
    fork_probe = read("fork-probe.json")
    require(fork_probe["build_exit_code"] == fork_probe["process_exit_code"] == 0
        and fork_probe["tick_count"] == fork_probe["isolated_count"] == 5
        and fork_probe["original_count"] == 10, "Native fork-cleanup A/B probe failed")
    require(fork_probe["source_sha256"] == sha(Path(__file__).with_name("fork_cleanup_probe.sv")), "Fork probe source changed")
    for name, expected in manifest["tools_sha256"].items():
        require(sha(PROJECT / name) == expected, "Cocotb capture tool changed: " + name)
    tools = {"instrument.py": "tools/stage10_sample_fix/instrument.py",
        "instrument_base.py": "tools/stage10_sample_parity/instrument.py",
        "run_vcs.sh": "tools/stage10_sample_parity/run_vcs.sh",
        "collect_vcs.py": "tools/stage10_sample_parity/collect_vcs.py",
        "aon_timer_smoke_vseq.sv": "tools/stage10_sample_parity/aon_timer_smoke_vseq.sv",
        "verify_source.py": "tools/stage10_sample_parity/verify_source.py",
        "stage10-paired-short-v1.json": "configs/stage10-paired-short-v1.json",
        "stage10-sample-fix-v1.json": "configs/stage10-sample-fix-v1.json"}
    for name, path in tools.items():
        require(sha(PROJECT / path) == execution["inputs_sha256"][name], "VCS capture input changed: " + name)
    require(execution["collector_tool_sha256"] == sha(Path(__file__).with_name("collect_run.py")), "Execution collector changed")
    require(post["verification_tool_sha256"] == sha(PROJECT / tools["verify_source.py"]), "Source verifier changed")
    inputs = {name: sha(root / name) for name in ("cocotb-manifest.json", "execution.json", "instrumentation.json", "instrumentation.patch", "reference-fixes.patch", "post-build-source.json", "source-attestation.json", "event-probe.json", "fork-probe.json", "simv.sha256", "cocotb-export.json")}
    cases = []
    for case in range(3):
        folder = root / f"cocotb-case-{case}"
        vcs, replay = read(f"vcs-case-{case}.json"), json.loads((folder / "replay.json").read_text())
        trace_path = folder / replay["raw_adapter_trace_filename"]
        trace = json.loads(trace_path.read_text())
        require(trace["schema_id"] == "aon_timer_pinned_sampling_fix_trace_v1" and trace["source_variant"] == VARIANT, "Unexpected adapter/schema variant")
        require(trace["coverage_credit_granted"] == 0 and trace["canonical_bin_vector"] is None, "Diagnostic cannot grant canonical credit")
        run = manifest["cases"][case]
        require(sha(folder / "replay.json") == run["files_sha256"]["replay.json"], "Replay hash mismatch")
        require(sha(trace_path) == run["files_sha256"]["traces/" + trace_path.name], "Trace hash mismatch")
        require(export["cases"][case]["original_xml_sha256"] == run["files_sha256"]["results.xml"] and export["cases"][case]["public_xml_sha256"] == sha(folder / "results.xml"), "XML export hash mismatch")
        tests = ET.parse(folder / "results.xml").findall(".//testcase")
        require(len(tests) == 1 and all(t.find("failure") is None and t.find("error") is None for t in tests), "Cocotb XML failed")
        require(vcs["process_exit_code"] == vcs["uvm_error_count"] == vcs["uvm_fatal_count"] == 0 and vcs["test_passed_checks"], "VCS testcase failed")
        for path in (root / f"vcs-case-{case}.json", folder / "replay.json", trace_path, folder / "results.xml"):
            inputs[path.relative_to(root).as_posix()] = sha(path)
        result = compare_case(vcs, replay, trace)
        result["cocotb_status"] = run["run_status"]
        # Preserve exact producer multiplicity: fixes must not simply hide duplicates.
        result["producer_events"] = vcs["control_events"]
        keys = [json.dumps(r, sort_keys=True) for r in vcs["control_events"]]
        result["producer_events_are_unique"] = all(n == 1 for n in Counter(keys).values())
        expected_groups = {"timer_cfg_cg", "intr_cg", "intr_pins_cg"} | ({"wake_up_timer_thold_hit_cg"} if case == 0 else {"watchdog_timer_bark_thold_hit_cg", "watchdog_timer_bite_thold_hit_cg"})
        require(set(result["samples"]["groups"]) == expected_groups, "Expected short-case sample groups are missing")
        cases.append(result)
    matches = bounded_match(cases)
    return {"schema": "aon-timer-pinned-sample-fix-audit-v1", "source_revision": attest["revision"],
        "reference_variant": VARIANT, "reference_logic_fixes": FIXES,
        "audit_tool_sha256": sha(Path(__file__)),
        "comparison_tool_sha256": sha(PROJECT / "tools/stage10_sample_parity/audit.py"),
        "source_export_verified": True, "post_build_source_verified": True,
        "status": "BOUNDED_FIXED_REFERENCE_MATCH" if matches else "DIFFERENCES_OBSERVED",
        "fixed_reference_short_cases_match": matches,
        "original_reference_parity_verified": False, "complete_parity_verified": False,
        "full_simulation_started": False, "coverage_credit_granted": 0, "full_coverage_rate": None,
        "scope": "Three unchanged deterministic short cases with declared fixes; equality required within each group and at each timestamp. Cross-group same-time invocation order is reported separately. Update/prescale/sleep/reset/shared matrix is not covered.",
        "inputs_sha256": inputs, "event_probe": probe, "fork_probe": fork_probe, "cases": cases}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_evidence(args.evidence_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    args.output.with_suffix(args.output.suffix + ".sha256").write_text(sha(args.output) + "  " + args.output.name + "\n")


if __name__ == "__main__":
    main()
