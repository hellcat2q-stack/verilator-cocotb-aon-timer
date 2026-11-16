#!/usr/bin/env python3
"""Audit AON Timer sample-site structure without assigning coverage credit.

The audit checks the raw trace contract against ``coverage_schema.json``:
covergroup fields, same-sample cross observations, event names, trace-level
sample counts, and the count-event RTL/cadence metadata.  It also records the
shared/non-AON definition scope that is intentionally outside the AON trace
adapter.  This is an evidence-structure audit; it does not claim UVM/VCS
sampling parity and never turns unknown identities into misses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

try:
    from tools.coverage_model import SUPPORTED_COVERAGE_SCHEMA_IDS
except ModuleNotFoundError:
    from coverage_model import SUPPORTED_COVERAGE_SCHEMA_IDS


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "configs" / "coverage_schema.json"
DEFAULT_DEFINITIONS = ROOT / "references" / "bin_definitions.v1.json"
DEFAULT_TRACE_ROOT = ROOT / "evidence"
DEFAULT_OUTPUT = (
    ROOT / "evidence" / "stage10_sample_site_audit" / "2026-11-16-v2"
    / "sample-site-audit.json"
)

COUNT_EVENT_GROUPS = {
    "wake_up_timer_thold_hit_cg": {
        "count_event": "aon_countdown_wakeup_count",
        "expiry_event": "aon_countdown_wakeup_expiry",
        "count_field": "wkup_count",
    },
    "watchdog_timer_bark_thold_hit_cg": {
        "count_event": "aon_countdown_bark_count",
        "expiry_event": "aon_countdown_bark_expiry",
        "count_field": "wdog_count",
    },
    "watchdog_timer_bite_thold_hit_cg": {
        "count_event": "aon_countdown_bite_count",
        "expiry_event": "aon_countdown_bite_expiry",
        "count_field": "wdog_count",
    },
}

EXPECTED_EVENTS = {
    "timer_cfg_cg": {"tl_addr_phase"},
    "intr_test_cg": {"tl_addr_phase_intr_test", "tl_data_phase_intr_test"},
    "intr_cg": {"tl_data_phase_intr_state_read"},
    "intr_pins_cg": {"aon_intr_pins_change"},
    **{
        group: {values["count_event"], values["expiry_event"]}
        for group, values in COUNT_EVENT_GROUPS.items()
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _relative(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return Path(path).name


def _trace_files(trace_root: Path) -> list[Path]:
    root = Path(trace_root)
    if root.is_file():
        candidates = [root]
    else:
        candidates = sorted(root.rglob("*.json"))
    return [
        path for path in candidates
        if path.is_file() and "coverage-traces" in path.parts
    ]


def _field_names(group: dict[str, Any]) -> set[str]:
    return set((group.get("fields") or {}).keys())


def _cross_field_names(group: dict[str, Any], cross: dict[str, Any]) -> set[str]:
    coverpoints = {
        str(point.get("name")): str(point.get("field"))
        for point in group.get("coverpoints", [])
        if point.get("name") is not None and point.get("field") is not None
    }
    return {coverpoints[member] for member in cross.get("members", []) if member in coverpoints}


def _is_illegal_intr_test(sample: dict[str, Any]) -> bool:
    fields = sample.get("fields") or {}
    if not isinstance(fields, dict):
        return False
    return (
        fields.get("intr_test") == 1
        and fields.get("intr_state") == 0
    )


def _empty_group_audit(group: dict[str, Any]) -> dict[str, Any]:
    name = str(group["name"])
    return {
        "covergroup": name,
        "declared_sample_site": group.get("sample_site"),
        "expected_field_names": sorted(_field_names(group)),
        "expected_cross_names": sorted(
            str(cross.get("name")) for cross in group.get("crosses", [])
        ),
        "expected_capture_events": sorted(EXPECTED_EVENTS.get(name, set())),
        "trace_file_count": 0,
        "sample_count": 0,
        "observed_capture_events": {},
        "field_key_mismatch_count": 0,
        "cross_key_mismatch_count": 0,
        "cross_value_mismatch_count": 0,
        "illegal_cross_sample_count": 0,
        "illegal_cross_encoding_mismatch_count": 0,
        "count_event_metadata_missing_count": 0,
        "count_event_rtl_value_mismatch_count": 0,
        "trace_sample_count_mismatch_count": 0,
        "trace_covergroup_count_mismatch_count": 0,
        "errors": [],
    }


def _add_error(audit: dict[str, Any], message: str) -> None:
    if len(audit["errors"]) < 20:
        audit["errors"].append(message)


def build_audit(
    *,
    schema_path: Path = DEFAULT_SCHEMA,
    definitions_path: Path = DEFAULT_DEFINITIONS,
    trace_root: Path = DEFAULT_TRACE_ROOT,
) -> dict[str, Any]:
    schema = read_json(schema_path)
    definitions = read_json(definitions_path)
    groups = schema.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("coverage schema has no groups")
    group_by_name = {str(group["name"]): group for group in groups}
    aon_group_names = [name for name in group_by_name if name != "resets_cg"]
    group_audits = {
        name: _empty_group_audit(group_by_name[name]) for name in aon_group_names
    }
    trace_paths = _trace_files(trace_root)
    schema_counts: Counter[str] = Counter()
    source_revision_counts: Counter[str] = Counter()
    trace_errors: list[dict[str, Any]] = []
    unknown_group_samples = 0
    sample_count_total = 0
    valid_trace_count = 0
    count_metadata_statuses: Counter[str] = Counter()

    for trace_path in trace_paths:
        relative = _relative(trace_path)
        try:
            trace = read_json(trace_path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            trace_errors.append({"path": relative, "error": f"invalid_json: {exc}"})
            continue
        valid_trace_count += 1
        trace_schema_id = str(trace.get("schema_id", ""))
        schema_counts[trace_schema_id] += 1
        if trace_schema_id not in SUPPORTED_COVERAGE_SCHEMA_IDS:
            trace_errors.append({"path": relative, "error": "unsupported_trace_schema"})
        source_revision = str(trace.get("source_revision", ""))
        source_revision_counts[source_revision] += 1
        if source_revision != schema.get("source_revision"):
            trace_errors.append({"path": relative, "error": "source_revision_mismatch"})
        samples = trace.get("samples")
        if not isinstance(samples, list):
            trace_errors.append({"path": relative, "error": "samples_is_not_a_list"})
            continue
        sample_count_total += len(samples)
        if trace.get("sample_count") != len(samples):
            for audit in group_audits.values():
                audit["trace_sample_count_mismatch_count"] += 1
            trace_errors.append({"path": relative, "error": "sample_count_mismatch"})
        declared_counts = trace.get("sample_counts_by_covergroup") or {}
        actual_counts = Counter(str(sample.get("covergroup", "")) for sample in samples if isinstance(sample, dict))
        if not isinstance(declared_counts, dict) or declared_counts != dict(actual_counts):
            for audit in group_audits.values():
                audit["trace_covergroup_count_mismatch_count"] += 1
            trace_errors.append({"path": relative, "error": "sample_counts_by_covergroup_mismatch"})

        for sample in samples:
            if not isinstance(sample, dict):
                trace_errors.append({"path": relative, "error": "sample_is_not_an_object"})
                continue
            group_name = str(sample.get("covergroup", ""))
            if group_name not in group_audits:
                unknown_group_samples += 1
                continue
            audit = group_audits[group_name]
            audit["sample_count"] += 1
            fields = sample.get("fields")
            expected_fields = _field_names(group_by_name[group_name])
            if not isinstance(fields, dict) or set(fields) != expected_fields:
                audit["field_key_mismatch_count"] += 1
                _add_error(audit, f"{relative}: field keys do not match schema")
            event = str(sample.get("capture_event", ""))
            audit["observed_capture_events"][event] = (
                audit["observed_capture_events"].get(event, 0) + 1
            )
            expected_events = EXPECTED_EVENTS.get(group_name, set())
            if event not in expected_events:
                _add_error(audit, f"{relative}: unexpected capture event {event!r}")

            observed_crosses = sample.get("same_sample_cross_observations") or {}
            if not isinstance(observed_crosses, dict):
                audit["cross_key_mismatch_count"] += 1
                _add_error(audit, f"{relative}: same-sample cross observations are not an object")
                observed_crosses = {}
            expected_crosses = {
                str(cross.get("name")): cross
                for cross in group_by_name[group_name].get("crosses", [])
            }
            if set(observed_crosses) != set(expected_crosses):
                audit["cross_key_mismatch_count"] += 1
                _add_error(audit, f"{relative}: same-sample cross keys do not match schema")
            for cross_name, cross_value in observed_crosses.items():
                cross_definition = expected_crosses.get(cross_name)
                if not isinstance(cross_value, dict) or cross_definition is None:
                    audit["cross_key_mismatch_count"] += 1
                    _add_error(audit, f"{relative}: cross {cross_name!r} is not an object or is unknown")
                    continue
                expected_cross_fields = _cross_field_names(group_by_name[group_name], cross_definition)
                if set(cross_value) != expected_cross_fields:
                    audit["cross_key_mismatch_count"] += 1
                    _add_error(audit, f"{relative}: cross {cross_name!r} fields do not match schema")
                elif isinstance(fields, dict) and any(
                    cross_value.get(field) != fields.get(field)
                    for field in expected_cross_fields
                ):
                    audit["cross_value_mismatch_count"] += 1
                    _add_error(audit, f"{relative}: cross {cross_name!r} is not same-sample")

            if group_name == "intr_test_cg":
                illegal = _is_illegal_intr_test(sample)
                encoded = sample.get("illegal_cross_condition")
                if bool(encoded) != illegal:
                    audit["illegal_cross_encoding_mismatch_count"] += 1
                    _add_error(audit, f"{relative}: illegal cross flag disagrees with fields")
                if illegal:
                    audit["illegal_cross_sample_count"] += 1

            count_config = COUNT_EVENT_GROUPS.get(group_name)
            if count_config is not None:
                adapter = trace.get("capture_adapter")
                count_capture = adapter.get("count_event_capture") if isinstance(adapter, dict) else None
                count_capture = count_capture if isinstance(count_capture, dict) else {}
                status = str(count_capture.get("status", "missing"))
                count_metadata_statuses[status] += 1
                metadata_ok = (
                    count_capture.get("startup_cycles") == 4
                    and status == "SCOREBOARD_CADENCE_MODELED_RTL_COUNTERS_OBSERVED"
                    and isinstance(count_capture.get("counter_source"), str)
                    and bool(count_capture.get("counter_source"))
                    and "VCS" not in str(count_capture.get("counter_source"))
                )
                if not metadata_ok or not all(
                    key in sample for key in ("rtl_count", "scoreboard_countdown_cycles", "scoreboard_target_cycles")
                ):
                    audit["count_event_metadata_missing_count"] += 1
                elif isinstance(fields, dict) and sample.get("rtl_count") != fields.get(count_config["count_field"]):
                    audit["count_event_rtl_value_mismatch_count"] += 1

        for name, audit in group_audits.items():
            if actual_counts.get(name):
                audit["trace_file_count"] += 1

    for audit in group_audits.values():
        audit["observed_capture_events"] = dict(sorted(audit["observed_capture_events"].items()))
        audit["expected_capture_events_observed"] = set(audit["observed_capture_events"]) >= set(audit["expected_capture_events"])
        audit["structural_checks_passed"] = all(
            audit[key] == 0
            for key in (
                "field_key_mismatch_count",
                "cross_key_mismatch_count",
                "cross_value_mismatch_count",
                "illegal_cross_encoding_mismatch_count",
                "count_event_metadata_missing_count",
                "count_event_rtl_value_mismatch_count",
                "trace_sample_count_mismatch_count",
                "trace_covergroup_count_mismatch_count",
            )
        ) and audit["expected_capture_events_observed"] and not audit["errors"]

    observed_groups = [name for name, audit in group_audits.items() if audit["sample_count"]]
    aon_capture_protocol_complete = (
        set(observed_groups) == set(aon_group_names)
        and all(audit["structural_checks_passed"] for audit in group_audits.values())
        and not trace_errors
        and unknown_group_samples == 0
        and valid_trace_count == len(trace_paths)
    )
    shared_count = int(definitions.get("shared_or_other_definition_count", 0))
    aon_count = int(definitions.get("aon_timer_definition_count", 0))
    shared_scopes = sorted({
        str(definition.get("scope"))
        for definition in definitions.get("definitions", [])
        if str(definition.get("scope")) and not (
            "aon_timer_env_cov" in str(definition.get("scope"))
            or any(f"::{name}::" in str(definition.get("scope")) for name in ("intr_cg", "intr_pins_cg", "intr_test_cg"))
        )
    })
    return {
        "schema": "aon-timer-sample-site-mapping-audit-v1",
        "audit_tool_sha256": sha256_file(Path(__file__)),
        "status": "AON_CAPTURE_PROTOCOL_COMPLETE_SHARED_SCOPE_UNAVAILABLE" if aon_capture_protocol_complete else "AON_CAPTURE_PROTOCOL_INCOMPLETE",
        "source_revision": schema.get("source_revision"),
        "coverage_schema_id": schema.get("schema_id"),
        "trace_root": _relative(trace_root),
        "trace_file_count": len(trace_paths),
        "valid_trace_file_count": valid_trace_count,
        "sample_count": sample_count_total,
        "trace_schema_counts": dict(sorted(schema_counts.items())),
        "trace_source_revision_counts": dict(sorted(source_revision_counts.items())),
        "trace_errors": trace_errors,
        "unknown_group_sample_count": unknown_group_samples,
        "aon_covergroup_names": aon_group_names,
        "aon_capture_protocol_complete": aon_capture_protocol_complete,
        "shared_scope": {
            "definition_count": shared_count,
            "aon_definition_count": aon_count,
            "shared_scope_names": shared_scopes,
            "trace_adapter_supports_shared_scope": False,
            "status": "UNAVAILABLE_IN_AON_TRACE_SCOPE",
        },
        "count_event_timing": {
            "metadata_status_counts": dict(sorted(count_metadata_statuses.items())),
            "cadence_model_present": all(
                group_audits[group]["count_event_metadata_missing_count"] == 0
                for group in COUNT_EVENT_GROUPS
            ),
            "independent_uvm_vcs_comparison_complete": False,
            "status": "MODELED_RTL_COUNTERS_NO_INDEPENDENT_UVM_VCS_PARITY",
        },
        "groups": [group_audits[name] for name in aon_group_names],
        "mapping_gates": {
            "aon_capture_protocol_complete": aon_capture_protocol_complete,
            "shared_scope_mapping_complete": False,
            "timing_parity_complete": False,
            "exact_identity_mapping_complete": False,
        },
        "coverage_credit_granted": 0,
        "unknowns_are_misses": False,
        "inputs": {
            "coverage_schema": {"path": _relative(schema_path), "sha256": sha256_file(schema_path)},
            "definition_catalog": {"path": _relative(definitions_path), "sha256": sha256_file(definitions_path)},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--definitions", type=Path, default=DEFAULT_DEFINITIONS)
    parser.add_argument("--trace-root", type=Path, default=DEFAULT_TRACE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_audit(
        schema_path=args.schema,
        definitions_path=args.definitions,
        trace_root=args.trace_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    digest = sha256_file(args.output)
    sidecar = Path(str(args.output) + ".sha256")
    sidecar.write_text(f"{digest}  {args.output.name}\n", encoding="ascii")
    print(json.dumps({
        "status": result["status"],
        "trace_file_count": result["trace_file_count"],
        "aon_capture_protocol_complete": result["aon_capture_protocol_complete"],
        "output": str(args.output),
    }, sort_keys=True))
    return 0 if result["aon_capture_protocol_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
