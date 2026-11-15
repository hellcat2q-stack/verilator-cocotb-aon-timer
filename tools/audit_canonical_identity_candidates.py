"""Diagnose canonical labels against pinned type-level bin definitions.

This audit never grants coverage credit for a candidate relationship.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PINNED_REVISION = "9f20940d494a223cc950a5b98f748fb28109d458"
VALUE_RANGE = re.compile(
    r"values:\s*\{\s*\[\s*(?:(\d+)'h([0-9a-fA-F]+)|(\d+))"
    r"\s*:\s*(?:(\d+)'h([0-9a-fA-F]+)|(\d+))\s*\]\s*\}"
)


def parse_value_range(label: str) -> tuple[int, int] | None:
    match = VALUE_RANGE.fullmatch(label.removeprefix("name:"))
    if not match:
        return None
    low = int(match.group(2), 16) if match.group(1) else int(match.group(3))
    high = int(match.group(5), 16) if match.group(4) else int(match.group(6))
    if low > high:
        raise ValueError("canonical value range has descending bounds")
    return low, high


def range_relationship(target: tuple[int, int], ranges: list[tuple[int, int]]) -> tuple[str, list[int]]:
    exact = [i for i, bounds in enumerate(ranges) if bounds == target]
    if exact:
        return "EXACT_VALUE_RANGE_TYPE_CANDIDATE_INSTANCE_UNRESOLVED", exact
    intersecting = sorted((low, high, i) for i, (low, high) in enumerate(ranges)
                          if low <= target[1] and high >= target[0])
    if not intersecting:
        return "NO_SOURCE_RANGE_CANDIDATE", []
    cursor = target[0]
    for low, high, _ in intersecting:
        low, high = max(low, target[0]), min(high, target[1])
        if low < cursor:
            return "OVERLAPPING_SOURCE_RANGE_CANDIDATE", [row[2] for row in intersecting]
        if low > cursor:
            return "PARTIAL_OR_GAPPED_VALUE_RANGE_CANDIDATE", [row[2] for row in intersecting]
        cursor = high + 1
    if cursor == target[1] + 1:
        return "COMPOSITE_VALUE_RANGE_TYPE_CANDIDATE_INSTANCE_UNRESOLVED", [row[2] for row in intersecting]
    return "PARTIAL_OR_GAPPED_VALUE_RANGE_CANDIDATE", [row[2] for row in intersecting]


def classify_identity(identity: str, definitions: list[dict[str, Any]]) -> dict[str, Any]:
    parts = identity.split("||")
    if len(parts) != 5:
        raise ValueError("canonical identity has an invalid field count")
    scope, kind, item, label, instance = parts
    direct_label = label.removeprefix("name:")
    peers = [row for row in definitions
             if (row.get("scope"), row.get("kind"), row.get("item")) == (scope, kind, item)]
    direct = [row for row in peers if row.get("bin_name") == direct_label]
    if len(direct) == 1 and instance == "0":
        return {"identity": identity, "classification": "DIRECT_TYPE_IDENTITY_MATCH",
                "candidate_definition_count": 1, "candidate_definition_ids": [direct[0]["definition_id"]]}
    target = parse_value_range(label)
    if target is not None:
        source_rows = [row for row in peers if isinstance(row.get("value_range"), list)
                       and len(row["value_range"]) == 2]
        ranges = [(row["value_range"][0], row["value_range"][1]) for row in source_rows]
        relation, indexes = range_relationship(target, ranges)
        return {"identity": identity, "classification": relation, "legacy_instance_index": instance,
                "canonical_value_range": list(target), "candidate_definition_count": len(indexes),
                "candidate_definition_ids": [source_rows[i]["definition_id"] for i in indexes[:8]]}
    if direct:
        classification = "DIRECT_LABEL_BUT_INSTANCE_IDENTITY_UNRESOLVED"
    elif kind == "cross":
        classification = "CROSS_LABEL_OR_EXPANSION_UNRESOLVED"
    else:
        classification = "VALUE_LABEL_OR_SOURCE_MAPPING_UNRESOLVED"
    return {"identity": identity, "classification": classification, "legacy_instance_index": instance,
            "candidate_definition_count": len(direct),
            "candidate_definition_ids": [row["definition_id"] for row in direct[:8]]}


def build_audit(canonical_ids: list[str], catalog: dict[str, Any]) -> dict[str, Any]:
    if catalog.get("schema") != "aon-timer-bin-definitions-v1":
        raise ValueError("unsupported source bin-definition catalog")
    if catalog.get("source_revision") != PINNED_REVISION:
        raise ValueError("source bin-definition catalog revision mismatch")
    if len(canonical_ids) != 4507 or len(set(canonical_ids)) != 4507:
        raise ValueError("canonical identity universe must contain 4,507 unique identities")
    definitions = catalog.get("definitions")
    if not isinstance(definitions, list) or len(definitions) != 4507:
        raise ValueError("source definition catalog must contain 4,507 definitions")
    rows = [classify_identity(identity, definitions) for identity in canonical_ids]
    counts = Counter(row["classification"] for row in rows)
    by_scope_item = Counter((row["identity"].split("||")[0].split("::")[-1],
                             row["identity"].split("||")[2], row["classification"]) for row in rows)
    return {
        "schema": "aon-timer-canonical-identity-candidate-audit-v1",
        "status": "DIAGNOSTIC_ONLY_NO_NEW_COVERAGE_MAPPING_CLAIM",
        "source_revision": PINNED_REVISION,
        "canonical_identity_count": len(canonical_ids),
        "source_definition_count": len(definitions),
        "classification_counts": dict(sorted(counts.items())),
        "by_covergroup_and_item": [
            {"covergroup": group, "item": item, "classification": classification, "count": count}
            for (group, item, classification), count in sorted(by_scope_item.items())
        ],
        "identities": rows,
        "coverage_credit_granted": 0,
        "unknowns_inferred_as_misses": 0,
        "note": "Value-range candidates are diagnostic only. Legacy occurrence indexes, cross expansion, and sample-site semantics are not inferred.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-ids", type=Path, default=ROOT / "references/canonical_bin_ids.txt")
    parser.add_argument("--catalog", type=Path, default=ROOT / "references/bin_definitions.v1.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ids_bytes = args.bin_ids.read_bytes()
    catalog_bytes = args.catalog.read_bytes()
    result = build_audit(ids_bytes.decode("utf-8").splitlines(), json.loads(catalog_bytes))
    result["input_sha256"] = {"canonical_bin_ids": hashlib.sha256(ids_bytes).hexdigest(),
                              "source_bin_definitions": hashlib.sha256(catalog_bytes).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "classification_counts": result["classification_counts"],
                      "coverage_credit_granted": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
