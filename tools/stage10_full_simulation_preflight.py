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
DEFAULT_OUTPUT = (
    ROOT / "evidence" / "stage10_full_simulation_preflight"
    / "2026-11-16-v1" / "preflight.json"
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
    classification_hash = sha256_file(classification_path)
    sidecar_path = Path(str(classification_path) + ".sha256")
    sidecar = sidecar_path.read_text(encoding="ascii").split()
    if len(sidecar) != 2 or sidecar[0] != classification_hash:
        raise ValueError("classification SHA-256 sidecar is missing or inconsistent")
    if sidecar[1] != Path(classification_path).name:
        raise ValueError("classification SHA-256 sidecar names a different artifact")

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
    classifier_hash_matches = classification.get("classifier_sha256") == sha256_file(
        classifier_path
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
    sample_site_complete = stage08.get("sample_sites_complete") is True
    if "sample_sites_complete" not in stage08:
        sample_site_complete = stage08.get("sample_site_mapping_status") == "COMPLETE"
    timing_parity_complete = not any(
        "timing parity" in str(item).lower()
        for item in stage08.get("unmapped_sample_sites", [])
    )

    blockers = []
    if mapping != canonical_count:
        blockers.append(
            f"Legacy identity bridge resolves only {mapping} of {canonical_count} canonical identities."
        )
    if not stage06_exact:
        blockers.append("Stage 06 does not contain a complete exact run matrix.")
    if stage08.get("stage07_scheduler_allowed") is not True:
        blockers.append("Stage 07 paper scheduler has not been enabled.")
    if not sample_site_complete:
        blockers.append("Sample-site and shared-group mapping is incomplete.")
    if stage08.get("array_bin_verilator_equivalence_verified") is not True:
        blockers.append(
            "Array reference partitions are validated for source/Python classification only; "
            "native Verilator/UVM/VCS equivalence remains unverified."
        )
    if not timing_parity_complete:
        blockers.append("Count-event sampling cadence has no independent UVM/VCS timing comparison.")
    if not replay.get("status") == "PASS" or replay.get("attempts_replayed") != 288:
        blockers.append("Stage 09 replay audit is not a verified 288/288 PASS.")
    if (classification.get("trace_count") != 288
            or classification.get("sample_count") != 16515
            or not classifier_hash_matches):
        blockers.append("Source-definition classification does not cover the expected 288 traces and 16,515 samples.")
    if classification.get("summary", {}).get("full_coverage_rate_percent") is not None:
        blockers.append("Classification unexpectedly reports a numeric full coverage rate.")

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
        "schema": "aon-timer-stage10-full-simulation-preflight-v1",
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
            "exact_stage06_matrix_available": stage06_exact,
            "sample_sites_complete": sample_site_complete,
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
            "trace_root": _relative(trace_root),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-root", type=Path, default=DEFAULT_TRACE_ROOT)
    parser.add_argument("--replay-audit", type=Path, default=DEFAULT_REPLAY_AUDIT)
    parser.add_argument("--stage06-matrix-audit", type=Path, default=DEFAULT_STAGE06_MATRIX_AUDIT)
    parser.add_argument("--stage08-readiness", type=Path, default=DEFAULT_STAGE08_READINESS)
    parser.add_argument("--classification", type=Path, default=DEFAULT_CLASSIFICATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = build_preflight(
            trace_root=args.trace_root,
            replay_audit_path=args.replay_audit,
            stage06_matrix_audit_path=args.stage06_matrix_audit,
            stage08_readiness_path=args.stage08_readiness,
            classification_path=args.classification,
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


if __name__ == "__main__":
    main()
