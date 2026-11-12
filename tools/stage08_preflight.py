"""Audit whether exact coverage feedback prerequisites are ready for Stage 08."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "references" / "bin_definitions.v1.json"
DEFAULT_BIN_IDS = ROOT / "references" / "canonical_bin_ids.txt"
DEFAULT_MATRIX_AUDIT = ROOT / "evidence" / "stage06_partial" / "coverage_matrix_audit.json"
DEFAULT_SCHEDULER_INPUT = ROOT / "evidence" / "stage07_partial" / "scheduler_input.json"
DEFAULT_SAMPLE_SITE_AUDIT = ROOT / "configs" / "coverage_schema.json"
DEFAULT_OUTPUT = (
    ROOT / "evidence" / "stage08_preflight"
    / datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S%fZ")
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_preconditions(
    catalog: dict[str, Any],
    canonical_ids: list[str],
    matrix_audit: dict[str, Any],
    scheduler_input: dict[str, Any],
    sample_site_audit: dict[str, Any],
) -> dict[str, Any]:
    definitions = catalog.get("definitions", [])
    definition_ids = {
        "||".join((entry["scope"], entry["kind"], entry["item"], entry["bin_name"]))
        for entry in definitions
    }
    if len(definition_ids) != catalog.get("definition_count"):
        raise ValueError("bin-definition catalog contains duplicate type identities")

    direct_ids = {
        "||".join((entry["scope"], entry["kind"], entry["item"], f"name:{entry['bin_name']}", "0"))
        for entry in definitions
    }
    exact_legacy_matches = direct_ids & set(canonical_ids)
    array_entries = [entry for entry in definitions if "array_bin" in entry]
    unresolved_arrays = [
        entry for entry in array_entries
        if entry["array_bin"].get("individual_value_range") is None
    ]
    auto_audits = catalog.get("auto_bin_partition_audit", [])
    cross_audits = catalog.get("cross_bin_partition_audit", [])
    auto_partitions_valid = bool(auto_audits) and all(
        item.get("complete_non_overlapping_partition") is True for item in auto_audits
    )
    cross_products_valid = bool(cross_audits) and all(
        item.get("complete_cartesian_product") is True for item in cross_audits
    )
    vector_exact = (
        matrix_audit.get("matrix_status") == "COMPLETE_EXACT"
        and matrix_audit.get("canonical_bin_count_observed") == len(canonical_ids)
        and matrix_audit.get("union", {}).get("unknown_bin_count") == 0
    )
    scheduler_enabled = scheduler_input.get("allowed_to_schedule") is True
    sample_site_mapping = sample_site_audit.get("sample_site_mapping", {})
    if not isinstance(sample_site_mapping, dict):
        sample_site_mapping = {}
        unmapped_sample_sites = ["sample_site_mapping must be an object"]
    else:
        unmapped_sample_sites = sample_site_mapping.get("unmapped", [])
    if not isinstance(unmapped_sample_sites, list):
        unmapped_sample_sites = ["sample_site_mapping.unmapped must be a list"]
    sample_sites_complete = (
        sample_site_mapping.get("complete") is True
        and sample_site_mapping.get("status") == "COMPLETE"
        and not unmapped_sample_sites
    )
    shared_group_names = sorted({
        entry["scope"] for entry in definitions
        if not entry["scope"].startswith("aon_timer_env_pkg::")
    })

    blockers = []
    if len(exact_legacy_matches) != len(canonical_ids):
        blockers.append(
            f"Legacy identity bridge resolves only {len(exact_legacy_matches)} of {len(canonical_ids)} canonical columns by exact label."
        )
    if unresolved_arrays:
        blockers.append(
            f"{len(unresolved_arrays)} declared array bins have known indices/domains but unresolved per-bin value boundaries."
        )
    if not auto_partitions_valid:
        blockers.append("The six AON Timer automatic-bin partitions are not fully audited.")
    if not cross_products_valid:
        blockers.append("The three AON Timer cross products are not fully audited.")
    if not vector_exact:
        blockers.append("Stage 06 does not contain a complete exact run matrix.")
    if not scheduler_enabled:
        blockers.append("Stage 07 has not enabled coverage-based scheduling.")
    if not sample_sites_complete:
        blockers.append(
            "Sample-site mapping is incomplete; "
            f"{len(unmapped_sample_sites)} sample or identity mapping item(s) remain unresolved."
        )

    ready = not blockers
    return {
        "schema": "aon-timer-stage08-preflight-v1",
        "status": "READY" if ready else "BLOCKED_PREREQUISITES_INCOMPLETE",
        "ready_for_online_coverage_feedback": ready,
        "canonical_bin_count": len(canonical_ids),
        "reference_definition_count": len(definition_ids),
        "aon_timer_definition_count": catalog.get("aon_timer_definition_count"),
        "shared_or_other_definition_count": catalog.get("shared_or_other_definition_count"),
        "direct_legacy_identity_matches": len(exact_legacy_matches),
        "legacy_identity_match_count_is_complete": len(exact_legacy_matches) == len(canonical_ids),
        "automatic_partitions_audited": len(auto_audits),
        "automatic_partitions_valid": auto_partitions_valid,
        "cross_products_audited": len(cross_audits),
        "cross_products_valid": cross_products_valid,
        "array_bin_count": len(array_entries),
        "array_bin_value_boundaries_unresolved": len(unresolved_arrays),
        "shared_or_other_source_scopes": shared_group_names,
        "stage06_matrix_status": matrix_audit.get("matrix_status"),
        "exact_vector_matrix_available": vector_exact,
        "stage07_scheduler_allowed": scheduler_enabled,
        "sample_sites_complete": sample_sites_complete,
        "sample_site_mapping_status": sample_site_mapping.get("status", "MISSING"),
        "unmapped_sample_site_count": len(unmapped_sample_sites),
        "unmapped_sample_sites": unmapped_sample_sites,
        "blockers": blockers,
        "next_actions": [
            "Resolve and validate each declared array-bin range against the fixed source definition and simulator semantics.",
            "Build a one-to-one mapping from the detailed source definitions to all frozen legacy identities, including auto-bin and cross labels.",
            "Connect count-event, conditional reset, and shared DV/TL sample calls to observable Cocotb events, then rerun the frozen suite.",
            "Rebuild and independently audit exact Stage 06 vectors before enabling Stage 07 scores/UCB and launching Stage 08.",
        ],
    }


def run_preflight(
    *, catalog_path: Path = DEFAULT_CATALOG,
    bin_ids_path: Path = DEFAULT_BIN_IDS,
    matrix_audit_path: Path = DEFAULT_MATRIX_AUDIT,
    scheduler_input_path: Path = DEFAULT_SCHEDULER_INPUT,
    sample_site_audit_path: Path = DEFAULT_SAMPLE_SITE_AUDIT,
    output_dir: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    inputs = {
        "bin_definition_catalog": Path(catalog_path),
        "canonical_bin_ids": Path(bin_ids_path),
        "stage06_matrix_audit": Path(matrix_audit_path),
        "stage07_scheduler_input": Path(scheduler_input_path),
        "sample_site_audit": Path(sample_site_audit_path),
    }
    for label, path in inputs.items():
        if not path.is_file():
            raise FileNotFoundError(f"missing {label}: {path}")
    catalog = json.loads(inputs["bin_definition_catalog"].read_text(encoding="utf-8"))
    canonical_ids = inputs["canonical_bin_ids"].read_text(encoding="utf-8").splitlines()
    matrix_audit = json.loads(inputs["stage06_matrix_audit"].read_text(encoding="utf-8"))
    scheduler_input = json.loads(inputs["stage07_scheduler_input"].read_text(encoding="utf-8"))
    sample_site_audit = json.loads(inputs["sample_site_audit"].read_text(encoding="utf-8"))
    result = audit_preconditions(catalog, canonical_ids, matrix_audit, scheduler_input, sample_site_audit)
    result["inputs"] = {label: {"path": str(path.name), "sha256": sha256_file(path)} for label, path in inputs.items()}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    output_path = output_dir / "readiness.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    digest = sha256_file(output_path)
    (output_dir / "sha256.txt").write_text(f"{digest}  readiness.json\n", encoding="ascii")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--bin-ids", type=Path, default=DEFAULT_BIN_IDS)
    parser.add_argument("--matrix-audit", type=Path, default=DEFAULT_MATRIX_AUDIT)
    parser.add_argument("--scheduler-input", type=Path, default=DEFAULT_SCHEDULER_INPUT)
    parser.add_argument("--sample-site-audit", type=Path, default=DEFAULT_SAMPLE_SITE_AUDIT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = run_preflight(
            catalog_path=args.catalog,
            bin_ids_path=args.bin_ids,
            matrix_audit_path=args.matrix_audit,
            scheduler_input_path=args.scheduler_input,
            sample_site_audit_path=args.sample_site_audit,
            output_dir=args.output_dir,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": result["status"],
        "ready_for_online_coverage_feedback": result["ready_for_online_coverage_feedback"],
        "direct_legacy_identity_matches": result["direct_legacy_identity_matches"],
        "array_bin_value_boundaries_unresolved": result["array_bin_value_boundaries_unresolved"],
        "blockers": result["blockers"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
