"""Classify raw source samples against the pinned source-definition catalog.

The classifier deliberately operates at the source-definition layer.  It does
not assign legacy CSV/URG identities, infer misses, or claim VCS/URG
equivalence.  A result may therefore contain exact named-bin matches, value
range matches for count-event auto bins, and explicitly unresolved array or
interrupt-cross observations.
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
CATALOG_PATH = ROOT / "references" / "bin_definitions.v1.json"
SCHEMA_PATH = ROOT / "configs" / "coverage_schema.json"
CLASSIFIER_SCHEMA = "aon-timer-source-definition-classification-v1"
SOURCE_REVISION = "9f20940d494a223cc950a5b98f748fb28109d458"
TRACE_SCHEMA_ID = "aon_timer_uvm_source_trace_v2"

SOURCE_SCOPES = {
    "timer_cfg_cg": "aon_timer_env_pkg::aon_timer_env_cov::timer_cfg_cg",
    "wake_up_timer_thold_hit_cg": (
        "aon_timer_env_pkg::aon_timer_env_cov::wake_up_timer_thold_hit_cg"
    ),
    "watchdog_timer_bark_thold_hit_cg": (
        "aon_timer_env_pkg::aon_timer_env_cov::watchdog_timer_bark_thold_hit_cg"
    ),
    "watchdog_timer_bite_thold_hit_cg": (
        "aon_timer_env_pkg::aon_timer_env_cov::watchdog_timer_bite_thold_hit_cg"
    ),
    "intr_cg": "cip_base_pkg::intr_cg::SHAPE{(num_interrupts - 1)=1}",
    "intr_test_cg": "cip_base_pkg::intr_test_cg::SHAPE{(num_interrupts - 1)=1}",
    "intr_pins_cg": "cip_base_pkg::intr_pins_cg::SHAPE{(num_interrupts - 1)=1}",
}

ARRAY_FIELDS = {
    "timer_cfg_cg": {
        "prescale": "prescale_cp",
        "bark_thold": "bark_thold_cp",
        "bite_thold": "bite_thold_cp",
        "wkup_thold": "wkup_thold_cp",
    }
}

COUNT_GROUPS = {
    "wake_up_timer_thold_hit_cg": {
        "value_fields": {"wkup_count_cp": "wkup_count", "wkup_thold_cp": "wkup_thold"},
        "crosses": {"wkup_thold_cpXwkup_int_cp"},
    },
    "watchdog_timer_bark_thold_hit_cg": {
        "value_fields": {"wdog_count_cp": "wdog_count", "wdog_thold_cp": "wdog_thold"},
        "crosses": {"wdog_thold_cpXwdog_bark_rst"},
    },
    "watchdog_timer_bite_thold_hit_cg": {
        "value_fields": {"wdog_count_cp": "wdog_count", "wdog_thold_cp": "wdog_thold"},
        "crosses": {"wdog_thold_cpXwdog_bite_rst"},
    },
}

INTERRUPT_FIELDS = {
    "intr_cg": {"cp_intr": "intr", "cp_intr_en": "intr_en", "cp_intr_state": "intr_state"},
    "intr_test_cg": {
        "cp_intr": "intr", "cp_intr_test": "intr_test", "cp_intr_en": "intr_en",
        "cp_intr_state": "intr_state",
    },
    "intr_pins_cg": {"cp_intr_pin": "intr_pin", "cp_intr_pin_value": "intr_pin_value"},
}

INTERRUPT_CROSSES = {
    "intr_cg": "cross_cp_intr_cp_intr_en_cp_intr_state",
    "intr_test_cg": "cross_cp_intr_cp_intr_test_cp_intr_en_cp_intr_state",
    "intr_pins_cg": "cp_intr_pins_all_values",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_catalog(path: Path = CATALOG_PATH) -> tuple[dict[str, Any], str]:
    """Load and validate the immutable source-definition catalog."""
    path = Path(path)
    raw = path.read_bytes()
    catalog = json.loads(raw.decode("utf-8"))
    if catalog.get("schema") != "aon-timer-bin-definitions-v1":
        raise ValueError("unsupported source-definition catalog schema")
    if catalog.get("source_revision") != SOURCE_REVISION:
        raise ValueError("source-definition catalog does not match the pinned revision")
    definitions = catalog.get("definitions")
    if not isinstance(definitions, list) or catalog.get("definition_count") != len(definitions):
        raise ValueError("source-definition catalog count is invalid")
    ids = [entry.get("definition_id") for entry in definitions]
    if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("source-definition catalog contains duplicate or invalid IDs")
    catalog_hash = hashlib.sha256(raw).hexdigest()
    sidecar = path.with_suffix(path.suffix + ".sha256")
    if not sidecar.is_file():
        raise ValueError("source-definition catalog SHA-256 sidecar is missing")
    declared_hash = sidecar.read_text(encoding="ascii").split()[0]
    if declared_hash != catalog_hash:
        raise ValueError("source-definition catalog SHA-256 sidecar mismatch")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    expected_hash = schema.get("bin_definition_reference", {}).get("catalog_sha256")
    if expected_hash != catalog_hash:
        raise ValueError("coverage schema does not reference this source-definition catalog hash")
    return catalog, catalog_hash


def _parse_membership(value: str) -> tuple[str, str, str] | None:
    """Parse CoverageTrace's ``group.coverpoint.bin`` membership label."""
    if not isinstance(value, str):
        return None
    group, separator, rest = value.partition(".")
    if not separator:
        return None
    item, separator, bin_name = rest.partition(".")
    if not separator or not group or not item or not bin_name:
        return None
    return group, item, bin_name


