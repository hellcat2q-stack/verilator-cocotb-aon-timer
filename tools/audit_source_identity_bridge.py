"""Audit the frozen legacy identities against the pinned source definitions.

This tool is deliberately an audit of *identity candidates*.  It does not
turn a candidate into a coverage hit, infer misses, or claim Verilator/UVM/VCS
equivalence.  The legacy URG export contains compressed automatic bins and
wildcard cross labels; those labels can describe several source definitions.
The report therefore records the candidate set and marks non-unique matches as
unresolved even when a deterministic range/order candidate can be proposed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
PINNED_REVISION = "9f20940d494a223cc950a5b98f748fb28109d458"
CANONICAL_IDS = ROOT / "references" / "canonical_bin_ids.txt"
CATALOG = ROOT / "references" / "bin_definitions.v1.json"
DEFAULT_OUTPUT = (
    ROOT / "evidence" / "stage10_identity_bridge" / "2026-11-16-v1" / "bridge.json"
)

_VALUE_RANGE = re.compile(
    r"^values:\s*\{\s*\[\s*"
    r"(?:(?P<lw>\d+)'h)?(?P<lo>[0-9a-fA-F]+)\s*:\s*"
    r"(?:(?P<hw>\d+)'h)?(?P<hi>[0-9a-fA-F]+)\s*\]\s*\}$",
    re.IGNORECASE,
)
_VALUE_SINGLE = re.compile(
    r"^values:\s*(?:\{\s*|\[\{\s*)\[\s*"
    r"(?:(?P<w>\d+)'h)?(?P<v>[0-9a-fA-F]+)\s*\]\s*\}\s*\]?$",
    re.IGNORECASE,
)
_AUTO_RANGE = re.compile(
    r"^auto\[(?P<lo>[0-9a-fA-F]+):(?P<hi>[0-9a-fA-F]+)\]$",
    re.IGNORECASE,
)
_AUTO_SINGLE = re.compile(r"^auto\[(?P<v>[0-9a-fA-F]+)\]$", re.IGNORECASE)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _parse_number(text: str, width: str | None) -> int:
    # A sized literal is hexadecimal.  URG's unsized values are decimal in
    # the frozen identities, while source auto labels are hexadecimal for the
    # 64-bit count coverpoints and decimal for the 32-bit ones.
    return int(text, 16 if width else 10)


def parse_value_range(label: str) -> tuple[int, int] | None:
    """Parse URG ``values:{[...]}`` and source ``auto[...]`` labels."""
    raw = label.removeprefix("name:").strip()
    match = _VALUE_RANGE.fullmatch(raw)
    if match:
        if (match.group("lw") or match.group("hw")) and match.group("lw") != match.group("hw"):
            return None
        low = _parse_number(match.group("lo"), match.group("lw"))
        high = _parse_number(match.group("hi"), match.group("hw"))
        return (low, high) if low <= high else None
    match = _VALUE_SINGLE.fullmatch(raw)
    if match:
        value = _parse_number(match.group("v"), match.group("w"))
        return value, value
    match = _AUTO_RANGE.fullmatch(raw)
    if match:
        low, high = int(match.group("lo"), 16), int(match.group("hi"), 16)
        return (low, high) if low <= high else None
    match = _AUTO_SINGLE.fullmatch(raw)
    if match:
        value = int(match.group("v"), 16)
        return value, value
    return None


def _identity_parts(identity: str) -> tuple[str, str, str, str, int]:
    parts = identity.split("||")
    if len(parts) != 5 or not parts[4].isdecimal():
        raise ValueError(f"invalid canonical identity: {identity!r}")
    return parts[0], parts[1], parts[2], parts[3], int(parts[4])


def _source_cross_members(definition: dict[str, Any]) -> list[tuple[str, str, tuple[int, int] | None]]:
    """Read cross members, repairing older catalog rows if necessary."""
    cross = definition.get("cross_definition")
    members = cross.get("members") if isinstance(cross, dict) else None
    if isinstance(members, list) and len(members) >= 2:
        parsed = []
        for member in members:
            if not isinstance(member, dict):
                parsed = []
                break
            coverpoint = str(member.get("coverpoint", ""))
            label = str(member.get("bin_label", ""))
            if not coverpoint or not label:
                parsed = []
                break
            parsed.append((coverpoint, label, tuple(member["value_range"]) if isinstance(member.get("value_range"), list) else None))
        if parsed:
            # The historical importer split an interrupt cross member on the
            # first `` x `` inside its label.  The source bin name is the
            # authoritative fallback for those malformed rows.
            expected = definition.get("bin_name", "")
            if len(parsed) == len(expected.split(" x ")):
                return parsed
    parsed = []
    for raw_member in str(definition.get("bin_name", "")).split(" x "):
        coverpoint, separator, label = raw_member.partition("=")
        if not separator or not coverpoint or not label:
            return []
        parsed.append((coverpoint.strip(), label.strip(), parse_value_range(label.strip())))
    return parsed


def _split_cross_label(label: str) -> list[str]:
    raw = label.removeprefix("name:").strip()
    # Cross separators in the URG labels are uppercase X.  There are no X
    # characters in the source bin labels themselves.
    return [part.strip() for part in raw.split("X")]


def _unwrap_member(token: str) -> str:
    token = token.strip()
    while len(token) >= 2 and token[0] == "[" and token[-1] == "]":
        token = token[1:-1].strip()
    return token


def _token_ranges(token: str) -> list[tuple[int, int]]:
    token = _unwrap_member(token)
    ranges: list[tuple[int, int]] = []
    for match in re.finditer(r"auto\[([0-9a-fA-F]+):([0-9a-fA-F]+)\]", token, re.IGNORECASE):
        low, high = int(match.group(1), 16), int(match.group(2), 16)
        if low <= high:
            ranges.append((low, high))
    parsed = parse_value_range(token)
    if parsed is not None:
        ranges.append(parsed)
    return ranges


def _member_matches(token: str, source_label: str, source_range: tuple[int, int] | None) -> bool:
    token = _unwrap_member(token)
    source_label = _unwrap_member(source_label)
    if token == "*":
        return True
    if token == source_label or re.sub(r"\s+", "", token) == re.sub(r"\s+", "", source_label):
        return True
    # URG may merge a stable value bin and a transition bin into one cross
    # label.  The source covergroup stores the transition as the cross member;
    # matching the explicit transition component is safe at the definition
    # layer and still leaves repeated legacy instances unresolved.
    transition = re.search(r"transitions\[[^]]+\]", token, re.IGNORECASE)
    if transition and transition.group(0).lower() == source_label.lower():
        return True
    value = re.search(r"values\[[^]]+\]", token, re.IGNORECASE)
    if value and value.group(0).lower() == source_label.lower():
        return True
    token_ranges = _token_ranges(token)
    if source_range is not None and token_ranges:
        return any(low <= source_range[0] and source_range[1] <= high for low, high in token_ranges)
    # URG prints some named values with a surrounding bracket only.
    return token.replace(" ", "") == source_label.replace(" ", "")


def _range_candidates(
    identity: str,
    peers: list[dict[str, Any]],
    all_identities_for_group: list[tuple[str, int]],
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    scope, kind, item, label, instance = _identity_parts(identity)
    target = parse_value_range(label)
    source_rows = [row for row in peers if isinstance(row.get("value_range"), list)]
    source_rows.sort(key=lambda row: (row["value_range"][0], row["value_range"][1], row["bin_name"]))
    if target is None or not source_rows:
        return "UNRESOLVED", [], {"reason": "NO_PARSEABLE_SOURCE_RANGE"}
    exact = [row for row in source_rows if tuple(row["value_range"]) == target]
    covered = [row for row in source_rows if row["value_range"][0] >= target[0] and row["value_range"][1] <= target[1]]
    covered.sort(key=lambda row: (row["value_range"][0], row["value_range"][1], row["bin_name"]))
    contiguous = bool(covered) and covered[0]["value_range"][0] == target[0]
    if contiguous:
        contiguous = all(left["value_range"][1] + 1 == right["value_range"][0] for left, right in zip(covered, covered[1:]))
        contiguous = contiguous and covered[-1]["value_range"][1] == target[1]
    group_instances = sorted(offset for _, offset in all_identities_for_group)
    if exact and len(exact) == 1 and len(group_instances) == 1 and instance == 0:
        return "RANGE_EXACT_CANDIDATE", exact, {"candidate_definition_id": exact[0]["definition_id"]}
    if contiguous and len(covered) == len(group_instances) and group_instances == list(range(len(group_instances))):
        candidate = covered[instance] if 0 <= instance < len(covered) else None
        return (
            "RANGE_ORDER_CANDIDATE",
            [candidate] if candidate else [],
            {"candidate_order": instance, "partition_size": len(covered), "candidate_definition_id": candidate["definition_id"] if candidate else None},
        )
    if exact:
        return "RANGE_INSTANCE_UNRESOLVED", exact, {"candidate_count": len(exact)}
    if covered and contiguous:
        return "RANGE_ORDER_PARTIAL_CANDIDATE", covered, {"candidate_count": len(covered), "partition_size": len(covered)}
    return "UNRESOLVED", [], {"reason": "SOURCE_RANGE_DOES_NOT_COVER_CANONICAL_RANGE"}


def _cross_candidates(identity: str, peers: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    _, _, _, label, instance = _identity_parts(identity)
    tokens = _split_cross_label(label)
    candidates = []
    for definition in peers:
        members = _source_cross_members(definition)
        if len(members) != len(tokens):
            continue
        if all(_member_matches(token, source_label, source_range)
               for token, (_, source_label, source_range) in zip(tokens, members)):
            candidates.append(definition)
    candidates.sort(key=lambda row: row["definition_id"])
    if len(candidates) == 1 and instance == 0:
        return "CROSS_EXACT_LABEL_CANDIDATE", candidates, {"candidate_definition_id": candidates[0]["definition_id"]}
    if candidates:
        return "CROSS_EXPANSION_CANDIDATE", candidates, {"candidate_count": len(candidates), "legacy_instance": instance}
    return "UNRESOLVED", [], {"reason": "NO_SOURCE_CROSS_MATCH", "legacy_instance": instance}


def classify_identity(
    identity: str,
    definitions_by_prefix: dict[tuple[str, str, str], list[dict[str, Any]]],
    identities_by_prefix_label: dict[tuple[str, str, str, str], list[tuple[str, int]]],
) -> dict[str, Any]:
    scope, kind, item, label, instance = _identity_parts(identity)
    peers = definitions_by_prefix.get((scope, kind, item), [])
    direct_label = label.removeprefix("name:")
    direct = [row for row in peers if row.get("bin_name") == direct_label]
    details: dict[str, Any] = {"legacy_instance_index": instance}
    if kind == "variable" and direct and instance == 0:
        return {"identity": identity, "classification": "EXACT_SOURCE_DEFINITION", "candidate_definition_ids": [direct[0]["definition_id"]], **details}
    if kind == "variable" and parse_value_range(label) is not None:
        status, candidates, extra = _range_candidates(
            identity, peers, identities_by_prefix_label.get((scope, kind, item, label), [])
        )
    elif kind == "cross":
        status, candidates, extra = _cross_candidates(identity, peers)
    elif direct:
        status, candidates, extra = "INSTANCE_UNRESOLVED", direct, {"candidate_count": len(direct)}
    else:
        status, candidates, extra = "UNRESOLVED", [], {"reason": "NO_SOURCE_LABEL_MATCH"}
    result = {"identity": identity, "classification": status, **details, **extra}
    if candidates:
        result["candidate_definition_ids"] = [row["definition_id"] for row in candidates[:8]]
        result["candidate_definition_count"] = len(candidates)
    return result


def build_audit(canonical_ids: list[str], catalog: dict[str, Any]) -> dict[str, Any]:
    if catalog.get("source_revision") != PINNED_REVISION or len(catalog.get("definitions", [])) != 4507:
        raise ValueError("catalog is not the pinned 4,507-definition catalog")
    if len(canonical_ids) != 4507 or len(set(canonical_ids)) != len(canonical_ids):
        raise ValueError("canonical identity universe must contain 4,507 unique identities")
    definitions_by_prefix: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for definition in catalog["definitions"]:
        definitions_by_prefix[(definition["scope"], definition["kind"], definition["item"])].append(definition)
    identities_by_prefix_label: dict[tuple[str, str, str, str], list[tuple[str, int]]] = defaultdict(list)
    for identity in canonical_ids:
        scope, kind, item, label, instance = _identity_parts(identity)
        identities_by_prefix_label[(scope, kind, item, label)].append((identity, instance))
    rows = [classify_identity(identity, definitions_by_prefix, identities_by_prefix_label) for identity in canonical_ids]
    counts = Counter(row["classification"] for row in rows)
    exact = [row for row in rows if row["classification"] == "EXACT_SOURCE_DEFINITION"]
    candidate = [row for row in rows if row["classification"] in {"RANGE_EXACT_CANDIDATE", "RANGE_ORDER_CANDIDATE", "CROSS_EXACT_LABEL_CANDIDATE"}]
    ambiguous = [row for row in rows if row["classification"] in {"RANGE_INSTANCE_UNRESOLVED", "RANGE_ORDER_PARTIAL_CANDIDATE", "CROSS_EXPANSION_CANDIDATE", "INSTANCE_UNRESOLVED"}]
    definition_ids = [row.get("candidate_definition_ids", [None])[0] for row in exact + candidate if row.get("candidate_definition_ids")]
    return {
        "schema": "aon-timer-source-identity-bridge-audit-v1",
        "status": "CANDIDATE_ONLY_LEGACY_BRIDGE_NOT_PROMOTED",
        "source_revision": PINNED_REVISION,
        "canonical_identity_count": len(canonical_ids),
        "source_definition_count": len(catalog["definitions"]),
        "classification_counts": dict(sorted(counts.items())),
        "exact_source_definition_count": len(exact),
        "deterministic_candidate_count": len(candidate),
        "ambiguous_candidate_count": len(ambiguous),
        "unresolved_count": counts.get("UNRESOLVED", 0),
        "candidate_definition_ids_are_unique_for_exact_and_deterministic_rows": len(definition_ids) == len(set(definition_ids)),
        "coverage_credit_granted": 0,
        "unknowns_inferred_as_misses": 0,
        "promotion_allowed": False,
        "promotion_blockers": [
            "Compressed auto-bin and wildcard cross labels are not injective source identities.",
            "A complete bridge requires independent URG/VCS evidence for ordering and expansion semantics.",
            "Shared/non-AON sample sites are outside the current Cocotb trace protocol.",
        ],
        "identities": rows,
        "input_sha256": {},
        "note": "Candidate mappings are diagnostic only and never add legacy coverage credit.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-ids", type=Path, default=CANONICAL_IDS)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    ids_bytes = args.bin_ids.read_bytes()
    catalog_bytes = args.catalog.read_bytes()
    canonical_ids = ids_bytes.decode("utf-8").splitlines()
    result = build_audit(canonical_ids, json.loads(catalog_bytes.decode("utf-8")))
    result["input_sha256"] = {
        "canonical_bin_ids": hashlib.sha256(ids_bytes).hexdigest(),
        "source_bin_definitions": hashlib.sha256(catalog_bytes).hexdigest(),
    }
    result["audit_tool_sha256"] = sha256_file(Path(__file__))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{sha256_file(output)}  {output.name}\n", encoding="ascii"
    )
    print(json.dumps({
        "status": result["status"],
        "classification_counts": result["classification_counts"],
        "coverage_credit_granted": 0,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
