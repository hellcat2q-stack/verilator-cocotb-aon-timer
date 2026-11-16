"""Prepare and audit an isolated VCS/Python timer-array boundary calibration.

This is a covergroup unit experiment, not an RTL/full run or a sample-timing
comparison.  The probe preserves the pinned timer_cfg_cg bins and enables
per-instance reporting on each independently sampled object.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARRAYS = {"bark": (32, "bark_thold_cp"), "bite": (32, "bite_thold_cp"),
          "prescale": (12, "prescale_cp"), "wkup": (64, "wkup_thold_cp")}
SOURCE_HASH = "c0ec937d68c335e2d05760268ce161eca1a40e7f8e50546156c0589882ed9b45"
REVISION = "9f20940d494a223cc950a5b98f748fb28109d458"


def native_bin_semantics(label: str, array: str, width: int) -> tuple:
    if label in (f"{array}_0", f"{array}_max"):
        value = 0 if label.endswith("_0") else 2 ** width - 1
        return label, value, value
    match = re.fullmatch(re.escape(array) + r"\[(0x[0-9a-fA-F]+|[0-9]+):(0x[0-9a-fA-F]+|[0-9]+)\]", label)
    if not match:
        raise ValueError(f"native bin has no explicit interval: {label}")
    def number(value):
        return int(value, 16 if value.startswith("0x") else 10)
    low, high = number(match[1]), number(match[2])
    if not 0 <= low <= high < 2 ** width:
        raise ValueError("native bin range is invalid")
    return "array", low, high


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.with_suffix(path.suffix + ".sha256").write_text(f"{digest(path)}  {path.name}\n", encoding="ascii")


def boundary_cases(catalog: dict) -> tuple[list[dict], list[dict]]:
    cases, invalid = [], []
    for array, records in catalog["arrays"].items():
        width, coverpoint = ARRAYS[array]
        for record in records:
            low, high = record["value_range"]
            for offset, value in enumerate((low - 1, low, high, high + 1)):
                case = {"case_id": f"{array}_{record['ordinal']:02d}_{offset}", "array": array,
                        "width": width, "coverpoint": coverpoint, "value": value}
                if not 0 <= value < 2 ** width:
                    invalid.append({**case, "reason": "OUTSIDE_SV_FIELD_DOMAIN_NOT_TRUNCATED"})
                    continue
                cases.append(case)
    return cases, invalid


def prepare(source_file: Path, output_dir: Path) -> dict:
    if digest(source_file) != SOURCE_HASH:
        raise ValueError("covergroup source does not match the pinned source hash")
    text = source_file.read_text(encoding="utf-8")
    match = re.search(r"  covergroup timer_cfg_cg\b.*?  endgroup : timer_cfg_cg", text, re.S)
    if not match:
        raise ValueError("timer_cfg_cg declaration is missing")
    declaration = match.group(0)
    catalog_path = ROOT / "references/array_bin_ranges.v1.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    cases, invalid = boundary_cases(catalog)
    instrumented = declaration.replace("    prescale_cp:", "    option.per_instance = 1;\n    prescale_cp:", 1)
    lines = ["// Copyright lowRISC contributors (OpenTitan project).",
             "// SPDX-License-Identifier: Apache-2.0", "class array_probe_holder;", instrumented,
             "  function new(string name);", "    timer_cfg_cg = new(name);",
             "    timer_cfg_cg.set_inst_name(name);",
             "  endfunction", "endclass", "module aon_array_boundary_probe;",
             f"  array_probe_holder probes[{len(cases)}];", "  initial begin"]
    for index, case in enumerate(cases):
        values = {"prescale": 0, "bark": 0, "bite": 0, "wkup": 0}
        values[case["array"]] = case["value"]
        args = [f"{ARRAYS[key][0]}'h{values[key]:x}" for key in ("prescale", "bark", "bite", "wkup")]
        args += ["1'b1", "1'b0", "1'b0"]
        lines += [f"    probes[{index}] = new(\"{case['case_id']}\");",
                  f"    probes[{index}].timer_cfg_cg.sample({', '.join(args)});"]
    lines += [f'    $display("ARRAY_BOUNDARY_PROBE_DONE cases={len(cases)}");', "    $finish;",
              "  end", "endmodule"]
    output_dir.mkdir(parents=True, exist_ok=False)
    source_out = output_dir / "probe.sv"
    source_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    plan = {"schema": "aon-timer-vcs-array-boundary-probe-plan-v1", "source_revision": REVISION,
            "source_file_sha256": SOURCE_HASH,
            "verbatim_covergroup_sha256": hashlib.sha256(declaration.encode()).hexdigest(),
            "reporting_instrumentation": "option.per_instance = 1 inserted in the declaration; bin definitions unchanged",
            "array_reference_sha256": digest(catalog_path), "probe_source_sha256": digest(source_out),
            "case_count": len(cases), "unrepresentable_case_count": len(invalid),
            "cases": cases, "unrepresentable_cases": invalid,
            "full_simulation_started": False, "coverage_credit_granted": 0}
    write_json(output_dir / "plan.json", plan)
    return plan


def audit(plan_path: Path, observations_path: Path) -> dict:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    observed = json.loads(observations_path.read_text(encoding="utf-8"))
    attestation_path = observations_path.with_name("attestation.json")
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    catalog_path = ROOT / "references/array_bin_ranges.v1.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    expected_cases, expected_invalid = boundary_cases(catalog)
    if (plan.get("schema") != "aon-timer-vcs-array-boundary-probe-plan-v1"
            or plan.get("source_revision") != REVISION or plan.get("source_file_sha256") != SOURCE_HASH
            or plan.get("array_reference_sha256") != digest(catalog_path)
            or plan.get("cases") != expected_cases or plan.get("unrepresentable_cases") != expected_invalid
            or plan.get("case_count") != 636 or plan.get("unrepresentable_case_count") != 4):
        raise ValueError("probe plan does not match pinned source/reference")
    if (observed.get("schema") != "aon-timer-vcs-array-boundary-observations-v1"
            or observed.get("plan_sha256") != digest(plan_path)
            or observed.get("probe_source_sha256") != plan.get("probe_source_sha256")
            or observed.get("server_pinned_source_sha256") != SOURCE_HASH
            or observed.get("compile_exit_code") != 0 or observed.get("simulation_exit_code") != 0):
        raise ValueError("probe did not complete or does not match the plan")
    if (attestation.get("schema") != "aon-timer-vcs-array-probe-attestation-v1"
            or attestation.get("observations_sha256") != digest(observations_path)
            or attestation.get("plan_sha256") != digest(plan_path)
            or attestation.get("probe_source_sha256") != plan.get("probe_source_sha256")
            or attestation.get("runner_sha256") != digest(ROOT / "tools/run_vcs_array_boundary_probe.py")
            or attestation.get("compile_exit_code") != 0 or attestation.get("simulation_exit_code") != 0
            or not str(attestation.get("vcs_runtime_version", "")).startswith("P-2019.06-SP1")
            or attestation.get("historical_hit_counts_imported") is not False):
        raise ValueError("native VCS calibration attestation is missing or inconsistent")
    rows = observed.get("cases", [])
    indexed = {row["case_id"]: row for row in rows}
    if len(indexed) != len(rows) or set(indexed) != {case["case_id"] for case in plan["cases"]}:
        raise ValueError("probe observations are missing, duplicated, or unexpected")
    results = []
    for case in plan["cases"]:
        array, value = case["array"], case["value"]
        expected = [f"{array}[{row['ordinal']}]" for row in catalog["arrays"][array]
                    if row["value_range"][0] <= value <= row["value_range"][1]]
        expected_semantics = [("array", *row["value_range"]) for row in catalog["arrays"][array]
                              if row["value_range"][0] <= value <= row["value_range"][1]]
        if value == 0:
            expected.append(f"{array}_0")
            expected_semantics.append((f"{array}_0", 0, 0))
        if value == 2 ** case["width"] - 1:
            expected.append(f"{array}_max")
            expected_semantics.append((f"{array}_max", value, value))
        observation = indexed[case["case_id"]]
        actual = sorted(observation["hit_bin_names"])
        actual_semantics = sorted(native_bin_semantics(label, array, case["width"]) for label in actual)
        results.append({**case, "python_expected_bin_names": sorted(expected),
                        "vcs_observed_bin_names": actual,
                        "python_expected_semantic_bins": sorted(expected_semantics),
                        "vcs_observed_semantic_bins": actual_semantics,
                        "passed": sorted(expected_semantics) == actual_semantics})
    passed = all(row["passed"] for row in results) and len(results) == 636
    return {"schema": "aon-timer-vcs-array-boundary-parity-audit-v1",
            "status": "PASS" if passed else "FAIL", "source_revision": REVISION,
            "vcs_python_array_boundary_parity_verified": passed,
            "vcs_run_provenance_verified": True,
            "case_count": len(results), "cases_passed": sum(row["passed"] for row in results),
            "unrepresentable_cases_rejected_without_truncation": plan["unrepresentable_case_count"],
            "native_verilator_covergroup_verified": False, "uvm_sample_timing_parity_verified": False,
            "coverage_credit_granted": 0, "full_simulation_started": False,
            "inputs": {"plan_sha256": digest(plan_path), "observations_sha256": digest(observations_path),
                       "array_reference_sha256": digest(catalog_path),
                       "attestation_sha256": digest(attestation_path)}, "cases": results,
            "audit_tool_sha256": digest(Path(__file__)),
            "note": "Isolated official covergroup boundary experiment. No historical hits or RTL coverage imported."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--source-file", type=Path, required=True)
    prep.add_argument("--output-dir", type=Path, required=True)
    check = sub.add_parser("audit")
    check.add_argument("--plan", type=Path, required=True)
    check.add_argument("--observations", type=Path, required=True)
    check.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.source_file, args.output_dir)
        print(json.dumps({"case_count": result["case_count"], "unrepresentable_cases": result["unrepresentable_case_count"]}))
    else:
        result = audit(args.plan, args.observations)
        write_json(args.output, result)
        print(json.dumps({"status": result["status"], "cases_passed": result["cases_passed"]}))
        if result["status"] != "PASS":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