def _label_value(label: str) -> int | None:
    """Decode the simple one-bit labels used by count-event cross members."""
    if label in {"set", "auto[1]"}:
        return 1
    if label in {"unset", "auto[0]"}:
        return 0
    match = re.fullmatch(r"auto\[(\d+)\]", label)
    return int(match.group(1)) if match else None


def _definition_id(entry: dict[str, Any]) -> str:
    value = entry.get("definition_id")
    if not isinstance(value, str) or not value:
        raise ValueError("catalog definition has no definition_id")
    return value


class SourceDefinitionClassifier:
    """Map one raw source sample to source definition IDs where justified."""

    def __init__(self, catalog: dict[str, Any]):
        self.catalog = catalog
        self._by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        self._by_scope_item: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for definition in catalog["definitions"]:
            key = (
                definition["scope"], definition["kind"],
                definition["item"], definition["bin_name"],
            )
            if key in self._by_key:
                raise ValueError(f"duplicate source definition key: {key}")
            self._by_key[key] = definition
            self._by_scope_item.setdefault(key[:3], []).append(definition)

    def _lookup_named(self, scope: str, item: str, bin_name: str) -> dict[str, Any] | None:
        return self._by_key.get((scope, "variable", item, bin_name))

    def _lookup_range(self, scope: str, item: str, value: int) -> list[dict[str, Any]]:
        result = []
        for definition in self._by_scope_item.get((scope, "variable", item), []):
            value_range = definition.get("value_range")
            if isinstance(value_range, list) and len(value_range) == 2:
                if value_range[0] <= value <= value_range[1]:
                    result.append(definition)
        return result

    @staticmethod
    def _match_cross_member(member: dict[str, Any], value: int) -> bool:
        value_range = member.get("value_range")
        if isinstance(value_range, list) and len(value_range) == 2:
            return value_range[0] <= value <= value_range[1]
        decoded = _label_value(str(member.get("bin_label", "")))
        return decoded is not None and decoded == value

    def _classify_count_cross(
        self, scope: str, item: str, observation: dict[str, int]
    ) -> tuple[list[dict[str, Any]], str | None]:
        candidates = []
        for definition in self._by_scope_item.get((scope, "cross", item), []):
            cross = definition.get("cross_definition")
            if not isinstance(cross, dict) or not isinstance(cross.get("members"), list):
                continue
            members = cross["members"]
            if len(members) != 2:
                continue
            values: list[int] = []
            valid = True
            for member in members:
                coverpoint = str(member.get("coverpoint", ""))
                field = coverpoint.removesuffix("_cp")
                if field not in observation:
                    valid = False
                    break
                values.append(observation[field])
            if valid and all(self._match_cross_member(member, value)
                             for member, value in zip(members, values)):
                candidates.append(definition)
        if len(candidates) == 1:
            return [candidates[0]], None
        if not candidates:
            return [], "NO_UNIQUE_VALUE_RANGE_CROSS_MATCH"
        return [], "AMBIGUOUS_VALUE_RANGE_CROSS_MATCH"

    def _exact_memberships(
        self, sample: dict[str, Any], source_scope: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        matches: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        memberships = sample.get("resolved_explicit_bin_memberships", [])
        if not isinstance(memberships, list):
            return matches, [{"kind": "variable", "reason": "MALFORMED_EXPLICIT_MEMBERSHIPS"}]
        for membership in memberships:
            parsed = _parse_membership(membership)
            if parsed is None:
                unresolved.append({"kind": "variable", "membership": membership,
                                   "reason": "MALFORMED_EXPLICIT_MEMBERSHIP"})
                continue
            group, item, bin_name = parsed
            if group != sample.get("covergroup"):
                unresolved.append({"kind": "variable", "membership": membership,
                                   "reason": "SAMPLE_GROUP_MEMBERSHIP_MISMATCH"})
                continue
            definition = self._lookup_named(source_scope, item, bin_name)
            if definition is None:
                unresolved.append({"kind": "variable", "membership": membership,
                                   "reason": "SOURCE_DEFINITION_NOT_FOUND"})
                continue
            matches.append({"definition_id": _definition_id(definition),
                            "match_kind": "SOURCE_DEFINITION_EXACT_MATCH",
                            "item": item, "bin_name": bin_name})
        return matches, unresolved

    def _classify_singletons(
        self, sample: dict[str, Any], source_scope: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        group = str(sample.get("covergroup"))
        fields = sample.get("fields")
        if not isinstance(fields, dict):
            return [], [{"kind": "sample", "reason": "MISSING_FIELDS"}]
        matches: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        if group in COUNT_GROUPS:
            field_items = COUNT_GROUPS[group]["value_fields"]
            for item, field in field_items.items():
                value = fields.get(field)
                if not isinstance(value, int):
                    unresolved.append({"kind": "variable", "item": item,
                                       "reason": "MISSING_VALUE_FIELD", "field": field})
                    continue
                candidates = self._lookup_range(source_scope, item, value)
                if len(candidates) == 1:
                    definition = candidates[0]
                    matches.append({"definition_id": _definition_id(definition),
                                    "match_kind": "SOURCE_DEFINITION_VALUE_RANGE_MATCH",
                                    "item": item, "bin_name": definition["bin_name"],
                                    "value": value})
                elif len(candidates) == 0:
                    unresolved.append({"kind": "variable", "item": item,
                                       "value": value, "reason": "NO_VALUE_RANGE_MATCH"})
                else:
                    unresolved.append({"kind": "variable", "item": item,
                                       "value": value, "reason": "AMBIGUOUS_VALUE_RANGE_MATCH"})
        elif group == "timer_cfg_cg":
            for item, field in (("wdog_regwen_cp", "wdog_regwen"),
                                ("pause_in_sleep_cp", "pause_in_sleep")):
                value = fields.get(field)
                if not isinstance(value, int):
                    unresolved.append({"kind": "variable", "item": item,
                                       "reason": "MISSING_VALUE_FIELD", "field": field})
                    continue
                candidates = self._lookup_range(source_scope, item, value)
                if len(candidates) == 1:
                    definition = candidates[0]
                    matches.append({"definition_id": _definition_id(definition),
                                    "match_kind": "SOURCE_DEFINITION_EXACT_MATCH",
                                    "item": item, "bin_name": definition["bin_name"],
                                    "value": value})
                elif len(candidates) == 0:
                    unresolved.append({"kind": "variable", "item": item,
                                       "value": value, "reason": "NO_SINGLETON_DEFINITION_MATCH"})
                else:
                    unresolved.append({"kind": "variable", "item": item,
                                       "value": value, "reason": "AMBIGUOUS_SINGLETON_DEFINITION_MATCH"})
        elif group in {"intr_cg", "intr_test_cg", "intr_pins_cg"}:
            for item, field in INTERRUPT_FIELDS[group].items():
                value = fields.get(field)
                if not isinstance(value, int):
                    unresolved.append({"kind": "variable", "item": item,
                                       "reason": "MISSING_VALUE_FIELD", "field": field})
                    continue
                bin_name: str | None = None
                if item == "cp_intr":
                    bin_name = f"all_values[{value}]"
                elif item == "cp_intr_pin":
                    bin_name = f"all_pins[{value}]"
                elif item == "cp_intr_pin_value":
                    bin_name = f"values[0x{value:x}]"
                    transition = sample.get("observed_transition")
                    if (isinstance(transition, list) and len(transition) == 2
                            and transition[0] in (0, 1) and transition[1] in (0, 1)
                            and transition[0] != transition[1]):
                        bin_name = f"transitions[0x{transition[0]:x}=>0x{transition[1]:x}]"
                if bin_name is None:
                    candidates = self._lookup_range(source_scope, item, value)
                    if len(candidates) == 1:
                        definition = candidates[0]
                        matches.append({"definition_id": _definition_id(definition),
                                        "match_kind": "SOURCE_DEFINITION_EXACT_MATCH",
                                        "item": item, "bin_name": definition["bin_name"],
                                        "value": value})
                    else:
                        unresolved.append({"kind": "variable", "item": item,
                                           "value": value,
                                           "reason": "NO_UNIQUE_SINGLETON_MATCH"})
                    continue
                definition = self._lookup_named(source_scope, item, bin_name)
                if definition is None:
                    unresolved.append({"kind": "variable", "item": item,
                                       "bin_name": bin_name,
                                       "reason": "SOURCE_DEFINITION_NOT_FOUND"})
                else:
                    matches.append({"definition_id": _definition_id(definition),
                                    "match_kind": "SOURCE_DEFINITION_EXACT_MATCH",
                                    "item": item, "bin_name": bin_name,
                                    "value": value})
        return matches, unresolved

    def classify_sample(self, sample: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(sample, dict) or not isinstance(sample.get("covergroup"), str):
            raise ValueError("sample must contain a covergroup name")
        group = sample["covergroup"]
        source_scope = SOURCE_SCOPES.get(group)
        sample_fields = sample.get("fields")
        if not isinstance(sample_fields, dict):
            sample_fields = {}
        result: dict[str, Any] = {
            "sample_index": sample.get("sample_index"),
            "covergroup": group,
            "source_scope": source_scope,
            "variable_matches": [],
            "cross_matches": [],
            "array_partition_unresolved": [],
            "unresolved": [],
        }
        if source_scope is None:
            result["unresolved"].append({"kind": "sample", "reason": "SOURCE_SCOPE_UNMAPPED"})
            result["status"] = "SOURCE_SCOPE_UNMAPPED"
            return result

        variable_matches, unresolved = self._exact_memberships(sample, source_scope)
        more_matches, more_unresolved = self._classify_singletons(sample, source_scope)
        result["variable_matches"].extend(variable_matches)
        result["variable_matches"].extend(more_matches)
        result["unresolved"].extend(unresolved)
        result["unresolved"].extend(more_unresolved)

        for field, item in ARRAY_FIELDS.get(group, {}).items():
            value = sample_fields.get(field)
            if not isinstance(value, int):
                continue
            definitions = [
                definition for definition in self._by_scope_item.get((source_scope, "variable", item), [])
                if isinstance(definition.get("array_bin"), dict)
                and definition["array_bin"].get("declared_value_range", [1, 0])[0]
                <= value <= definition["array_bin"].get("declared_value_range", [1, 0])[1]
            ]
            if definitions:
                result["array_partition_unresolved"].append({
                    "item": item, "field": field, "value": value,
                    "reason": "ARRAY_PARTITION_UNRESOLVED",
                    "candidate_definition_count": len(definitions),
                })

        observations = sample.get("same_sample_cross_observations", {})
        if not isinstance(observations, dict):
            result["unresolved"].append({"kind": "cross", "reason": "MALFORMED_CROSS_OBSERVATIONS"})
            observations = {}
        else:
            for item, observation in observations.items():
                if group in COUNT_GROUPS and item in COUNT_GROUPS[group]["crosses"]:
                    if not isinstance(observation, dict) or any(not isinstance(v, int) for v in observation.values()):
                        result["unresolved"].append({"kind": "cross", "item": item,
                                                       "reason": "MALFORMED_CROSS_OBSERVATION"})
                        continue
                    matches, reason = self._classify_count_cross(source_scope, item, observation)
                    if matches:
                        definition = matches[0]
                        result["cross_matches"].append({
                            "definition_id": _definition_id(definition),
                            "match_kind": "SOURCE_DEFINITION_CROSS_MEMBER_MATCH",
                            "item": item, "bin_name": definition["bin_name"],
                            "observation": dict(observation),
                        })
                    else:
                        result["unresolved"].append({"kind": "cross", "item": item,
                                                       "reason": reason or "CROSS_UNRESOLVED"})
                elif group in {"intr_cg", "intr_test_cg", "intr_pins_cg"}:
                    result["unresolved"].append({
                        "kind": "cross", "item": item,
                        "reason": "INTERRUPT_CROSS_SCHEMA_UNRESOLVED",
                    })
                else:
                    result["unresolved"].append({"kind": "cross", "item": item,
                                                   "reason": "SOURCE_CROSS_NOT_MAPPED"})

        expected_crosses = COUNT_GROUPS.get(group, {}).get("crosses", set())
        if group in INTERRUPT_CROSSES:
            expected_crosses = {INTERRUPT_CROSSES[group]}
        for item in expected_crosses:
            if item not in observations:
                result["unresolved"].append({
                    "kind": "cross", "item": item,
                    "reason": "MISSING_SAME_SAMPLE_CROSS_OBSERVATION",
                })

        if result["array_partition_unresolved"]:
            result["status"] = "SOURCE_DEFINITION_PARTIAL_ARRAY_UNRESOLVED"
        elif result["unresolved"]:
            result["status"] = "SOURCE_DEFINITION_PARTIAL"
        else:
            result["status"] = "SOURCE_DEFINITION_EXACT_MATCH"
        return result

    def classify_trace(self, trace: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(trace, dict):
            raise ValueError("trace must be a JSON object")
        if trace.get("schema_id") != TRACE_SCHEMA_ID:
            raise ValueError("unsupported source-trace schema")
        if trace.get("source_revision") != SOURCE_REVISION:
            raise ValueError("trace source revision does not match the pinned revision")
        samples = trace.get("samples")
        if not isinstance(samples, list):
            raise ValueError("trace has no samples list")
        classifications = [self.classify_sample(sample) for sample in samples]
        variable_ids = sorted({item["definition_id"] for row in classifications
                               for item in row["variable_matches"]})
        cross_ids = sorted({item["definition_id"] for row in classifications
                            for item in row["cross_matches"]})
        exact_ids = sorted({item["definition_id"] for row in classifications
                            for item in row["variable_matches"] + row["cross_matches"]
                            if item["match_kind"] == "SOURCE_DEFINITION_EXACT_MATCH"})
        range_ids = sorted({item["definition_id"] for row in classifications
                            for item in row["variable_matches"]
                            if item["match_kind"] == "SOURCE_DEFINITION_VALUE_RANGE_MATCH"})
        return {
            "schema": CLASSIFIER_SCHEMA,
            "status": "SOURCE_DEFINITION_MAPPING_PARTIAL",
            "source_revision": SOURCE_REVISION,
            "run_id": trace.get("run_id"),
            "testcase": trace.get("testcase"),
            "seed": trace.get("seed"),
            "definition_catalog_sha256": self.catalog.get("catalog_sha256") or "",
            "sample_count": len(samples),
            "samples": classifications,
            "summary": {
                "source_definition_count": self.catalog["definition_count"],
                "unique_variable_definition_match_count": len(variable_ids),
                "unique_cross_definition_match_count": len(cross_ids),
                "unique_definition_match_count": len(set(variable_ids) | set(cross_ids)),
                "exact_named_or_singleton_match_count": len(exact_ids),
                "value_range_match_count": len(range_ids),
                "array_partition_unresolved_sample_count": sum(
                    bool(row["array_partition_unresolved"]) for row in classifications
                ),
                "interrupt_cross_unresolved_sample_count": sum(
                    any(item.get("reason") == "INTERRUPT_CROSS_SCHEMA_UNRESOLVED"
                        for item in row["unresolved"])
                    for row in classifications
                ),
                "legacy_identity_credit_granted": 0,
                "full_coverage_rate_percent": None,
            },
            "definition_ids_observed": sorted(set(variable_ids) | set(cross_ids)),
            "unknown_policy": "unmatched source definitions remain unknown; no misses are inferred",
            "equivalence_policy": "source-definition mapping is not VCS/URG/Cocotb coverage equivalence",
        }


def classify_trace(trace: dict[str, Any], catalog_path: Path = CATALOG_PATH) -> dict[str, Any]:
    catalog, catalog_hash = load_catalog(catalog_path)
    classifier = SourceDefinitionClassifier(catalog)
    result = classifier.classify_trace(trace)
    result["definition_catalog_sha256"] = catalog_hash
    result["catalog_status"] = catalog.get("status")
    return result


def classify_passing_trace_tree(
    trace_root: Path,
    catalog_path: Path = CATALOG_PATH,
    *,
    expected_trace_count: int | None = None,
) -> dict[str, Any]:
    """Classify traces whose adjacent attempt records prove a passing run."""
    trace_root = Path(trace_root).resolve()
    catalog, catalog_hash = load_catalog(catalog_path)
    classifier = SourceDefinitionClassifier(catalog)
    trace_paths = sorted(
        path for directory in trace_root.rglob("coverage-traces")
        for path in directory.glob("*.json")
    )
    if expected_trace_count is not None and len(trace_paths) != expected_trace_count:
        raise ValueError(
            f"expected {expected_trace_count} trace files, found {len(trace_paths)}"
        )

    traces = []
    definition_occurrences: Counter[tuple[str, str, str]] = Counter()
    match_kind_occurrences: Counter[str] = Counter()
    unresolved_reasons: Counter[str] = Counter()
    total_samples = 0
    array_unresolved_samples = 0
    array_unresolved_observations = 0
    for trace_path in trace_paths:
        attempt_path = trace_path.parent.parent / "attempt.json"
        if not attempt_path.is_file():
            raise ValueError(f"trace has no adjacent attempt record: {trace_path.name}")
        attempt_bytes = attempt_path.read_bytes()
        attempt = json.loads(attempt_bytes.decode("utf-8"))
        if not isinstance(attempt, dict):
            raise ValueError(f"attempt record is not a JSON object: {attempt_path.name}")
        trace_bytes = trace_path.read_bytes()
        trace_hash = hashlib.sha256(trace_bytes).hexdigest()
        if attempt.get("result") != "PASS":
            raise ValueError(f"trace is attached to a non-passing attempt: {trace_path.name}")
        if attempt.get("exit_code") != 0 or attempt.get("timed_out") is not False:
            raise ValueError(f"PASS attempt has inconsistent process status: {trace_path.name}")
        if attempt.get("trace_sha256") != trace_hash:
            raise ValueError(f"attempt record trace hash mismatch: {trace_path.name}")
        trace = json.loads(trace_bytes.decode("utf-8"))
        if not isinstance(trace, dict):
            raise ValueError(f"trace is not a JSON object: {trace_path.name}")
        if trace.get("schema_id") != TRACE_SCHEMA_ID:
            raise ValueError(f"unsupported source-trace schema: {trace_path.name}")
        if trace.get("run_id") != attempt.get("run_id"):
            raise ValueError(f"trace run ID disagrees with its attempt: {trace_path.name}")
        if trace.get("testcase") != attempt.get("testcase"):
            raise ValueError(f"trace testcase disagrees with its attempt: {trace_path.name}")
        samples = trace.get("samples")
        if (not isinstance(samples, list) or len(samples) != attempt.get("sample_count")
                or len(samples) != trace.get("sample_count")):
            raise ValueError(f"trace sample count disagrees with its attempt: {trace_path.name}")
        testcase_records = attempt.get("testcases")
        if (not isinstance(testcase_records, list) or not testcase_records
                or any(record.get("result") != "PASS" for record in testcase_records)
                or {record.get("name") for record in testcase_records} != {trace.get("testcase")}):
            raise ValueError(f"attempt testcase results disagree with its trace: {trace_path.name}")

        result = classifier.classify_trace(trace)
        canonical_result = json.dumps(
            result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        per_file_matches: Counter[tuple[str, str]] = Counter()
        per_file_reasons: Counter[str] = Counter()
        for row in result["samples"]:
            for item in row["variable_matches"]:
                key = (item["definition_id"], item["match_kind"], row["covergroup"])
                definition_occurrences[key] += 1
                match_kind_occurrences[item["match_kind"]] += 1
                per_file_matches[(item["definition_id"], item["match_kind"])] += 1
            for item in row["cross_matches"]:
                key = (item["definition_id"], item["match_kind"], row["covergroup"])
                definition_occurrences[key] += 1
                match_kind_occurrences[item["match_kind"]] += 1
                per_file_matches[(item["definition_id"], item["match_kind"])] += 1
            for item in row["unresolved"]:
                reason = item.get("reason", "UNSPECIFIED")
                unresolved_reasons[reason] += 1
                per_file_reasons[reason] += 1
            if row["array_partition_unresolved"]:
                array_unresolved_samples += 1
                array_unresolved_observations += len(row["array_partition_unresolved"])

        traces.append({
            "path": trace_path.relative_to(trace_root).as_posix(),
            "run_id": trace.get("run_id"),
            "testcase": trace.get("testcase"),
            "seed": trace.get("seed"),
            "attempt_record_sha256": hashlib.sha256(attempt_bytes).hexdigest(),
            "trace_sha256": trace_hash,
            "classification_sha256": hashlib.sha256(canonical_result).hexdigest(),
            "sample_count": len(samples),
            "unique_definition_match_count": result["summary"]["unique_definition_match_count"],
            "variable_definition_match_occurrences": sum(
                count for (definition_id, match_kind), count in per_file_matches.items()
                if match_kind != "SOURCE_DEFINITION_CROSS_MEMBER_MATCH"
            ),
            "cross_definition_match_occurrences": sum(
                count for (definition_id, match_kind), count in per_file_matches.items()
                if match_kind == "SOURCE_DEFINITION_CROSS_MEMBER_MATCH"
            ),
            "array_partition_unresolved_sample_count": result["summary"][
                "array_partition_unresolved_sample_count"
            ],
            "unresolved_reason_counts": dict(sorted(per_file_reasons.items())),
        })
        total_samples += len(samples)

    if not traces:
        raise ValueError("trace tree contains no passing trace files")
    variable_ids = {
        definition_id for definition_id, match_kind, _ in definition_occurrences
        if "||cross||" not in definition_id
    }
    cross_ids = {
        definition_id for definition_id, match_kind, _ in definition_occurrences
        if "||cross||" in definition_id
    }
    return {
        "schema": "aon-timer-source-definition-classification-corpus-v1",
        "status": "SOURCE_DEFINITION_MAPPING_PARTIAL",
        "source_revision": SOURCE_REVISION,
        "definition_catalog_sha256": catalog_hash,
        "definition_catalog_count": catalog["definition_count"],
        "classifier_sha256": sha256_file(Path(__file__)),
        "trace_count": len(traces),
        "sample_count": total_samples,
        "summary": {
            "unique_definition_match_count": len(variable_ids | cross_ids),
            "unique_variable_definition_match_count": len(variable_ids),
            "unique_cross_definition_match_count": len(cross_ids),
            "match_occurrence_counts": dict(sorted(match_kind_occurrences.items())),
            "array_partition_unresolved_sample_count": array_unresolved_samples,
            "array_partition_unresolved_observation_count": array_unresolved_observations,
            "interrupt_cross_unresolved_sample_count": unresolved_reasons.get(
                "INTERRUPT_CROSS_SCHEMA_UNRESOLVED", 0
            ),
            "unresolved_observation_count": sum(unresolved_reasons.values()),
            "legacy_identity_credit_granted": 0,
            "full_coverage_rate_percent": None,
        },
        "traces": traces,
        "observed_definition_occurrences": [
            {"definition_id": definition_id, "match_kind": match_kind,
             "covergroup": covergroup, "sample_occurrences": count}
            for (definition_id, match_kind, covergroup), count
            in sorted(definition_occurrences.items())
        ],
        "unresolved_reason_counts": dict(sorted(unresolved_reasons.items())),
        "coverage_accounting": {
            "source_definition_matches_are_coverage_credit": False,
            "legacy_identity_credit_granted": 0,
            "unknowns_are_misses": False,
            "full_coverage_rate_percent": None,
            "reason": (
                "Source definition mapping is separate from legacy VCS identity mapping and does "
                "not prove VCS/URG/Cocotb coverage equivalence."
            ),
        },
    }


def write_artifact(path: Path, document: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    path.with_suffix(path.suffix + ".sha256").write_text(
        f"{sha256_file(path)}  {path.name}\n", encoding="ascii"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--trace", type=Path)
    source.add_argument("--trace-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--expected-trace-count", type=int)
    args = parser.parse_args()
    try:
        if args.trace is not None:
            trace = json.loads(args.trace.read_text(encoding="utf-8"))
            result = classify_trace(trace, args.catalog)
        else:
            result = classify_passing_trace_tree(
                args.trace_root, args.catalog,
                expected_trace_count=args.expected_trace_count,
            )
        write_artifact(args.output, result)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, KeyError) as exc:
        parser.error(str(exc))
    summary = {"schema": result["schema"], "sample_count": result["sample_count"],
               "trace_count": result.get("trace_count", 1)}
    if "summary" in result:
        summary["unique_definition_match_count"] = result["summary"][
            "unique_definition_match_count"
        ]
    summary["full_coverage_rate_percent"] = None
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
