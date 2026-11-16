"""Audit legacy vector headers against the frozen source-definition catalog.

The historical VCS/URG vectors use two related layouts.  Older runs expose
the canonical labels directly, while the later paper runs expand automatic
bins as ``auto[n]`` and timer arrays as numeric ranges.  This tool resolves
those labels to *source-definition candidates* using explicit value ranges and
ordinal order.  It never imports historical hit values and never grants
coverage credit: an ordinal bridge still needs independent evidence for
sampling, expansion and identity semantics before it can be promoted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

try:
    from tools.audit_source_identity_bridge import (
        _identity_parts,
        _source_cross_members,
        _unwrap_member,
        classify_identity,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from audit_source_identity_bridge import (
        _identity_parts,
        _source_cross_members,
        _unwrap_member,
        classify_identity,
    )


ROOT = Path(__file__).resolve().parents[1]
PINNED_REVISION = "9f20940d494a223cc950a5b98f748fb28109d458"
CATALOG_PATH = ROOT / "references" / "bin_definitions.v1.json"
CANONICAL_IDS_PATH = ROOT / "references" / "canonical_bin_ids.txt"
ARRAY_REFERENCE_PATH = ROOT / "references" / "array_bin_ranges.v1.json"
DEFAULT_OUTPUT = (
    ROOT / "evidence" / "stage10_legacy_vector_header_bridge"
    / "2026-11-16-v1" / "audit.json"
)

DEFAULT_VECTORS = (
    ROOT.parent
    / "opentitan-aon-timer-paper-method-repro"
    / "09_对照与消融"
    / "evidence"
    / "stage09_v30_Full_full1000_20261111"
    / "vectors.csv",
    ROOT.parent
    / "opentitan-aon-timer-paper-method-repro"
    / "08_两层UCB在线复现"
    / "evidence"
    / "stage08_vcs_full_20261104"
    / "vectors.csv",
)

_ARRAY_RANGE = re.compile(
    r"^name:(?P<base>[A-Za-z_][A-Za-z0-9_]*)\[(?P<lo>0[xX][0-9a-fA-F]+|[0-9]+):"
    r"(?P<hi>0[xX][0-9a-fA-F]+|[0-9]+)\]$"
)
_ORDINAL = re.compile(r"^auto\[(?P<index>[0-9]+)\]$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative_source_path(path: Path) -> dict[str, str]:
    """Record a logical sibling-repository path without committing a machine path."""
    resolved = Path(path).resolve()
    for marker in ("opentitan-aon-timer-paper-method-repro",):
        parts = resolved.parts
        if marker in parts:
            index = parts.index(marker)
            return {
                "source_repository": marker,
                "relative_path": Path(*parts[index + 1 :]).as_posix(),
            }
    return {"source_repository": "external", "relative_path": resolved.name}


def _parse_number(text: str) -> int:
    return int(text, 16 if text.lower().startswith("0x") else 10)


def parse_array_range(label: str) -> tuple[str, int, int] | None:
    match = _ARRAY_RANGE.fullmatch(label)
    if not match:
        return None
    low = _parse_number(match.group("lo"))
    high = _parse_number(match.group("hi"))
    if low > high:
        return None
    return match.group("base"), low, high


def parse_ordinal(label: str) -> int | None:
    match = _ORDINAL.fullmatch(label.removeprefix("name:"))
    return int(match.group("index")) if match else None


def _source_definition_indexes(
    definitions: list[dict[str, Any]],
) -> tuple[
    dict[tuple[str, str, str], list[dict[str, Any]]],
    dict[tuple[str, str, str, str], list[dict[str, Any]]],
    dict[tuple[str, str, str, str], list[tuple[str, int, int]]],
]:
    by_prefix: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for definition in definitions:
        by_prefix[(definition["scope"], definition["kind"], definition["item"])].append(definition)

    # Source ``auto[...]`` ranges are stored with numeric value_range metadata;
    # use that metadata instead of guessing whether an unprefixed literal is
    # decimal or hexadecimal.
    variable_ranges: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for (scope, kind, item), peers in by_prefix.items():
        if kind != "variable":
            continue
        rows = [row for row in peers if isinstance(row.get("value_range"), list)]
        if rows:
            ordered = sorted(
                rows,
                key=lambda row: (tuple(row["value_range"]), row["bin_name"]),
            )
            if _continuous_partition([tuple(row["value_range"]) for row in ordered]):
                variable_ranges[(scope, kind, item, "auto")] = ordered

    cross_ranges: dict[tuple[str, str, str, str], list[tuple[str, int, int]]] = defaultdict(list)
    for (scope, kind, item), peers in by_prefix.items():
        if kind != "cross":
            continue
        seen: set[tuple[str, tuple[int, int]]] = set()
        for definition in peers:
            for coverpoint, label, value_range in _source_cross_members(definition):
                if value_range is None:
                    continue
                key = (coverpoint, tuple(value_range))
                if key not in seen:
                    seen.add(key)
                    cross_ranges[(scope, kind, item, coverpoint)].append(
                        (label, value_range[0], value_range[1])
                    )
        for key in [key for key in cross_ranges if key[:3] == (scope, kind, item)]:
            cross_ranges[key].sort(key=lambda row: (row[1], row[2], row[0]))
            if not _continuous_partition([(low, high) for _, low, high in cross_ranges[key]]):
                cross_ranges[key] = []
    return by_prefix, variable_ranges, cross_ranges


def _continuous_partition(ranges: list[tuple[int, int]]) -> bool:
    return bool(ranges) and all(low <= high for low, high in ranges) and all(
        left[1] + 1 == right[0] for left, right in zip(ranges, ranges[1:])
    )


def _array_indexes(
    array_reference: dict[str, Any],
) -> dict[tuple[str, str, str, tuple[int, int]], dict[str, Any]]:
    result: dict[tuple[str, str, str, tuple[int, int]], dict[str, Any]] = {}
    for rows in array_reference.get("arrays", {}).values():
        for row in rows:
            identity = row["canonical_identity"]
            scope, kind, item, label, instance = _identity_parts(identity)
            parsed = parse_array_range(f"name:{row['source_interval_label']}")
            if parsed is None:
                raise ValueError(f"array reference interval is not parseable: {row['source_interval_label']}")
            base, low, high = parsed
            key = (scope, item, base, (low, high))
            if key in result or [low, high] != row["value_range"] or instance != 0:
                raise ValueError("array reference contains duplicate or inconsistent intervals")
            result[key] = {
                **row,
                "canonical_identity": identity,
                "source_scope": scope,
                "source_item": item,
                "source_base": base,
                "source_range": [low, high],
            }
    return result


def _member_matches_ordinal(
    token: str,
    source_label: str,
    source_range: tuple[int, int] | None,
    ordered_ranges: list[tuple[str, int, int]],
) -> bool:
    token = _unwrap_member(token)
    source_label = _unwrap_member(source_label)
    if token == source_label or token.replace(" ", "") == source_label.replace(" ", ""):
        return True
    ordinal = parse_ordinal(token)
    if ordinal is None or source_range is None or ordinal >= len(ordered_ranges):
        return False
    _, low, high = ordered_ranges[ordinal]
    return (low, high) == tuple(source_range)


def _cross_ordinal_candidates(
    identity: str,
    peers: list[dict[str, Any]],
    cross_ranges: dict[tuple[str, str, str, str], list[tuple[str, int, int]]],
) -> tuple[str, list[dict[str, Any]], dict[str, Any]] | None:
    scope, kind, item, label, instance = _identity_parts(identity)
    raw = label.removeprefix("name:")
    tokens = [part.strip() for part in raw.split("X")]
    candidates: list[dict[str, Any]] = []
    used_ordinal = False
    for definition in peers:
        members = _source_cross_members(definition)
        if len(members) != len(tokens):
            continue
        matched = True
        this_used_ordinal = False
        for token, (coverpoint, source_label, source_range) in zip(tokens, members):
            ordered = cross_ranges.get((scope, kind, item, coverpoint), [])
            if not _member_matches_ordinal(token, source_label, source_range, ordered):
                matched = False
                break
            if _unwrap_member(token).replace(" ", "") != _unwrap_member(source_label).replace(" ", ""):
                this_used_ordinal = True
        if matched:
            candidates.append(definition)
            used_ordinal = used_ordinal or this_used_ordinal
    if not candidates:
        return None
    candidates.sort(key=lambda row: row["definition_id"])
    return (
        "CROSS_ORDINAL_CANDIDATE" if used_ordinal else "CROSS_CANDIDATE",
        candidates,
        {"candidate_count": len(candidates), "legacy_instance_index": instance},
    )


def _variable_ordinal_candidate(
    identity: str,
    historical_group: list[tuple[str, int]],
    variable_ranges: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], dict[str, Any]] | None:
    _, kind, _, label, instance = _identity_parts(identity)
    if kind != "variable" or instance != 0:
        return None
    ordinal = parse_ordinal(label)
    if ordinal is None or not variable_ranges:
        return None
    ordinals = sorted(offset for _, offset in historical_group)
    if (ordinals != list(range(len(ordinals))) or len(ordinals) != len(variable_ranges)
            or ordinal >= len(variable_ranges)):
        return (
            "RANGE_ORDER_PARTIAL_CANDIDATE",
            [],
            {
                "reason": "HISTORICAL_ORDINAL_GROUP_IS_NOT_A_COMPLETE_SOURCE_PARTITION",
                "historical_group_size": len(ordinals),
                "source_partition_size": len(variable_ranges),
            },
        )
    candidate = variable_ranges[ordinal]
    return (
        "RANGE_CANDIDATE",
        [candidate],
        {
            "candidate_definition_id": candidate["definition_id"],
            "candidate_ordinal": ordinal,
            "candidate_value_range": candidate.get("value_range"),
        },
    )


def _classify_header(
    identities: list[str],
    canonical_ids: set[str],
    definitions: list[dict[str, Any]],
    array_indexes: dict[tuple[str, str, str, tuple[int, int]], dict[str, Any]],
) -> dict[str, Any]:
    by_prefix, variable_ranges, cross_ranges = _source_definition_indexes(definitions)
    identities_by_prefix_label: dict[tuple[str, str, str, str], list[tuple[str, int]]] = defaultdict(list)
    ordinal_groups: dict[tuple[str, str, str], list[tuple[str, int]]] = defaultdict(list)
    for identity in identities:
        scope, kind, item, label, instance = _identity_parts(identity)
        identities_by_prefix_label[(scope, kind, item, label)].append((identity, instance))
        ordinal = parse_ordinal(label)
        if kind == "variable" and ordinal is not None and instance == 0:
            ordinal_groups[(scope, kind, item)].append((identity, ordinal))

    rows: list[dict[str, Any]] = []
    for identity in identities:
        scope, kind, item, label, instance = _identity_parts(identity)
        peers = by_prefix.get((scope, kind, item), [])
        direct = [row for row in peers if row.get("bin_name") == label.removeprefix("name:")]
        parsed_array = parse_array_range(label)
        if kind == "variable" and parsed_array is not None:
            base, low, high = parsed_array
            reference = array_indexes.get((scope, item, base, (low, high)))
            if reference is not None:
                source_label = reference["canonical_identity"].split("||")[3].removeprefix("name:")
                array_source = [peer for peer in peers if peer["bin_name"] == source_label]
                if len(array_source) != 1 or instance != 0:
                    raise ValueError("array interval does not identify a unique source definition")
                rows.append(
                    {
                        "identity": identity,
                        "classification": "ARRAY_RANGE_CANDIDATE",
                        "candidate_canonical_identity": reference["canonical_identity"],
                        "candidate_definition_ids": [array_source[0]["definition_id"]],
                        "candidate_ordinal": reference["ordinal"],
                        "candidate_source_interval_label": reference["source_interval_label"],
                        "candidate_value_range": [low, high],
                        "coverage_credit_granted": 0,
                    }
                )
                continue

        if kind == "variable" and not direct:
            variable_candidate = _variable_ordinal_candidate(
                identity,
                ordinal_groups.get((scope, kind, item), []),
                variable_ranges.get((scope, kind, item, "auto"), []),
            )
            if variable_candidate is not None and variable_candidate[0] != "RANGE_ORDER_PARTIAL_CANDIDATE":
                status, candidates, details = variable_candidate
                rows.append(
                    {
                        "identity": identity,
                        "classification": status,
                        **details,
                        "candidate_definition_ids": [row["definition_id"] for row in candidates],
                        "coverage_credit_granted": 0,
                    }
                )
                continue

        if kind == "cross":
            ordinal_candidate = _cross_ordinal_candidates(identity, peers, cross_ranges)
            if ordinal_candidate is not None:
                status, candidates, details = ordinal_candidate
                rows.append(
                    {
                        "identity": identity,
                        "classification": status,
                        **details,
                        "candidate_definition_ids": [row["definition_id"] for row in candidates[:8]],
                        "coverage_credit_granted": 0,
                    }
                )
                continue

        source_row = classify_identity(identity, by_prefix, identities_by_prefix_label)
        classification = source_row["classification"]
        if classification == "EXACT_SOURCE_DEFINITION":
            normalized = "EXACT_SEMANTIC_MATCH"
        elif classification in {"RANGE_EXACT_CANDIDATE", "RANGE_ORDER_CANDIDATE"}:
            normalized = "RANGE_CANDIDATE"
        elif classification in {"CROSS_EXACT_LABEL_CANDIDATE", "CROSS_EXPANSION_CANDIDATE"}:
            normalized = "CROSS_CANDIDATE"
        else:
            normalized = "UNRESOLVED"
        row = {
            "identity": identity,
            "classification": normalized,
            "source_bridge_classification": classification,
            "coverage_credit_granted": 0,
        }
        for key in ("candidate_definition_id", "candidate_definition_ids", "candidate_definition_count", "reason"):
            if key in source_row:
                row[key] = source_row[key]
        rows.append(row)

    counts = Counter(row["classification"] for row in rows)
    unresolved = [row for row in rows if row["classification"] == "UNRESOLVED"]
    single_candidates = [
        row["candidate_definition_ids"][0] for row in rows
        if len(row.get("candidate_definition_ids", [])) == 1
        and row.get("candidate_count", 1) == 1
        and row.get("candidate_definition_count", 1) == 1
    ]
    return {
        "historical_identity_count": len(identities),
        "unique_historical_identity_count": len(set(identities)),
        "canonical_identity_overlap_count": sum(identity in canonical_ids for identity in identities),
        "classification_counts": dict(sorted(counts.items())),
        "semantic_candidate_count": len(identities) - len(unresolved),
        "unresolved_count": len(unresolved),
        "unresolved_examples": unresolved[:32],
        "single_source_candidate_count": len(single_candidates),
        "unique_single_source_candidate_count": len(set(single_candidates)),
        "one_to_one_source_candidates_only": (
            len(single_candidates) == len(set(single_candidates)) == len(identities)
        ),
        "coverage_credit_granted": 0,
        "unknowns_inferred_as_misses": 0,
        "promotion_allowed": False,
        "identities": rows,
    }


def audit_vector_headers(
    vector_paths: Iterable[Path],
    *,
    catalog_path: Path = CATALOG_PATH,
    canonical_ids_path: Path = CANONICAL_IDS_PATH,
    array_reference_path: Path = ARRAY_REFERENCE_PATH,
) -> dict[str, Any]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if catalog.get("source_revision") != PINNED_REVISION or catalog.get("definition_count") != 4507:
        raise ValueError("catalog is not the pinned 4,507-definition catalog")
    definitions = catalog["definitions"]
    if len(definitions) != 4507 or len({row["definition_id"] for row in definitions}) != 4507:
        raise ValueError("source-definition catalog must contain 4,507 unique definitions")
    canonical_bytes = canonical_ids_path.read_bytes()
    canonical_ids = canonical_bytes.decode("utf-8").splitlines()
    if len(canonical_ids) != 4507 or len(set(canonical_ids)) != 4507:
        raise ValueError("canonical identity universe must contain 4,507 unique identities")
    array_reference = json.loads(array_reference_path.read_text(encoding="utf-8"))
    if array_reference.get("source_revision") != PINNED_REVISION:
        raise ValueError("array reference is for a different source revision")
    array_indexes = _array_indexes(array_reference)
    reports = []
    for raw_path in vector_paths:
        path = Path(raw_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        with path.open("rb") as binary:
            header_bytes = binary.readline()
        with path.open("r", encoding="utf-8", newline="") as handle:
            header = next(csv.reader(handle))
        if len(header) < 3 or header[:2] != ["run_id", "accepted"]:
            raise ValueError(f"unexpected vectors header: {path}")
        identities = header[2:]
        if len(identities) != 4507 or len(set(identities)) != 4507:
            raise ValueError(f"vectors header is not a unique 4,507-column header: {path}")
        report = _classify_header(identities, set(canonical_ids), definitions, array_indexes)
        report.update(
            {
                "path": _relative_source_path(path),
                "file_size_bytes": path.stat().st_size,
                "file_sha256": sha256_file(path),
                "header_sha256": sha256_bytes(header_bytes),
                "header_column_count": len(header),
                "header_identity_order_sha256": sha256_bytes("\n".join(identities).encode("utf-8")),
            }
        )
        if report["canonical_identity_overlap_count"] == 4507:
            report.pop("identities")
            report["identity_details_omitted"] = (
                "The complete canonical identity candidates are already recorded in the source identity bridge audit."
            )
        reports.append(report)

    all_complete = all(report["unresolved_count"] == 0 for report in reports)
    return {
        "schema": "aon-timer-legacy-vector-header-bridge-audit-v1",
        "status": "ALL_HEADERS_CLASSIFIED_CANDIDATES_NOT_PROMOTED" if all_complete else "SEMANTIC_HEADER_BRIDGE_INCOMPLETE",
        "source_revision": PINNED_REVISION,
        "canonical_identity_count": 4507,
        "source_definition_count": len(definitions),
        "vector_header_count": len(reports),
        "vectors": reports,
        "coverage_credit_granted": 0,
        "unknowns_inferred_as_misses": 0,
        "promotion_allowed": False,
        "promotion_blockers": [
            "Header semantics do not prove that VCS/URG hit counts correspond to the current Verilator/Cocotb sample protocol.",
            "Ordinal auto-bin expansion requires independent evidence for ordering and instance semantics.",
            "Historical hit values are deliberately not imported into the open-source coverage matrix.",
        ],
        "input_sha256": {
            "catalog": sha256_file(catalog_path),
            "canonical_bin_ids": sha256_bytes(canonical_bytes),
            "array_reference": sha256_file(array_reference_path),
        },
        "audit_tool_sha256": sha256_file(Path(__file__)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector", type=Path, action="append", dest="vectors")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    vectors = args.vectors or list(DEFAULT_VECTORS)
    result = audit_vector_headers(vectors)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{sha256_file(output)}  {output.name}\n", encoding="ascii"
    )
    print(json.dumps({
        "status": result["status"],
        "vector_header_count": result["vector_header_count"],
        "classification_counts": [
            report["classification_counts"] for report in result["vectors"]
        ],
        "coverage_credit_granted": 0,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
