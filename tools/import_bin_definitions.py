"""Import bin definitions from the pinned public URG manifest.

The exporter deliberately drops all run results and score fields.  It retains
only type-level bin definitions, source locations, value ranges, cross labels,
and the number of expanded instances represented by a type definition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


PINNED_REVISION = "9f20940d494a223cc950a5b98f748fb28109d458"
EXPECTED_BINS = 4507
EXPECTED_AON_BINS = 4279
AUTO_RANGE = re.compile(r"^auto\[([0-9a-fA-F]+):([0-9a-fA-F]+)\]$")
AUTO_SINGLETON = re.compile(r"^auto\[(\d+)\]$")
CROSS_MEMBERS = re.compile(r"^([^=]+)=(.*?)\s+x\s+([^=]+)=(.*)$")
ARRAY_BIN = re.compile(r"^(prescale|bark|bite|wkup)\[(\d+)\]$")
AON_ARRAYS = {
    "prescale_cp": {"name": "prescale", "count": 32, "value_range": [1, 4095]},
    "bark_thold_cp": {"name": "bark", "count": 32, "value_range": [1, (1 << 32) - 1]},
    "bite_thold_cp": {"name": "bite", "count": 32, "value_range": [1, (1 << 32) - 1]},
    "wkup_thold_cp": {"name": "wkup", "count": 64, "value_range": [1, (1 << 64) - 1]},
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _aon_value_width(covergroup: str, item: str) -> int | None:
    if not covergroup.startswith("aon_timer_env_pkg::aon_timer_env_cov::"):
        return None
    if covergroup.endswith("wake_up_timer_thold_hit_cg"):
        return 64 if item in {"wkup_count_cp", "wkup_thold_cp"} else None
    if covergroup.endswith(("watchdog_timer_bark_thold_hit_cg", "watchdog_timer_bite_thold_hit_cg")):
        return 32 if item in {"wdog_count_cp", "wdog_thold_cp"} else None
    return None


def _parse_range(label: str, *, width: int | None) -> list[int] | None:
    singleton = AUTO_SINGLETON.fullmatch(label)
    if singleton:
        value = int(singleton.group(1))
        return [value, value]
    match = AUTO_RANGE.fullmatch(label)
    if not match or width not in (32, 64):
        return None
    base = 16 if width == 64 else 10
    start, end = (int(part, base) for part in match.groups())
    if start > end or end >= (1 << width):
        raise ValueError(f"invalid {width}-bit range in {label!r}")
    return [start, end]


def _parse_cross(label: str, *, covergroup: str) -> dict[str, Any] | None:
    match = CROSS_MEMBERS.fullmatch(label)
    if not match:
        return None
    left_name, left_label, right_name, right_label = match.groups()
    left_width = _aon_value_width(covergroup, left_name)
    right_width = _aon_value_width(covergroup, right_name)
    return {
        "members": [
            {"coverpoint": left_name, "bin_label": left_label,
             "value_range": _parse_range(left_label, width=left_width)},
            {"coverpoint": right_name, "bin_label": right_label,
             "value_range": _parse_range(right_label, width=right_width)},
        ]
    }


def build_catalog(manifest: dict[str, Any], *, manifest_sha256: str) -> dict[str, Any]:
    source = manifest.get("source", {})
    if source.get("open_titan_commit") != PINNED_REVISION:
        raise ValueError("bin-definition manifest does not match the pinned OpenTitan revision")
    if not isinstance(manifest.get("bins"), list):
        raise ValueError("bin-definition manifest has no bins list")

    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in manifest["bins"]:
        required = ("covergroup", "bin_type", "coverpoint_or_cross", "bin_name", "source_file", "source_line")
        if any(key not in row for key in required):
            raise ValueError("manifest bin entry is missing definition metadata")
        covergroup = row["covergroup"]
        kind = "cross" if row["bin_type"] == "cross" else "variable"
        item = row["coverpoint_or_cross"]
        name = row["bin_name"]
        key = (covergroup, kind, item, name)
        width = _aon_value_width(covergroup, item)
        definition = {
            "scope": covergroup,
            "kind": kind,
            "item": item,
            "bin_name": name,
            "definition_id": "||".join((covergroup, kind, item, name)),
            "source_file": row["source_file"],
            "source_line": row["source_line"],
        }
        if covergroup.endswith("::timer_cfg_cg") and kind == "variable" and item in AON_ARRAYS:
            array_match = ARRAY_BIN.fullmatch(name)
            array_spec = AON_ARRAYS[item]
            if array_match and array_match.group(1) == array_spec["name"]:
                definition["array_bin"] = {
                    "index": int(array_match.group(2)),
                    "count": array_spec["count"],
                    "declared_value_range": array_spec["value_range"],
                    "individual_value_range": None,
                    "partition_status": "ARRAY_INDEX_AND_DECLARED_DOMAIN_KNOWN_BOUNDARIES_UNRESOLVED",
                }
        value_range = _parse_range(name, width=width)
        if value_range is not None:
            definition["value_range"] = value_range
            definition["value_width"] = width
        if kind == "cross":
            cross = _parse_cross(name, covergroup=covergroup)
            if cross is not None:
                definition["cross_definition"] = cross
        prior = unique.get(key)
        if prior is not None:
            comparable = {k: v for k, v in prior.items() if k != "instance_record_count"}
            if comparable != definition:
                raise ValueError(f"inconsistent expanded definitions for {key!r}")
            prior["instance_record_count"] += 1
        else:
            definition["instance_record_count"] = 1
            unique[key] = definition

    records = [unique[key] for key in sorted(unique)]
    aon_count = sum(item["scope"].startswith("aon_timer_env_pkg::") for item in records)
    if len(records) != len(unique):
        raise ValueError("bin-definition identity collision")
    if manifest.get("counts", {}).get("unique_type_bin_definitions") != len(records):
        raise ValueError("unique type-definition count disagrees with the manifest metadata")
    if manifest.get("counts", {}).get("aon_timer_bins") != aon_count:
        raise ValueError("AON Timer type-definition count disagrees with the manifest metadata")

    partition_audits = []
    expected_auto_counts = {
        ("wake_up_timer_thold_hit_cg", "wkup_count_cp"): 512,
        ("wake_up_timer_thold_hit_cg", "wkup_thold_cp"): 512,
        ("watchdog_timer_bark_thold_hit_cg", "wdog_count_cp"): 256,
        ("watchdog_timer_bark_thold_hit_cg", "wdog_thold_cp"): 256,
        ("watchdog_timer_bite_thold_hit_cg", "wdog_count_cp"): 256,
        ("watchdog_timer_bite_thold_hit_cg", "wdog_thold_cp"): 256,
    }
    is_full_reference_manifest = (
        manifest.get("counts", {}).get("unique_type_bin_definitions") == EXPECTED_BINS
        and len(records) == EXPECTED_BINS
    )
    for (group_leaf, item), expected_count in sorted(expected_auto_counts.items()):
        if not is_full_reference_manifest:
            break
        definitions = [
            entry for entry in records
            if entry["scope"].endswith(f"::{group_leaf}") and entry["item"] == item
            and "value_range" in entry
        ]
        ranges = sorted(entry["value_range"] for entry in definitions)
        width = _aon_value_width(definitions[0]["scope"], item) if definitions else None
        domain_max = (1 << width) - 1 if width is not None else None
        contiguous = bool(ranges) and ranges[0][0] == 0 and ranges[-1][1] == domain_max
        if contiguous:
            contiguous = all(left[1] + 1 == right[0] for left, right in zip(ranges, ranges[1:]))
        partition_audits.append({
            "covergroup": group_leaf,
            "coverpoint": item,
            "expected_auto_bin_max": expected_count,
            "observed_ranges": len(ranges),
            "value_width": width,
            "domain": [0, domain_max] if domain_max is not None else None,
            "complete_non_overlapping_partition": len(ranges) == expected_count and contiguous,
        })
    if any(not item["complete_non_overlapping_partition"] for item in partition_audits):
        raise ValueError("auto-bin value ranges do not form the expected complete partition")

    cross_audits = []
    expected_crosses = {
        "wake_up_timer_thold_hit_cg": ("wkup_thold_cpXwkup_int_cp", 512, {"set", "unset"}),
        "watchdog_timer_bark_thold_hit_cg": ("wdog_thold_cpXwdog_bark_rst", 256, {"auto[0]", "auto[1]"}),
        "watchdog_timer_bite_thold_hit_cg": ("wdog_thold_cpXwdog_bite_rst", 256, {"auto[0]", "auto[1]"}),
    }
    for group_leaf, (cross_item, left_count, right_labels) in sorted(expected_crosses.items()):
        if not is_full_reference_manifest:
            break
        cross_entries = [
            entry for entry in records
            if entry["scope"].endswith(f"::{group_leaf}") and entry["kind"] == "cross"
            and entry["item"] == cross_item and "cross_definition" in entry
        ]
        expected_pairs = set()
        left_ranges = {
            tuple(entry["value_range"]) for entry in records
            if entry["scope"].endswith(f"::{group_leaf}") and entry["kind"] == "variable"
            and entry["item"] == ("wkup_thold_cp" if group_leaf.startswith("wake") else "wdog_thold_cp")
            and "value_range" in entry
        }
        for value_range in left_ranges:
            for right_label in right_labels:
                right_range = _parse_range(right_label, width=None)
                expected_pairs.add((value_range, tuple(right_range) if right_range is not None else right_label))
        actual_pairs = set()
        for entry in cross_entries:
            members = entry["cross_definition"]["members"]
            left, right = members
            left_value = tuple(left["value_range"]) if left["value_range"] is not None else left["bin_label"]
            right_value = tuple(right["value_range"]) if right["value_range"] is not None else right["bin_label"]
            actual_pairs.add((left_value, right_value))
        complete = len(cross_entries) == left_count * len(right_labels) and actual_pairs == expected_pairs
        if not complete:
            raise ValueError(f"{group_leaf} cross definitions do not match the expected Cartesian product")
        cross_audits.append({
            "covergroup": group_leaf,
            "cross": cross_item,
            "expected_combinations": left_count * len(right_labels),
            "observed_combinations": len(actual_pairs),
            "complete_cartesian_product": True,
        })

    return {
        "schema": "aon-timer-bin-definitions-v1",
        "status": "REFERENCE_DEFINITIONS_IMPORTED_LEGACY_IDENTITY_BRIDGE_PARTIAL",
        "source_revision": PINNED_REVISION,
        "source_manifest_sha256": manifest_sha256,
        "definition_count": len(records),
        "aon_timer_definition_count": aon_count,
        "shared_or_other_definition_count": len(records) - aon_count,
        "expanded_manifest_record_count": len(manifest["bins"]),
        "auto_bin_partition_audit": partition_audits,
        "cross_bin_partition_audit": cross_audits,
        "array_bin_partition_status": "ARRAY_INDICES_AND_DECLARED_DOMAINS_KNOWN_INDIVIDUAL_BOUNDARIES_UNRESOLVED",
        "definition_identity_format": "<covergroup_scope>||<variable_or_cross>||<item>||<bin_name>",
        "hit_counts_included": False,
        "legacy_identity_note": (
            "The legacy CSV header collapses some cross labels and represents several shared-group "
            "instances differently. These definitions are not silently assigned to legacy columns."
        ),
        "definitions": records,
    }


def import_manifest(manifest_path: Path, output_path: Path, *, expected_counts: bool = True) -> dict[str, Any]:
    manifest_bytes = Path(manifest_path).read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    catalog = build_catalog(manifest, manifest_sha256=sha256_bytes(manifest_bytes))
    if expected_counts and (
        catalog["definition_count"] != EXPECTED_BINS
        or catalog["aon_timer_definition_count"] != EXPECTED_AON_BINS
    ):
        raise ValueError(
            "expected 4,507 unique definitions including 4,279 AON Timer definitions; "
            f"found {catalog['definition_count']} and {catalog['aon_timer_definition_count']}"
        )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_bytes = (json.dumps(catalog, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    output_path.write_bytes(output_bytes)
    catalog["catalog_sha256"] = sha256_bytes(output_bytes)
    output_path.with_suffix(output_path.suffix + ".sha256").write_text(
        f"{catalog['catalog_sha256']}  {output_path.name}\n", encoding="ascii"
    )
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path,
        default=Path(__file__).resolve().parents[1] / "references" / "bin_definitions.v1.json",
    )
    args = parser.parse_args()
    try:
        result = import_manifest(args.manifest, args.output)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps({key: result[key] for key in (
        "schema", "status", "definition_count", "aon_timer_definition_count",
        "shared_or_other_definition_count", "expanded_manifest_record_count", "catalog_sha256",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
