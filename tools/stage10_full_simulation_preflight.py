"""Record the full-simulation start gate without launching a simulation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from tools.classify_source_definitions import (
        ARRAY_PARTITION_AUDIT_PATH,
        ARRAY_RANGE_PATH,
        CATALOG_PATH,
        CANONICAL_IDS_PATH,
        CANONICAL_CATALOG_PATH,
        SCHEMA_PATH,
        load_array_reference,
        load_catalog,
    )
except ModuleNotFoundError:
    from classify_source_definitions import (
        ARRAY_PARTITION_AUDIT_PATH,
        ARRAY_RANGE_PATH,
        CATALOG_PATH,
        CANONICAL_IDS_PATH,
        CANONICAL_CATALOG_PATH,
        SCHEMA_PATH,
        load_array_reference,
        load_catalog,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACE_ROOT = ROOT / "evidence" / "stage09_comparison" / "2026-11-14-v1"
DEFAULT_REPLAY_AUDIT = DEFAULT_TRACE_ROOT / "replay-audit.json"
DEFAULT_STAGE06_MATRIX_AUDIT = (
    ROOT / "evidence" / "stage06_count_event_v2_verified" / "matrix"
    / "coverage_matrix_audit.json"
)
DEFAULT_STAGE08_READINESS = (
    ROOT / "evidence" / "stage08_preflight" / "2026-11-14-full-paper-scope"
    / "readiness.json"
)
DEFAULT_CLASSIFICATION = (
    ROOT / "evidence" / "stage10_source_definition_classification"
    / "2026-11-16-v2" / "classification.json"
)
DEFAULT_IDENTITY_BRIDGE = (
    ROOT / "evidence" / "stage10_identity_bridge"
    / "2026-11-16-v1" / "bridge.json"
)
DEFAULT_SAMPLE_SITE_AUDIT = (
    ROOT / "evidence" / "stage10_sample_site_audit"
    / "2026-11-16-v2" / "sample-site-audit.json"
)
DEFAULT_LEGACY_VECTOR_HEADER_AUDIT = (
    ROOT / "evidence" / "stage10_legacy_vector_header_bridge"
    / "2026-11-16-v1" / "audit.json"
)
DEFAULT_ARRAY_VCS_BOUNDARY_AUDIT = (
    ROOT / "evidence" / "stage10_vcs_array_boundary"
    / "2026-11-16-v1" / "audit.json"
)
DEFAULT_UVM_TIMING_SHAPE_AUDIT = (
    ROOT / "evidence" / "stage10_uvm_vcs_timing"
    / "2026-11-16-v2" / "audit.json"
)
DEFAULT_ACTUAL_SAMPLE_AUDIT = (
    ROOT / "evidence" / "stage10_independent_sample_parity"
    / "2026-11-16-v1" / "audit.json"
)
DEFAULT_SAMPLE_FIX_AUDIT = (
    ROOT / "evidence" / "stage10_sample_fix" / "2026-11-16-v1" / "audit.json"
)
DEFAULT_OUTPUT = (
    ROOT / "evidence" / "stage10_full_simulation_preflight"
    / "2026-11-16-v6" / "preflight.json"
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path.name}")
    return value


def _relative(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return Path(path).name


def build_preflight(
    *,
    trace_root: Path = DEFAULT_TRACE_ROOT,
    replay_audit_path: Path = DEFAULT_REPLAY_AUDIT,
    stage06_matrix_audit_path: Path = DEFAULT_STAGE06_MATRIX_AUDIT,
    stage08_readiness_path: Path = DEFAULT_STAGE08_READINESS,
    classification_path: Path = DEFAULT_CLASSIFICATION,
    identity_bridge_path: Path = DEFAULT_IDENTITY_BRIDGE,
    sample_site_audit_path: Path = DEFAULT_SAMPLE_SITE_AUDIT,
    legacy_vector_header_audit_path: Path = DEFAULT_LEGACY_VECTOR_HEADER_AUDIT,
    array_vcs_boundary_audit_path: Path = DEFAULT_ARRAY_VCS_BOUNDARY_AUDIT,
    uvm_timing_shape_audit_path: Path = DEFAULT_UVM_TIMING_SHAPE_AUDIT,
    actual_sample_audit_path: Path = DEFAULT_ACTUAL_SAMPLE_AUDIT,
    sample_fix_audit_path: Path = DEFAULT_SAMPLE_FIX_AUDIT,
) -> dict[str, Any]:
    catalog, catalog_hash = load_catalog(CATALOG_PATH)
    array_definitions, array_reference = load_array_reference(catalog)
    canonical_ids = CANONICAL_IDS_PATH.read_text(encoding="utf-8").splitlines()
    array_catalog = read_json(ARRAY_RANGE_PATH)
    partition_audit = read_json(ARRAY_PARTITION_AUDIT_PATH)
    stage06 = read_json(stage06_matrix_audit_path)
    stage08 = read_json(stage08_readiness_path)
    replay = read_json(replay_audit_path)
    classification = read_json(classification_path)
    identity_bridge = read_json(identity_bridge_path)
    sample_site_audit = read_json(sample_site_audit_path)
    timing_shape = read_json(uvm_timing_shape_audit_path)
    actual_samples = read_json(actual_sample_audit_path)
    actual_samples_hash = sha256_file(actual_sample_audit_path)
    actual_sidecar = Path(str(actual_sample_audit_path) + ".sha256").read_text(encoding="ascii").split()
    if actual_sidecar != [actual_samples_hash, Path(actual_sample_audit_path).name]:
        raise ValueError("Actual sample audit SHA-256 sidecar mismatch")
    try:
        from tools.stage10_sample_parity.audit import audit_evidence as replay_actual_samples
    except ModuleNotFoundError:
        from stage10_sample_parity.audit import audit_evidence as replay_actual_samples
    if actual_samples != replay_actual_samples(Path(actual_sample_audit_path).parent):
        raise ValueError("Actual sample audit does not replay from independently captured evidence")
    if not actual_samples["valid_independent_short_pairs"] or actual_samples["complete_parity_verified"]:
        raise ValueError("Three short diagnostic pairs cannot establish complete sampling parity")
    sample_fix = read_json(sample_fix_audit_path)
    sample_fix_hash = sha256_file(sample_fix_audit_path)
    fix_sidecar = Path(str(sample_fix_audit_path) + ".sha256").read_text(encoding="ascii").split()
    if fix_sidecar != [sample_fix_hash, Path(sample_fix_audit_path).name]:
        raise ValueError("Fixed-reference sample audit SHA-256 sidecar mismatch")
    try:
        from tools.stage10_sample_fix.audit import audit_evidence as replay_sample_fix
    except ModuleNotFoundError:
        from stage10_sample_fix.audit import audit_evidence as replay_sample_fix
    if sample_fix != replay_sample_fix(Path(sample_fix_audit_path).parent):
        raise ValueError("Fixed-reference sample audit does not replay from captured evidence")
    if sample_fix["original_reference_parity_verified"] or sample_fix["complete_parity_verified"]:
        raise ValueError("A repaired reference and three short cases do not establish original/full parity")
    timing_shape_hash = sha256_file(uvm_timing_shape_audit_path)
    timing_sidecar = Path(str(uvm_timing_shape_audit_path) + ".sha256").read_text(encoding="ascii").split()
    if timing_sidecar != [timing_shape_hash, Path(uvm_timing_shape_audit_path).name]:
        raise ValueError("UVM timing shape audit SHA-256 sidecar mismatch")
    try:
        from tools.audit_uvm_vcs_timing import audit_evidence as replay_timing_shape
    except ModuleNotFoundError:
        from audit_uvm_vcs_timing import audit_evidence as replay_timing_shape
    if timing_shape != replay_timing_shape(Path(uvm_timing_shape_audit_path).parent):
        raise ValueError("UVM timing shape audit does not replay from diagnostic evidence")
    timing_shape_verified = (
        timing_shape.get("status") == "PASS"
        and timing_shape.get("count_event_shape_comparison_complete") is True
        and timing_shape.get("independent_uvm_vcs_timing_comparison_complete") is False
        and timing_shape.get("covergroup_sample_invocations_observed") is False
        and timing_shape.get("coverage_credit_granted") == 0
    )
    legacy_headers = read_json(legacy_vector_header_audit_path)
    array_boundary = read_json(array_vcs_boundary_audit_path)
    boundary_hash = sha256_file(array_vcs_boundary_audit_path)
    boundary_sidecar = Path(str(array_vcs_boundary_audit_path) + ".sha256").read_text(encoding="ascii").split()
    if boundary_sidecar != [boundary_hash, Path(array_vcs_boundary_audit_path).name]:
        raise ValueError("VCS array boundary audit SHA-256 sidecar is inconsistent")
    try:
        from tools.vcs_array_boundary_probe import audit as replay_array_boundary
    except ModuleNotFoundError:
        from vcs_array_boundary_probe import audit as replay_array_boundary
    boundary_dir = Path(array_vcs_boundary_audit_path).parent
    boundary_replay = replay_array_boundary(boundary_dir / "plan.json", boundary_dir / "observations.json")
    # JSON serializes semantic tuples as lists; compare normalized objects.
    if array_boundary != json.loads(json.dumps(boundary_replay)):
        raise ValueError("VCS array boundary audit does not replay from native observations")
    array_vcs_python_parity_verified = (
        array_boundary.get("status") == "PASS"
        and array_boundary.get("vcs_python_array_boundary_parity_verified") is True
        and array_boundary.get("vcs_run_provenance_verified") is True
        and array_boundary.get("cases_passed") == 636
        and array_boundary.get("unrepresentable_cases_rejected_without_truncation") == 4
        and array_boundary.get("coverage_credit_granted") == 0
    )
    legacy_headers_hash = sha256_file(legacy_vector_header_audit_path)
    header_sidecar = Path(str(legacy_vector_header_audit_path) + ".sha256").read_text(encoding="ascii").split()
    if header_sidecar != [legacy_headers_hash, Path(legacy_vector_header_audit_path).name]:
        raise ValueError("legacy vector header audit SHA-256 sidecar is missing or inconsistent")
    legacy_headers_valid = (
        legacy_headers.get("schema") == "aon-timer-legacy-vector-header-bridge-audit-v1"
        and legacy_headers.get("source_revision") == catalog.get("source_revision")
        and legacy_headers.get("canonical_identity_count") == len(canonical_ids)
        and legacy_headers.get("source_definition_count") == len(catalog["definitions"])
        and legacy_headers.get("coverage_credit_granted") == 0
        and legacy_headers.get("unknowns_inferred_as_misses") == 0
        and legacy_headers.get("promotion_allowed") is False
        and legacy_headers.get("audit_tool_sha256") == sha256_file(ROOT / "tools" / "audit_legacy_vector_headers.py")
        and legacy_headers.get("input_sha256") == {
            "catalog": catalog_hash,
            "canonical_bin_ids": sha256_file(CANONICAL_IDS_PATH),
            "array_reference": sha256_file(ARRAY_RANGE_PATH),
        }
        and len(legacy_headers.get("vectors", [])) > 0
        and legacy_headers.get("vector_header_count") == len(legacy_headers.get("vectors", []))
        and all(
            row.get("historical_identity_count") == 4507
            and row.get("unique_historical_identity_count") == 4507
            and row.get("coverage_credit_granted") == 0
            and row.get("promotion_allowed") is False
            for row in legacy_headers.get("vectors", [])
        )
    )
    if not legacy_headers_valid:
        raise ValueError("legacy vector header audit is stale or is not diagnostic-only")
    classification_hash = sha256_file(classification_path)
    sidecar_path = Path(str(classification_path) + ".sha256")
    sidecar = sidecar_path.read_text(encoding="ascii").split()
    if len(sidecar) != 2 or sidecar[0] != classification_hash:
        raise ValueError("classification SHA-256 sidecar is missing or inconsistent")
    if sidecar[1] != Path(classification_path).name:
        raise ValueError("classification SHA-256 sidecar names a different artifact")

    bridge_hash = sha256_file(identity_bridge_path)
    bridge_sidecar_path = Path(str(identity_bridge_path) + ".sha256")
    bridge_sidecar = bridge_sidecar_path.read_text(encoding="ascii").split()
    if len(bridge_sidecar) != 2 or bridge_sidecar[0] != bridge_hash:
        raise ValueError("identity bridge SHA-256 sidecar is missing or inconsistent")
    if bridge_sidecar[1] != Path(identity_bridge_path).name:
        raise ValueError("identity bridge SHA-256 sidecar names a different artifact")

    sample_site_audit_hash = sha256_file(sample_site_audit_path)
    sample_site_audit_sidecar_path = Path(str(sample_site_audit_path) + ".sha256")
    sample_site_audit_sidecar = sample_site_audit_sidecar_path.read_text(encoding="ascii").split()
    if len(sample_site_audit_sidecar) != 2 or sample_site_audit_sidecar[0] != sample_site_audit_hash:
        raise ValueError("sample-site audit SHA-256 sidecar is missing or inconsistent")
    if sample_site_audit_sidecar[1] != Path(sample_site_audit_path).name:
        raise ValueError("sample-site audit SHA-256 sidecar names a different artifact")

    stage08_sha_manifest = Path(stage08_readiness_path).with_name("sha256.txt")
    declared_readiness_hash = stage08_sha_manifest.read_text(encoding="ascii").split()[0]
    if declared_readiness_hash != sha256_file(stage08_readiness_path):
        raise ValueError("Stage 08 readiness SHA-256 manifest is stale")
    stage08_inputs = stage08.get("inputs", {})
    if stage08_inputs.get("stage06_matrix_audit", {}).get("sha256") != sha256_file(
        stage06_matrix_audit_path
    ):
        raise ValueError("Stage 08 readiness references a different Stage 06 matrix audit")

    replay_summary_path = Path(replay_audit_path).with_name("summary.json")
    if replay.get("summary_sha256") != sha256_file(replay_summary_path):
        raise ValueError("Stage 09 replay audit does not match its summary")
    classifier_path = ROOT / "tools" / "classify_source_definitions.py"
    bridge_tool_path = ROOT / "tools" / "audit_source_identity_bridge.py"
    sample_site_tool_path = ROOT / "tools" / "audit_sample_site_mapping.py"
    classifier_hash_matches = classification.get("classifier_sha256") == sha256_file(
        classifier_path
    )
    bridge_tool_hash_matches = identity_bridge.get("audit_tool_sha256") == sha256_file(
        bridge_tool_path
    )
    sample_site_tool_hash_matches = sample_site_audit.get("audit_tool_sha256") == sha256_file(
        sample_site_tool_path
    )

    array_bin_count = sum(len(records) for records in array_catalog["arrays"].values())
    endpoint_probe_count = sum(
        record.get("endpoint_probe_count", 0)
        for record in partition_audit.get("arrays", {}).values()
    )
    endpoint_pass_count = sum(
        record.get("endpoint_probes_passed", 0)
        for record in partition_audit.get("arrays", {}).values()
    )
    definition_total = len(catalog.get("definitions", []))
    stage06_exact = (
        stage06.get("matrix_status") == "COMPLETE_EXACT"
        and stage06.get("canonical_bin_count_observed") == 4507
        and stage06.get("union", {}).get("unknown_bin_count") == 0
    )
    mapping = stage08.get("direct_legacy_identity_matches", 0)
    canonical_count = stage08.get("canonical_bin_count", 4507)
    stage08_sample_site_complete = stage08.get("sample_sites_complete") is True
    if "sample_sites_complete" not in stage08:
        stage08_sample_site_complete = stage08.get("sample_site_mapping_status") == "COMPLETE"
    sample_site_audit_valid = (
        sample_site_audit.get("schema") == "aon-timer-sample-site-mapping-audit-v1"
        and sample_site_audit.get("source_revision") == catalog.get("source_revision")
        and sample_site_audit.get("coverage_schema_id") == read_json(SCHEMA_PATH).get("schema_id")
        and sample_site_audit.get("coverage_credit_granted") == 0
        and sample_site_audit.get("unknowns_are_misses") is False
        and sample_site_audit.get("trace_errors") == []
        and sample_site_audit.get("unknown_group_sample_count") == 0
        and sample_site_tool_hash_matches
    )
    aon_capture_protocol_complete = (
        sample_site_audit_valid
        and sample_site_audit.get("mapping_gates", {}).get("aon_capture_protocol_complete") is True
    )
    shared_scope_mapping_complete = (
        sample_site_audit_valid
        and sample_site_audit.get("mapping_gates", {}).get("shared_scope_mapping_complete") is True
    )
    timing_parity_complete = (
        sample_site_audit_valid
        and sample_site_audit.get("mapping_gates", {}).get("timing_parity_complete") is True
        and not any(
        "timing parity" in str(item).lower()
        for item in stage08.get("unmapped_sample_sites", [])
        )
    )
    sample_site_complete = (
        stage08_sample_site_complete
        and aon_capture_protocol_complete
        and shared_scope_mapping_complete
        and timing_parity_complete
    )

    blockers = []
    if mapping != canonical_count:
        blockers.append(
            f"Legacy identity bridge has only {mapping} direct matches; the remaining identities "
            f"require candidate or independent expansion evidence ({identity_bridge.get('deterministic_candidate_count', 0)} deterministic candidates, "
            f"{identity_bridge.get('ambiguous_candidate_count', 0)} ambiguous candidates)."
        )
    if not stage06_exact:
        blockers.append("Stage 06 does not contain a complete exact run matrix.")
    if stage08.get("stage07_scheduler_allowed") is not True:
        blockers.append("Stage 07 paper scheduler has not been enabled.")
    if not sample_site_audit_valid:
        blockers.append("Sample-site audit is missing, stale, or not fail-closed.")
    elif not aon_capture_protocol_complete:
        blockers.append("AON capture protocol audit has not validated all seven AON covergroups.")
    if not shared_scope_mapping_complete:
        blockers.append(
            f"Shared/non-AON scope mapping is unavailable for {sample_site_audit.get('shared_scope', {}).get('definition_count', 228)} definitions; "
            "the AON trace adapter does not sample those groups."
        )
    if not array_vcs_python_parity_verified:
        blockers.append(
            "Array boundaries lack a verified native VCS/Python classifier comparison."
        )
    if not timing_parity_complete:
        blockers.append(
            "Count-event sampling cadence lacks source-locked testcase/sample-level UVM/VCS timing parity; "
            "the original shows differences; a declared repair matches three bounded cases, with the broader timing/shared matrix still unresolved."
        )
    if not replay.get("status") == "PASS" or replay.get("attempts_replayed") != 288:
        blockers.append("Stage 09 replay audit is not a verified 288/288 PASS.")
    if (classification.get("trace_count") != 288
            or classification.get("sample_count") != 16515
            or not classifier_hash_matches):
        blockers.append("Source-definition classification does not cover the expected 288 traces and 16,515 samples.")
    if classification.get("summary", {}).get("full_coverage_rate_percent") is not None:
        blockers.append("Classification unexpectedly reports a numeric full coverage rate.")
    bridge_audit_valid = (
        identity_bridge.get("schema") == "aon-timer-source-identity-bridge-audit-v1"
        and identity_bridge.get("source_revision") == catalog.get("source_revision")
        and identity_bridge.get("canonical_identity_count") == canonical_count
        and identity_bridge.get("source_definition_count") == definition_total
        and identity_bridge.get("coverage_credit_granted") == 0
        and identity_bridge.get("promotion_allowed") is False
        and bridge_tool_hash_matches
    )
    if not bridge_audit_valid:
        blockers.append("Source identity bridge audit is missing, stale, or not fail-closed.")

    checks = {
        "definition_catalog_count_is_4507": definition_total == 4507,
        "canonical_identity_catalog_count_is_4507": len(canonical_ids) == 4507,
        "array_reference_partition_count_is_160": array_bin_count == 160,
        "array_source_python_partition_audit_passed": (
            partition_audit.get("status") == "SOURCE_PARTITION_AND_PYTHON_CLASSIFIER_VERIFIED"
            and partition_audit.get("python_classifier_partition_verified") is True
            and endpoint_probe_count == endpoint_pass_count
            and endpoint_probe_count == 640
        ),
        "stage09_replay_audit_is_288_of_288": (
            replay.get("status") == "PASS"
            and replay.get("attempts_replayed") == 288
            and replay.get("real_tests_passed") == 288
            and replay.get("unknowns_never_inferred_as_misses") is True
        ),
        "source_classification_is_288_traces_16515_samples": (
            classification.get("trace_count") == 288
            and classification.get("sample_count") == 16515
            and classification.get("summary", {}).get("legacy_identity_credit_granted") == 0
        ),
        "classification_hash_is_sidecar_verified": True,
        "classification_uses_current_classifier": classifier_hash_matches,
        "identity_bridge_audit_is_sidecar_verified": True,
        "identity_bridge_uses_current_tool": bridge_tool_hash_matches,
        "identity_bridge_audit_is_complete_as_audit": bridge_audit_valid,
        "sample_site_audit_is_sidecar_verified": True,
        "sample_site_audit_uses_current_tool": sample_site_tool_hash_matches,
        "legacy_vector_header_audit_is_current_and_diagnostic_only": legacy_headers_valid,
        "array_vcs_python_boundary_parity_verified": array_vcs_python_parity_verified,
        "aon_capture_protocol_is_complete": aon_capture_protocol_complete,
        "shared_scope_mapping_is_complete": shared_scope_mapping_complete,
        "count_event_cadence_model_is_present": (
            sample_site_audit.get("count_event_timing", {}).get("cadence_model_present") is True
        ),
        "uvm_control_event_shape_diagnostic_is_replayed": timing_shape_verified,
        "independent_actual_sample_diagnostic_is_replayed": True,
        "fixed_reference_sample_diagnostic_is_replayed": True,
        "fixed_reference_three_short_cases_match": sample_fix["fixed_reference_short_cases_match"],
        "stage06_exact_matrix_is_available": stage06_exact,
        "legacy_identity_bridge_is_complete": mapping == canonical_count,
        "sample_site_mapping_is_complete": sample_site_complete,
        "stage07_paper_scheduler_is_enabled": (
            stage08.get("stage07_scheduler_allowed") is True
        ),
        "independent_uvm_vcs_timing_comparison_complete": timing_parity_complete,
        "native_verilator_uvm_equivalence_verified": (
            stage08.get("array_bin_verilator_equivalence_verified") is True
            and sample_site_complete
            and timing_parity_complete
        ),
        "full_coverage_rate_is_reportable": False,
    }
    return {
        "schema": "aon-timer-stage10-full-simulation-preflight-v2",
        "status": "BLOCKED_BEFORE_FULL_SIMULATION",
        "source_revision": catalog.get("source_revision"),
        "full_simulation_started": False,
        "full_simulation_start_gate": "BLOCKED",
        "full_coverage_rate_percent": None,
        "coverage_credit_added": 0,
        "unknowns_are_misses": False,
        "checks": checks,
        "summary": {
            "definition_catalog_count": definition_total,
            "canonical_identity_count": canonical_count,
            "canonical_identity_catalog_file_count": len(canonical_ids),
            "array_reference_partition_count": array_bin_count,
            "array_source_python_endpoint_probes_passed": endpoint_pass_count,
            "array_vcs_python_boundary_probes_passed": array_boundary.get("cases_passed"),
            "array_vcs_python_boundary_parity_verified": array_vcs_python_parity_verified,
            "stage09_traces_replayed": replay.get("attempts_replayed"),
            "stage09_passed_attempts": replay.get("real_tests_passed"),
            "classified_traces": classification.get("trace_count"),
            "classified_samples": classification.get("sample_count"),
            "array_reference_matches": classification.get("summary", {}).get(
                "array_reference_match_occurrence_count"
            ),
            "array_unresolved_observations": classification.get("summary", {}).get(
                "array_partition_unresolved_observation_count"
            ),
            "direct_legacy_identity_matches": mapping,
            "identity_bridge_exact_source_definition_count": identity_bridge.get(
                "exact_source_definition_count"
            ),
            "identity_bridge_deterministic_candidate_count": identity_bridge.get(
                "deterministic_candidate_count"
            ),
            "identity_bridge_ambiguous_candidate_count": identity_bridge.get(
                "ambiguous_candidate_count"
            ),
            "identity_bridge_unresolved_count": identity_bridge.get("unresolved_count"),
            "legacy_vector_header_diagnostics": [
                {
                    "source": row["path"],
                    "canonical_identity_overlap_count": row["canonical_identity_overlap_count"],
                    "classification_counts": row["classification_counts"],
                    "unresolved_count": row["unresolved_count"],
                    "promotion_allowed": False,
                }
                for row in legacy_headers["vectors"]
            ],
            "exact_stage06_matrix_available": stage06_exact,
            "aon_capture_protocol_complete": aon_capture_protocol_complete,
            "shared_definition_count": sample_site_audit.get("shared_scope", {}).get("definition_count"),
            "shared_scope_mapping_complete": shared_scope_mapping_complete,
            "count_event_cadence_model_present": sample_site_audit.get("count_event_timing", {}).get("cadence_model_present"),
            "sample_sites_complete": sample_site_complete,
            "uvm_control_event_shape_diagnostic_complete": timing_shape_verified,
            "uvm_control_event_run_count": len(timing_shape.get("runs", [])),
            "independent_pinned_actual_sample_run_pairs": len(actual_samples["cases"]),
            "independent_pinned_actual_sample_diagnostic_status": actual_samples["status"],
            "independent_pinned_actual_sample_body_count": sum(c["uvm_sample_count_in_body"] for c in actual_samples["cases"]),
            "independent_cocotb_sample_body_count": sum(c["cocotb_sample_count_in_body"] for c in actual_samples["cases"]),
            "independent_source_export_and_declared_patch_verified": actual_samples["post_build_source_matches_declared_variant"],
            "fixed_reference_variant": sample_fix["reference_variant"],
            "fixed_reference_short_case_status": sample_fix["status"],
            "fixed_reference_actual_sample_body_count": sum(c["uvm_sample_count_in_body"] for c in sample_fix["cases"]),
            "fixed_adapter_sample_body_count": sum(c["cocotb_sample_count_in_body"] for c in sample_fix["cases"]),
            "fixed_reference_is_original_reference_parity": False,
            "uvm_control_message_count": sum(row["event_count"] for row in timing_shape["runs"]),
            "uvm_covergroup_sample_invocations_observed": False,
            "uvm_build_source_revision_verified": timing_shape.get("build_source_revision_verified"),
            "uvm_build_tree_scoreboard_matches_pinned": timing_shape.get(
                "current_build_tree_scoreboard_matches_pinned"
            ),
            "native_verilator_uvm_equivalence_verified": False,
        },
        "blockers": blockers,
        "next_gate": (
            "Resolve the exact legacy identity bridge, complete sample-site and shared-group mapping, "
            "validate sampling/timing equivalence against independent UVM/VCS evidence, and rebuild "
            "the exact Stage 06 matrix. Re-run this preflight before starting the full simulation."
        ),
        "inputs": {
            "definition_catalog": {"path": _relative(CATALOG_PATH), "sha256": catalog_hash},
            "array_reference": {
                "path": _relative(ARRAY_RANGE_PATH),
                "sha256": array_reference["evidence"]["catalog_sha256"],
                "source_python_audit": {
                    "path": _relative(ARRAY_PARTITION_AUDIT_PATH),
                    "sha256": array_reference["evidence"]["partition_audit_file_sha256"],
                },
                "mapped_source_definitions": len(array_definitions),
            },
            "canonical_identity_catalog": {
                "path": _relative(CANONICAL_CATALOG_PATH),
                "sha256": array_reference["evidence"]["canonical_identity_catalog_sha256"],
            },
            "coverage_schema": {"path": _relative(SCHEMA_PATH), "sha256": sha256_file(SCHEMA_PATH)},
            "stage06_matrix_audit": {
                "path": _relative(stage06_matrix_audit_path),
                "sha256": sha256_file(stage06_matrix_audit_path),
            },
            "stage08_readiness": {
                "path": _relative(stage08_readiness_path),
                "sha256": sha256_file(stage08_readiness_path),
            },
            "stage09_replay_audit": {
                "path": _relative(replay_audit_path),
                "sha256": sha256_file(replay_audit_path),
            },
            "source_definition_classification": {
                "path": _relative(classification_path),
                "sha256": classification_hash,
            },
            "source_identity_bridge_audit": {
                "path": _relative(identity_bridge_path),
                "sha256": bridge_hash,
            },
            "sample_site_audit": {
                "path": _relative(sample_site_audit_path),
                "sha256": sample_site_audit_hash,
            },
            "legacy_vector_header_audit": {
                "path": _relative(legacy_vector_header_audit_path),
                "sha256": legacy_headers_hash,
                "purpose": "Diagnostic source-definition candidates only; does not satisfy the legacy identity gate.",
            },
            "array_vcs_boundary_audit": {
                "path": _relative(array_vcs_boundary_audit_path),
                "sha256": boundary_hash,
                "scope": "Official timer_cfg_cg array bin boundaries; excludes RTL/UVM sample timing.",
            },
            "uvm_timing_shape_diagnostic": {
                "path": _relative(uvm_timing_shape_audit_path),
                "sha256": timing_shape_hash,
                "scope": "Count/expiry producer control messages only; cannot satisfy the sampling parity gate.",
            },
            "independent_actual_sample_diagnostic": {
                "path": _relative(actual_sample_audit_path),
                "sha256": actual_samples_hash,
                "scope": "Three pinned actual-sample pairs; preserves observed differences and does not satisfy complete parity.",
            },
            "fixed_reference_sample_diagnostic": {
                "path": _relative(sample_fix_audit_path), "sha256": sample_fix_hash,
                "scope": "Declared reference repairs and separate adapter match three short cases; no original/full parity credit.",
            },
            "trace_root": _relative(trace_root),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-root", type=Path, default=DEFAULT_TRACE_ROOT)
    parser.add_argument("--replay-audit", type=Path, default=DEFAULT_REPLAY_AUDIT)
    parser.add_argument("--stage06-matrix-audit", type=Path, default=DEFAULT_STAGE06_MATRIX_AUDIT)
    parser.add_argument("--stage08-readiness", type=Path, default=DEFAULT_STAGE08_READINESS)
    parser.add_argument("--classification", type=Path, default=DEFAULT_CLASSIFICATION)
    parser.add_argument("--identity-bridge", type=Path, default=DEFAULT_IDENTITY_BRIDGE)
    parser.add_argument("--sample-site-audit", type=Path, default=DEFAULT_SAMPLE_SITE_AUDIT)
    parser.add_argument("--legacy-vector-header-audit", type=Path, default=DEFAULT_LEGACY_VECTOR_HEADER_AUDIT)
    parser.add_argument("--array-vcs-boundary-audit", type=Path, default=DEFAULT_ARRAY_VCS_BOUNDARY_AUDIT)
    parser.add_argument("--uvm-timing-shape-audit", type=Path, default=DEFAULT_UVM_TIMING_SHAPE_AUDIT)
    parser.add_argument("--actual-sample-audit", type=Path, default=DEFAULT_ACTUAL_SAMPLE_AUDIT)
    parser.add_argument("--sample-fix-audit", type=Path, default=DEFAULT_SAMPLE_FIX_AUDIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--require-ready", action="store_true",
                        help="Return exit code 2 when the full-simulation start gate is blocked.")
    args = parser.parse_args()
    try:
        result = build_preflight(
            trace_root=args.trace_root,
            replay_audit_path=args.replay_audit,
            stage06_matrix_audit_path=args.stage06_matrix_audit,
            stage08_readiness_path=args.stage08_readiness,
            classification_path=args.classification,
            identity_bridge_path=args.identity_bridge,
            sample_site_audit_path=args.sample_site_audit,
            legacy_vector_header_audit_path=args.legacy_vector_header_audit,
            array_vcs_boundary_audit_path=args.array_vcs_boundary_audit,
            uvm_timing_shape_audit_path=args.uvm_timing_shape_audit,
            actual_sample_audit_path=args.actual_sample_audit,
            sample_fix_audit_path=args.sample_fix_audit,
        )
    except (OSError, UnicodeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{sha256_file(output)}  {output.name}\n", encoding="ascii"
    )
    print(json.dumps({
        "status": result["status"],
        "full_simulation_started": result["full_simulation_started"],
        "full_simulation_start_gate": result["full_simulation_start_gate"],
        "blocker_count": len(result["blockers"]),
    }, ensure_ascii=False))
    return 2 if args.require_ready and result["full_simulation_start_gate"] != "READY" else 0


if __name__ == "__main__":
    raise SystemExit(main())
