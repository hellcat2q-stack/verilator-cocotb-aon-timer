"""Recover definition-only URG layouts and reject unstable positional bridges.

No historical COUNT, test names, scores, HTML, or server paths are exported.
The portable layout export can be replayed without the original report files.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LAYOUT_SCHEMA = "aon-timer-legacy-urg-layouts-v1"
AUDIT_SCHEMA = "aon-timer-legacy-urg-layout-audit-v1"
BIN_SECTIONS = {"Bins", "Covered bins", "Uncovered bins", "Element holes"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_page(path: Path) -> dict[str, Any]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if "Group ::" not in title:
        raise ValueError("URG page does not identify a covergroup")
    group = title.split("Group ::", 1)[1].strip()
    rows = []
    for heading in soup.find_all("span", class_="repname"):
        text = heading.get_text(" ", strip=True)
        if text.startswith("Summary for Variable "):
            kind, item = "variable", text.removeprefix("Summary for Variable ").strip()
        elif text.startswith("Summary for Cross "):
            kind, item = "cross", text.removeprefix("Summary for Cross ").strip()
        else:
            continue
        section = ""
        for node in heading.next_elements:
            if getattr(node, "name", None) == "span" and "repname" in (node.get("class") or []):
                section = node.get_text(" ", strip=True)
                if section.startswith(("Summary for Variable ", "Summary for Cross ")):
                    break
            if getattr(node, "name", None) != "table" or section not in BIN_SECTIONS:
                continue
            table_rows = node.find_all("tr")
            if not table_rows:
                continue
            headers = [cell.get_text(" ", strip=True).upper()
                       for cell in table_rows[0].find_all(["th", "td"])]
            if kind == "variable":
                if headers[:2] != ["NAME", "COUNT"]:
                    continue
                count_index, name_indexes = 1, [0]
            else:
                if "COUNT" not in headers:
                    continue
                count_index = headers.index("COUNT")
                name_indexes = list(range(count_index))
            for table_row in table_rows[1:]:
                cells = [cell.get_text(" ", strip=True) for cell in table_row.find_all(["th", "td"])]
                if len(cells) <= count_index or not any(cells[i] for i in name_indexes):
                    continue
                # Read only definitions/cardinality. The COUNT column is discarded.
                number = 1
                if "NUMBER" in headers and len(cells) > headers.index("NUMBER"):
                    number_text = cells[headers.index("NUMBER")].replace(",", "")
                    if not re.fullmatch(r"\d+", number_text) or int(number_text) < 1:
                        raise ValueError("invalid URG definition cardinality")
                    number = int(number_text)
                else:
                    match = re.search(r"\((\d+)\s+bins?\)", " ".join(cells), re.IGNORECASE)
                    if match:
                        number = int(match.group(1))
                display = "X".join(cells[i] for i in name_indexes)
                label = f"name:{display}"
                if kind == "variable" and "SUBSUMED VALUES" in headers:
                    index = headers.index("SUBSUMED VALUES")
                    value = cells[index] if len(cells) > index else "--"
                    if value not in {"", "--"}:
                        label = f"values:{value}"
                rows.append({"kind": kind, "item": item, "label": label, "number": number})
    if not rows:
        raise ValueError("URG page has no definition rows")
    return {"file": path.name, "sha256": digest(path), "scope": group, "rows": rows}


def expand_layout(report: dict[str, Any]) -> dict[tuple[str, str, str], list[str]]:
    # Match legacy dictionary insertion/dedup semantics, including repeated
    # instance tables, without reading any coverage result.
    identities: dict[str, None] = {}
    for page in report["pages"]:
        for row in page["rows"]:
            number = row["number"]
            if type(number) is not int or number < 1:
                raise ValueError("layout cardinality must be a positive integer")
            for offset in range(number):
                identity = "||".join((page["scope"], row["kind"], row["item"], row["label"], str(offset)))
                identities.setdefault(identity, None)
    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for identity in identities:
        groups[tuple(identity.split("||")[:3])].append(identity)
    return dict(groups)


def semantic_identity(identity: str) -> str | None:
    """Resolve only a singleton value or explicit variable name, never an offset."""
    scope, kind, item, label, offset = identity.split("||")
    if kind != "variable" or offset != "0":
        return None
    if label.startswith("values:"):
        # URG wraps singleton values differently in covered and uncovered rows.
        value = label.removeprefix("values:").strip()
        if value.startswith("[") and value.endswith("]"):
            value = value[1:-1].strip()
        singleton = re.fullmatch(r"\{\s*\[\s*(\d+)\s*\]\s*\}", value)
        if singleton is None:
            return None
        atom = "value:" + str(int(singleton.group(1)))
    elif label.startswith("name:"):
        atom = label
        if not re.fullmatch(r"name:[A-Za-z_]\w*(?:\[(?:\d+|0x[0-9a-fA-F]+)\])?", atom):
            return None
        auto = re.fullmatch(r"name:auto\[(\d+)\]", atom)
        if auto:
            atom = "value:" + str(int(auto.group(1)))
    else:
        return None
    return "||".join((scope, kind, item, atom))


def resolved_semantics(identities: list[str]) -> list[str | None]:
    cardinalities = Counter(identity.rsplit("||", 1)[0] for identity in identities)
    return [semantic_identity(identity) if cardinalities[identity.rsplit("||", 1)[0]] == 1 else None
            for identity in identities]


def align_by_semantics(reference: list[str], observed: list[str]) -> list[dict[str, Any]]:
    """Return only unique, explicit identity pairs; ambiguous bins are omitted."""
    left: dict[str, list[tuple[int, str]]] = defaultdict(list)
    right: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for rows, index in ((reference, left), (observed, right)):
        for position, (identity, semantic) in enumerate(zip(rows, resolved_semantics(rows))):
            if semantic is not None:
                index[semantic].append((position, identity))
    result = []
    for semantic in sorted(left.keys() & right.keys()):
        if len(left[semantic]) != 1 or len(right[semantic]) != 1:
            continue
        old_position, old_identity = left[semantic][0]
        new_position, new_identity = right[semantic][0]
        result.append({
            "semantic_identity": semantic,
            "reference_identity": old_identity,
            "report_identity": new_identity,
            "reference_position": old_position,
            "report_position": new_position,
        })
    return result


def audit_layouts(document: dict[str, Any], canonical_ids: list[str]) -> dict[str, Any]:
    if document.get("schema") != LAYOUT_SCHEMA:
        raise ValueError("unsupported URG layout schema")
    reports = document.get("reports", [])
    if len(reports) < 2 or len({r["report_id"] for r in reports}) != len(reports):
        raise ValueError("at least two distinct URG reports are required")
    reference = expand_layout(reports[0])
    reference_ids = [identity for rows in reference.values() for identity in rows]
    if sorted(reference_ids) != canonical_ids or len(set(canonical_ids)) != len(canonical_ids):
        raise ValueError("first URG report does not reproduce the frozen identity header")
    comparisons = []
    confirmed_conflicts = 0
    for report in reports[1:]:
        observed = expand_layout(report)
        if set(observed) != set(reference):
            raise ValueError("URG report coverpoint/cross set differs from the reference")
        groups = []
        total_aligned = 0
        shifted_alignments = 0
        for prefix, old in reference.items():
            new = observed[prefix]
            if len(new) != len(old):
                raise ValueError("URG report bin cardinality differs from the reference")
            explicit_pairs = align_by_semantics(old, new)
            total_aligned += len(explicit_pairs)
            shifted = [pair for pair in explicit_pairs if pair["reference_position"] != pair["report_position"]]
            shifted_alignments += len(shifted)
            old_semantics, new_semantics = resolved_semantics(old), resolved_semantics(new)
            conflicts = [
                {"position": i, "reference_identity": left, "report_identity_at_same_position": right,
                 "reference_semantic_identity": left_semantic,
                 "report_semantic_identity": right_semantic}
                for i, (left, right, left_semantic, right_semantic) in enumerate(zip(old, new, old_semantics, new_semantics))
                if left_semantic is not None and right_semantic is not None and left_semantic != right_semantic
            ]
            confirmed_conflicts += len(conflicts)
            if old != new:
                groups.append({
                    "scope": prefix[0], "kind": prefix[1], "item": prefix[2],
                    "identity_count": len(old),
                    "changed_label_positions": sum(left != right for left, right in zip(old, new)),
                    "confirmed_semantic_position_conflicts": len(conflicts),
                    "conflict_examples": conflicts[:4],
                    "explicit_semantic_pairs": len(explicit_pairs),
                    "shifted_explicit_semantic_pairs": len(shifted),
                    "shift_examples": shifted[:4],
                })
        comparisons.append({
            "report_id": report["report_id"],
            "expanded_identity_count": sum(len(rows) for rows in observed.values()),
            "changed_prefix_count": len(groups),
            "explicit_semantic_alignment_count": total_aligned,
            "explicit_semantic_alignment_shift_count": shifted_alignments,
            "changed_prefixes": groups,
        })
    return {
        "schema": AUDIT_SCHEMA,
        "status": "UNSAFE_LEGACY_POSITIONAL_BRIDGE" if confirmed_conflicts else "POSITIONAL_BRIDGE_NOT_PROVEN",
        "reference_report_id": reports[0]["report_id"],
        "reference_header_reproduced": True,
        "canonical_identity_count": len(canonical_ids),
        "report_count": len(reports),
        "confirmed_semantic_position_conflicts": confirmed_conflicts,
        "positional_mapping_promotion_allowed": False,
        "comparisons": comparisons,
        "coverage_credit_granted": 0,
        "full_coverage_rate_percent": None,
        "limitations": [
            "Compressed NUMBER rows do not expose an individual bin order.",
            "Only unique explicit names and singleton values are semantically aligned.",
            "No historical run counts are imported or attributed to Cocotb.",
            "This identity audit provides no UVM/Cocotb sample-timing equivalence evidence.",
        ],
    }


def write_artifact(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    path.with_suffix(path.suffix + ".sha256").write_text(f"{digest(path)}  {path.name}\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--reports-root", type=Path)
    source.add_argument("--layouts", type=Path)
    parser.add_argument("--reference-report", default="original_g0")
    parser.add_argument("--bin-ids", type=Path, default=ROOT / "references/canonical_bin_ids.txt")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.reports_root:
        directories = sorted(p for p in args.reports_root.iterdir() if p.is_dir() and list(p.glob("grp*.html")))
        directories.sort(key=lambda p: (p.name != args.reference_report, p.name))
        if not directories or directories[0].name != args.reference_report:
            raise ValueError("reference URG report not found")
        document = {"schema": LAYOUT_SCHEMA, "report_results_exported": False, "reports": []}
        for directory in directories:
            pages = sorted(directory.glob("grp*.html"), key=lambda p: int(re.fullmatch(r"grp(\d+)\.html", p.name)[1]))
            document["reports"].append({"report_id": directory.name, "pages": [extract_page(page) for page in pages]})
    else:
        document = json.loads(args.layouts.read_text(encoding="utf-8"))
    canonical_ids = args.bin_ids.read_text(encoding="utf-8").splitlines()
    result = audit_layouts(document, canonical_ids)
    layouts_path = args.output_dir / "layouts.json"
    write_artifact(layouts_path, document)
    result["input_sha256"] = {"layouts.json": digest(layouts_path), "canonical_bin_ids": digest(args.bin_ids)}
    result["audit_tool_sha256"] = digest(Path(__file__))
    write_artifact(args.output_dir / "audit.json", result)
    print(json.dumps({key: result[key] for key in (
        "status", "report_count", "reference_header_reproduced", "confirmed_semantic_position_conflicts",
        "positional_mapping_promotion_allowed", "coverage_credit_granted")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
