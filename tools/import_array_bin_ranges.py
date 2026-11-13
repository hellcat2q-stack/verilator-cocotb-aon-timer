"""Import array-bin value ranges from a VCS vector header, never its run data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PINNED_REVISION = "9f20940d494a223cc950a5b98f748fb28109d458"
EXPECTED_BINS = 4507
EXPECTED_ARRAYS = {
    "prescale": {"coverpoint": "prescale_cp", "count": 32, "width": 12},
    "bark": {"coverpoint": "bark_thold_cp", "count": 32, "width": 32},
    "bite": {"coverpoint": "bite_thold_cp", "count": 32, "width": 32},
    "wkup": {"coverpoint": "wkup_thold_cp", "count": 64, "width": 64},
}
INTERVAL = re.compile(r"^name:(prescale|bark|bite|wkup)\[(0x[0-9a-f]+|[0-9]+):(0x[0-9a-f]+|[0-9]+)\]$", re.IGNORECASE)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_header(path: Path) -> tuple[list[str], str]:
    """Read only the first CSV record. No run rows are read or retained."""
    with Path(path).open("rb") as stream:
        raw = stream.readline()
    if not raw or not raw.endswith(b"\n"):
        raise ValueError("source CSV does not have a complete header line")
    try:
        header = next(csv.reader([raw.decode("utf-8").rstrip("\r\n")]))
    except (UnicodeError, csv.Error) as exc:
        raise ValueError("source CSV header is not valid UTF-8 CSV") from exc
    return header, sha256_bytes(raw)


def _identity(scope: str, item: str, bin_name: str) -> str:
    return "||".join((scope, "variable", item, f"name:{bin_name}", "0"))


def build_range_catalog(
    header: list[str],
    *,
    header_sha256: str,
    canonical_ids: list[str],
    definition_catalog: dict[str, Any],
    source_protocol: dict[str, Any],
    mapping_validation: dict[str, Any],
    protocol_sha256: str,
    mapping_validation_sha256: str,
) -> dict[str, Any]:
    if len(header) != EXPECTED_BINS + 2:
        raise ValueError(f"expected two metadata fields plus {EXPECTED_BINS} bin columns; found {len(header)} fields")
    if source_protocol.get("schema") != "aon-timer-stage08-policy-v2":
        raise ValueError("unsupported VCS reference protocol")
    if source_protocol.get("bin_count") != EXPECTED_BINS:
        raise ValueError("VCS reference protocol bin count does not match the frozen universe")
    bin_identity = source_protocol.get("bin_identity")
    if not isinstance(bin_identity, str) or not bin_identity.startswith("VCS cumulative XML"):
        raise ValueError("VCS reference protocol does not declare cumulative-XML bin identities")
    if mapping_validation.get("status") != "pass" or mapping_validation.get("bin_count") != EXPECTED_BINS:
        raise ValueError("VCS mapping validation did not pass for the frozen bin count")
    if source_protocol.get("mapping_sha256") != mapping_validation.get("mapping_sha256"):
        raise ValueError("VCS protocol and mapping-validation hashes disagree")
    if definition_catalog.get("source_revision") != PINNED_REVISION:
        raise ValueError("detailed bin-definition catalog does not match the pinned source revision")
    if len(canonical_ids) != EXPECTED_BINS or len(set(canonical_ids)) != EXPECTED_BINS:
        raise ValueError("canonical identity list must contain 4,507 unique entries")

    canonical_set = set(canonical_ids)
    definitions = {
        (item["scope"], item["item"], item["bin_name"]): item
        for item in definition_catalog.get("definitions", [])
        if item.get("kind") == "variable" and "array_bin" in item
    }
    scope = "aon_timer_env_pkg::aon_timer_env_cov::timer_cfg_cg"
    by_array: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for column in header[2:]:
        fields = column.split("||")
        if len(fields) != 5 or fields[0] != scope or fields[1] != "variable":
            continue
        match = INTERVAL.fullmatch(fields[3])
        if not match:
            continue
        name, low_text, high_text = match.groups()
        spec = EXPECTED_ARRAYS[name.lower()]
        if fields[2] != spec["coverpoint"]:
            raise ValueError(f"{name} interval label appears under an unexpected coverpoint")
        low = int(low_text, 16 if low_text.lower().startswith("0x") else 10)
        high = int(high_text, 16 if high_text.lower().startswith("0x") else 10)
        if low > high or high >= (1 << spec["width"]):
            raise ValueError(f"invalid {spec['width']}-bit range in {fields[3]}")
        by_array[name.lower()].append((low, high, fields[3][len("name:"):]))

    missing = set(EXPECTED_ARRAYS) - set(by_array)
    if missing:
        raise ValueError(f"missing array-bin interval labels for: {', '.join(sorted(missing))}")

    array_records: dict[str, list[dict[str, Any]]] = {}
    for name, spec in sorted(EXPECTED_ARRAYS.items()):
        items = sorted(by_array[name])
        if len(items) != spec["count"]:
            raise ValueError(f"{name}: expected {spec['count']} interval labels, found {len(items)}")
        maximum = (1 << spec["width"]) - 1
        if items[0][0] != 1 or items[-1][1] != maximum:
            raise ValueError(f"{name}: intervals do not cover the declared [1:$] domain")
        if any(left[1] + 1 != right[0] for left, right in zip(items, items[1:])):
            raise ValueError(f"{name}: intervals have a gap or overlap")

        records = []
        for ordinal, (low, high, source_label) in enumerate(items):
            canonical_identity = _identity(scope, spec["coverpoint"], f"{name}[{ordinal}]")
            if canonical_identity not in canonical_set:
                raise ValueError(f"missing canonical identity for {name}[{ordinal}]")
            source_definition = definitions.get((scope, spec["coverpoint"], f"{name}[{ordinal}]"))
            if source_definition is None:
                raise ValueError(f"detailed definition catalog is missing {name}[{ordinal}]")
            source_array = source_definition["array_bin"]
            expected_domain = [1, (1 << spec["width"]) - 1]
            if (
                source_array.get("index") != ordinal
                or source_array.get("count") != spec["count"]
                or source_array.get("declared_value_range") != expected_domain
            ):
                raise ValueError(f"detailed definition catalog disagrees with {name}[{ordinal}] declaration")
            records.append({
                "ordinal": ordinal,
                "canonical_identity": canonical_identity,
                "source_interval_label": source_label,
                "value_range": [low, high],
            })
        array_records[name] = records

    total = sum(len(records) for records in array_records.values())
    return {
        "schema": "aon-timer-array-bin-ranges-v1",
        "status": "VCS_REFERENCE_PARTITIONS_VALID_VERILATOR_EQUIVALENCE_UNVERIFIED",
        "source_revision": PINNED_REVISION,
        "source_revision_evidence": {
            "basis": "The pinned source manifest records aon_timer_env_cov.sv SHA-256 c0ec937d68c335e2d05760268ce161eca1a40e7f8e50546156c0589882ed9b45. The imported VCS run protocol itself does not embed a Git revision, so linkage is a cross-reference, not a direct run attestation.",
            "coverage_source_file": "hw/ip/aon_timer/dv/env/aon_timer_env_cov.sv",
            "coverage_source_file_sha256": "c0ec937d68c335e2d05760268ce161eca1a40e7f8e50546156c0589882ed9b45",
            "direct_vcs_run_revision_attestation": False,
        },
        "source_evidence": {
            "kind": "VCS/Cocotb project compatibility-reference VCS vector header; header only",
            "header_sha256": header_sha256,
            "protocol_sha256": protocol_sha256,
            "mapping_validation_sha256": mapping_validation_sha256,
            "mapping_validation_status": mapping_validation["status"],
            "mapping_validation_bin_count": mapping_validation["bin_count"],
            "historical_run_rows_read": False,
            "historical_hit_counts_imported": False,
        },
        "mapping": {
            "total_array_bin_count": total,
            "one_to_one_canonical_identity_mapping": total == 160,
            "ordinal_rule": "Intervals sorted by numeric lower bound map to the declared bins[] ordinal 0..N-1.",
            "partition_rule": "The recorded interval labels must be non-overlapping, contiguous, and span [1, 2**width-1].",
            "current_verilator_partition_verified": False,
        },
        "arrays": array_records,
        "limitations": [
            "Intervals are reference values from a prior VCS coverage header and are not generated by the current Verilator+Cocotb run.",
            "The VCS run protocol has no direct Git revision field; the pinned coverage-source hash is cross-referenced independently.",
            "No historical run rows, coverage vectors, or hit counts are imported into this catalog.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vectors", type=Path, required=True, help="VCS vectors CSV; only its header is read")
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--mapping-validation", type=Path, required=True)
    parser.add_argument("--canonical-ids", type=Path, default=ROOT / "references" / "canonical_bin_ids.txt")
    parser.add_argument("--definitions", type=Path, default=ROOT / "references" / "bin_definitions.v1.json")
    parser.add_argument("--output", type=Path, default=ROOT / "references" / "array_bin_ranges.v1.json")
    args = parser.parse_args()
    try:
        header, header_hash = _read_header(args.vectors)
        protocol_bytes = args.protocol.read_bytes()
        mapping_bytes = args.mapping_validation.read_bytes()
        result = build_range_catalog(
            header,
            header_sha256=header_hash,
            canonical_ids=args.canonical_ids.read_text(encoding="utf-8").splitlines(),
            definition_catalog=json.loads(args.definitions.read_text(encoding="utf-8")),
            source_protocol=json.loads(protocol_bytes),
            mapping_validation=json.loads(mapping_bytes),
            protocol_sha256=sha256_bytes(protocol_bytes),
            mapping_validation_sha256=sha256_bytes(mapping_bytes),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        output_bytes = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        args.output.write_bytes(output_bytes)
        args.output.with_suffix(args.output.suffix + ".sha256").write_text(
            f"{sha256_bytes(output_bytes)}  {args.output.name}\n", encoding="ascii"
        )
    except (OSError, UnicodeError, ValueError, csv.Error, json.JSONDecodeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": result["status"],
        "array_bin_count": result["mapping"]["total_array_bin_count"],
        "header_sha256": result["source_evidence"]["header_sha256"],
        "historical_hit_counts_imported": result["source_evidence"]["historical_hit_counts_imported"],
    }, indent=2))


if __name__ == "__main__":
    main()
