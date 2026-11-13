"""Audit whether exact coverage feedback prerequisites are ready for Stage 08."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "references" / "bin_definitions.v1.json"
DEFAULT_BIN_IDS = ROOT / "references" / "canonical_bin_ids.txt"
DEFAULT_MATRIX_AUDIT = ROOT / "evidence" / "stage06_partial" / "coverage_matrix_audit.json"
DEFAULT_SCHEDULER_INPUT = ROOT / "evidence" / "stage07_partial" / "scheduler_input.json"
DEFAULT_SAMPLE_SITE_AUDIT = ROOT / "configs" / "coverage_schema.json"
DEFAULT_ARRAY_RANGE_CATALOG = ROOT / "references" / "array_bin_ranges.v1.json"
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


def validate_array_range_catalog(
    catalog: dict[str, Any],
    canonical_ids: list[str],
    range_catalog: dict[str, Any] | None,
    source_schema: dict[str, Any],
) -> tuple[int, bool]:
    """Return unresolved boundary count and whether Verilator parity is verified."""
    array_entries = [entry for entry in catalog.get("definitions", []) if "array_bin" in entry]
    if not array_entries:
        return 0, True
    if range_catalog is None:
        return len(array_entries), False

    if range_catalog.get("schema") != "aon-timer-array-bin-ranges-v1":
        raise ValueError("unsupported array-bin range catalog schema")
    if range_catalog.get("source_revision") != catalog.get("source_revision"):
        raise ValueError("array-bin range catalog does not match the fixed source revision")
    if range_catalog.get("status") != "VCS_REFERENCE_PARTITIONS_VALID_VERILATOR_EQUIVALENCE_UNVERIFIED":
        raise ValueError("array-bin range catalog has an unexpected verification status")
    evidence = range_catalog.get("source_evidence", {})
    if evidence.get("historical_run_rows_read") is not False or evidence.get("historical_hit_counts_imported") is not False:
        raise ValueError("array-bin range catalog must exclude historical run rows and hit counts")
    if not all(
        isinstance(evidence.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", evidence[key])
        for key in ("header_sha256", "protocol_sha256", "mapping_validation_sha256")
    ):
        raise ValueError("array-bin range catalog is missing source evidence hashes")
    source_evidence = range_catalog.get("source_revision_evidence", {})
    coverage_source_hashes = {
        item.get("sha256") for item in source_schema.get("source_files", [])
        if item.get("path") == source_evidence.get("coverage_source_file")
    }
    if (
        source_evidence.get("direct_vcs_run_revision_attestation") is not False
        or source_evidence.get("coverage_source_file_sha256") not in coverage_source_hashes
    ):
        raise ValueError("array-bin VCS source cross-reference does not match the pinned coverage source")
    mapping = range_catalog.get("mapping", {})
    if mapping.get("current_verilator_partition_verified") is not False:
        raise ValueError("VCS reference ranges cannot assert Verilator partition equivalence")

    expected: dict[str, dict[int, dict[str, Any]]] = {}
    declared: dict[str, tuple[int, int, int]] = {}
    identity_to_array = {}
    for entry in array_entries:
        details = entry.get("array_bin", {})
        match = re.fullmatch(r"([a-z]+)\[(\d+)\]", entry.get("bin_name", ""))
        if not match:
            raise ValueError("array-bin definition has an unsupported bin label")
        name, ordinal_text = match.groups()
        ordinal = int(ordinal_text)
        count = details.get("count")
        domain = details.get("declared_value_range")
        if (
            not isinstance(count, int) or isinstance(count, bool)
            or not isinstance(domain, list) or len(domain) != 2
            or any(not isinstance(value, int) or isinstance(value, bool) for value in domain)
        ):
            raise ValueError("array-bin definition has incomplete count/domain metadata")
        if name not in declared:
            declared[name] = (count, domain[0], domain[1])
            expected[name] = {}
        elif declared[name] != (count, domain[0], domain[1]):
            raise ValueError(f"{name}: inconsistent array-bin declarations")
        if ordinal in expected[name]:
            raise ValueError(f"{name}: duplicate source array-bin ordinal {ordinal}")
        if not isinstance(details.get("index"), int) or isinstance(details.get("index"), bool) or details["index"] != ordinal:
            raise ValueError(f"{name}[{ordinal}]: source definition index does not match its bin label")
        legacy_identity = "||".join((
            entry["scope"], entry["kind"], entry["item"], f"name:{entry['bin_name']}", "0"
        ))
        if legacy_identity not in canonical_ids:
            raise ValueError(f"missing canonical identity for {name}[{ordinal}]")
        identity_to_array[legacy_identity] = (name, ordinal)
        expected[name][ordinal] = {"identity": legacy_identity, "domain": domain, "count": count}

    arrays = range_catalog.get("arrays")
    if not isinstance(arrays, dict) or set(arrays) != set(expected):
        raise ValueError("array-bin range catalog does not contain the expected arrays")
    validated_total = 0
    for name, ordinal_entries in expected.items():
        count, domain_low, domain_high = declared[name]
        if len(ordinal_entries) != count or set(ordinal_entries) != set(range(count)):
            raise ValueError(f"{name}: source definitions do not enumerate the declared bins")
        records = arrays[name]
        if not isinstance(records, list) or len(records) != count:
            raise ValueError(f"{name}: reference ranges do not cover every declared bin")
        by_ordinal = {}
        for record in records:
            if not isinstance(record, dict):
                raise ValueError(f"{name}: malformed array-bin range record")
            ordinal = record.get("ordinal")
            if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal in by_ordinal:
                raise ValueError(f"{name}: duplicate or invalid range ordinal")
            if ordinal not in ordinal_entries:
                raise ValueError(f"{name}: range ordinal is outside the source definition")
            if record.get("canonical_identity") != ordinal_entries[ordinal]["identity"]:
                raise ValueError(f"{name}[{ordinal}]: range identity does not match the source definition")
            source_interval_label = record.get("source_interval_label")
            if not isinstance(source_interval_label, str):
                raise ValueError(f"{name}[{ordinal}]: malformed source interval label")
            label_match = re.fullmatch(
                r"([a-z]+)\[(0x[0-9a-f]+|[0-9]+):(0x[0-9a-f]+|[0-9]+)\]",
                source_interval_label,
                re.IGNORECASE,
            )
            if not label_match:
                raise ValueError(f"{name}[{ordinal}]: malformed source interval label")
            label_name, low_text, high_text = label_match.groups()
            label_bounds = [
                int(low_text, 16 if low_text.lower().startswith("0x") else 10),
                int(high_text, 16 if high_text.lower().startswith("0x") else 10),
            ]
            if label_name.lower() != name or label_bounds != record.get("value_range"):
                raise ValueError(f"{name}[{ordinal}]: source interval label disagrees with numeric bounds")
            bounds = record.get("value_range")
            if (
                not isinstance(bounds, list) or len(bounds) != 2
                or any(not isinstance(value, int) or isinstance(value, bool) for value in bounds)
                or bounds[0] > bounds[1]
                or bounds[0] < domain_low or bounds[1] > domain_high
            ):
                raise ValueError(f"{name}[{ordinal}]: invalid value range")
            by_ordinal[ordinal] = bounds
        if set(by_ordinal) != set(range(count)):
            raise ValueError(f"{name}: reference ranges have missing ordinals")
        ordered = [by_ordinal[index] for index in range(count)]
        if ordered[0][0] != domain_low or ordered[-1][1] != domain_high:
            raise ValueError(f"{name}: reference ranges do not cover the declared domain")
        if any(left[1] + 1 != right[0] for left, right in zip(ordered, ordered[1:])):
            raise ValueError(f"{name}: reference ranges contain a gap or overlap")
        validated_total += count

    if validated_total != len(array_entries) or mapping.get("total_array_bin_count") != validated_total:
        raise ValueError("array-bin range catalog count does not match the source definitions")
    if mapping.get("one_to_one_canonical_identity_mapping") is not True:
        raise ValueError("array-bin range catalog does not attest a one-to-one identity mapping")
    if len(identity_to_array) != len(array_entries):
        raise ValueError("array-bin canonical identity mapping is not one-to-one")
    return 0, False


def audit_preconditions(
    catalog: dict[str, Any],
    canonical_ids: list[str],
    matrix_audit: dict[str, Any],
    scheduler_input: dict[str, Any],
    sample_site_audit: dict[str, Any],
    array_range_catalog: dict[str, Any] | None = None,
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
    unresolved_array_boundaries, array_verilator_equivalence_verified = validate_array_range_catalog(
        catalog, canonical_ids, array_range_catalog, sample_site_audit
    )
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
    if unresolved_array_boundaries:
        blockers.append(
            f"{unresolved_array_boundaries} declared array bins have no validated reference value boundaries."
        )
    if array_entries and not array_verilator_equivalence_verified:
        blockers.append(
            "Native Verilator/SystemVerilog covergroup equivalence has not been verified; "
            "the Python/Cocotb array partition audit does not replace native coverage evidence."
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

    next_actions = [
        "If native covergroups are required, verify VCS reference array partitions against a native Verilator/SystemVerilog coverage run; the Python/Cocotb partition audit is already complete.",
        "Compare the new count-event trace timing and RTL values against an independent UVM/VCS event trace before claiming sampling parity.",
        "Build a one-to-one mapping from the detailed source definitions to all frozen legacy identities, including auto-bin and cross labels and shared groups.",
        "Rebuild and independently audit exact Stage 06 vectors before enabling Stage 07 scores/UCB and launching Stage 08.",
    ]
    if any("conditional resets_cg" in str(item) for item in unmapped_sample_sites):
        next_actions.insert(
            3,
            "Resolve whether conditional reset coverage is active in the reference test configuration; retain it as not applicable only when num_edn is confirmed zero.",
        )

    ready = not blockers
    return {
        "schema": "aon-timer-stage08-preflight-v2",
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
        "array_bin_definition_catalog_boundaries_unresolved": len(unresolved_arrays),
        "array_bin_value_boundaries_unresolved": unresolved_array_boundaries,
        "array_bin_reference_partitions_verified": unresolved_array_boundaries == 0 and bool(array_entries),
        "array_bin_verilator_equivalence_verified": array_verilator_equivalence_verified,
        "shared_or_other_source_scopes": shared_group_names,
        "stage06_matrix_status": matrix_audit.get("matrix_status"),
        "exact_vector_matrix_available": vector_exact,
        "stage07_scheduler_allowed": scheduler_enabled,
        "sample_sites_complete": sample_sites_complete,
        "sample_site_mapping_status": sample_site_mapping.get("status", "MISSING"),
        "unmapped_sample_site_count": len(unmapped_sample_sites),
        "unmapped_sample_sites": unmapped_sample_sites,
        "blockers": blockers,
        "next_actions": next_actions,
    }


def run_preflight(
    *, catalog_path: Path = DEFAULT_CATALOG,
    bin_ids_path: Path = DEFAULT_BIN_IDS,
    matrix_audit_path: Path = DEFAULT_MATRIX_AUDIT,
    scheduler_input_path: Path = DEFAULT_SCHEDULER_INPUT,
    sample_site_audit_path: Path = DEFAULT_SAMPLE_SITE_AUDIT,
    array_range_catalog_path: Path = DEFAULT_ARRAY_RANGE_CATALOG,
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
    array_range_catalog_path = Path(array_range_catalog_path)
    array_range_catalog = None
    if array_range_catalog_path.is_file():
        inputs["array_bin_range_catalog"] = array_range_catalog_path
        sidecar_path = array_range_catalog_path.with_suffix(array_range_catalog_path.suffix + ".sha256")
        if not sidecar_path.is_file():
            raise FileNotFoundError(f"missing array-bin range catalog hash: {sidecar_path}")
        expected_hash_line = sidecar_path.read_text(encoding="ascii").strip()
        expected_hash_match = re.fullmatch(r"([0-9a-f]{64})  (.+)", expected_hash_line)
        if (
            not expected_hash_match
            or expected_hash_match.group(1) != sha256_file(array_range_catalog_path)
            or expected_hash_match.group(2) != array_range_catalog_path.name
        ):
            raise ValueError("array-bin range catalog SHA-256 sidecar does not match the catalog")
        inputs["array_bin_range_catalog_sha256"] = sidecar_path
        array_range_catalog = json.loads(array_range_catalog_path.read_text(encoding="utf-8"))
    result = audit_preconditions(
        catalog, canonical_ids, matrix_audit, scheduler_input, sample_site_audit, array_range_catalog
    )
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
    parser.add_argument("--array-range-catalog", type=Path, default=DEFAULT_ARRAY_RANGE_CATALOG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = run_preflight(
            catalog_path=args.catalog,
            bin_ids_path=args.bin_ids,
            matrix_audit_path=args.matrix_audit,
            scheduler_input_path=args.scheduler_input,
            sample_site_audit_path=args.sample_site_audit,
            array_range_catalog_path=args.array_range_catalog,
            output_dir=args.output_dir,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": result["status"],
        "ready_for_online_coverage_feedback": result["ready_for_online_coverage_feedback"],
        "direct_legacy_identity_matches": result["direct_legacy_identity_matches"],
        "array_bin_value_boundaries_unresolved": result["array_bin_value_boundaries_unresolved"],
        "array_bin_verilator_equivalence_verified": result["array_bin_verilator_equivalence_verified"],
        "blockers": result["blockers"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
