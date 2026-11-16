"""Compare UVM scoreboard control messages with the Python scheduler's shape.

UVM_HIGH count/expiry messages identify event producers, not covergroup sample
invocations or sampled RTL values. This diagnostic cannot establish sampling
parity or grant coverage credit. The model's countdown length is inferred from
the observed count messages, and alignment starts at the first count message;
the startup delay is therefore an assumption, not a measured result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

try:
    from tools.coverage_model import SOURCE_REVISION, TimerSampleScheduler
except ModuleNotFoundError:
    from coverage_model import SOURCE_REVISION, TimerSampleScheduler


TOOL_SCHEMA = "aon-timer-uvm-vcs-control-shape-audit-v2"
ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "tools" / "coverage_model.py"
LABEL_TO_GROUP = {
    "WKUP": "wake_up_timer_thold_hit_cg",
    "WDOG Bark": "watchdog_timer_bark_thold_hit_cg",
    "WDOG Bite": "watchdog_timer_bite_thold_hit_cg",
}
COUNT_RE = re.compile(
    r"UVM_INFO\s+@\s+(?P<time>\d+)\s+ps:.*?\(aon_timer_scoreboard\.sv:(?:289|368|437)\).*?"
    r"(?P<label>WKUP|WDOG Bark|WDOG Bite) Timer count:\s+(?P<count>\d+)"
)
EXPIRY_RE = re.compile(
    r"UVM_INFO\s+@\s+(?P<time>\d+)\s+ps:.*?\(aon_timer_scoreboard\.sv:(?:292|371|440)\).*?"
    r"(?P<label>WKUP|WDOG Bark|WDOG Bite) Timer expired check for interrupts"
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_events(path: Path) -> list[dict[str, Any]]:
    events = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            match = COUNT_RE.search(line)
            kind = "count"
            if match is None:
                match = EXPIRY_RE.search(line)
                kind = "expiry"
            if match:
                record = {
                    "line": line_number,
                    "kind": kind,
                    "group": LABEL_TO_GROUP[match.group("label")],
                    "time_ps": int(match.group("time")),
                }
                if kind == "count":
                    record["count"] = int(match.group("count"))
                events.append(record)
    return events


def _scheduler_shape(target_cycles: int) -> dict[str, Any]:
    scheduler = TimerSampleScheduler()
    emitted = []
    # Only replay the first countdown. No measured enable time is available.
    for edge in range(1, scheduler.startup_cycles + target_cycles + 2):
        kinds = scheduler.tick(enabled=True, target_cycles=target_cycles)
        for kind in kinds:
            item = {"edge": edge, "kind": kind}
            if kind == "count":
                item["count"] = scheduler.countdown_cycles
            emitted.append(item)
        if "expiry" in kinds:
            break
    if not emitted:
        raise ValueError("Python scheduler emitted no events")
    first_edge = emitted[0]["edge"]
    for item in emitted:
        item["relative_edge"] = item.pop("edge") - first_edge
    return {
        "model": "tools.coverage_model.TimerSampleScheduler",
        "assumed_startup_cycles": scheduler.startup_cycles,
        "startup_delay_verified": False,
        "target_cycles_inferred_from_count_messages": target_cycles,
        "events": emitted,
    }


def _check_group(group: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    counts = [event for event in events if event["kind"] == "count"]
    expiries = [event for event in events if event["kind"] == "expiry"]
    count_times = [event["time_ps"] for event in counts]
    intervals = [right - left for left, right in zip(count_times, count_times[1:])]
    cadence_measurable = len(counts) > 1
    regular = bool(intervals) and len(set(intervals)) == 1 and intervals[0] > 0
    period = intervals[0] if regular else None
    python_shape = _scheduler_shape(len(counts)) if counts else None
    model_events = python_shape["events"] if python_shape else []
    origin = count_times[0] if counts else 0
    # With one count, only same-time count/expiry order is testable. The
    # multiplier 1 is a comparison convenience, not a measured clock period.
    scale = period or 1
    expected = [
        (item["kind"], item.get("count"), item["relative_edge"] * scale)
        for item in model_events
    ]
    observed = [
        (item["kind"], item.get("count"), item["time_ps"] - origin)
        for item in events
    ]
    passed = bool(counts) and len(expiries) == 1 and expected == observed and (
        not cadence_measurable or regular
    )
    return {
        "group": group,
        "count_event_count": len(counts),
        "expiry_event_count": len(expiries),
        "count_values": [event["count"] for event in counts],
        "count_timestamps_ps": count_times,
        "count_intervals_ps": intervals,
        "expiry_timestamps_ps": [event["time_ps"] for event in expiries],
        "same_edge_count_expiry": bool(counts and expiries) and (
            counts[-1]["time_ps"] == expiries[-1]["time_ps"]
        ),
        "cadence_measurable": cadence_measurable,
        "measured_count_interval_ps": period,
        "measured_count_interval_us": period / 1_000_000 if period else None,
        "python_scheduler_shape": python_shape,
        "shape_passed": passed,
    }


def audit_logs(
    paths: list[Path],
    *,
    source_revision: str = SOURCE_REVISION,
    expected_groups: dict[str, str] | None = None,
    source_log_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    if source_revision != SOURCE_REVISION:
        raise ValueError("source revision differs from the pinned OpenTitan baseline")
    names = [Path(path).name for path in paths]
    if len(set(names)) != len(names):
        raise ValueError("log names must be unique")
    for name, group in (expected_groups or {}).items():
        if name not in names or group not in LABEL_TO_GROUP.values():
            raise ValueError("expected group must name an input log and a supported timer group")
    if source_log_hashes is not None and (
        set(source_log_hashes) != set(names)
        or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
               for value in source_log_hashes.values())
    ):
        raise ValueError("source hashes must provide a SHA-256 for every input log")
    runs = []
    verified_groups = set()
    for path in paths:
        name = Path(path).name
        events = parse_events(path)
        groups = {
            group: _check_group(group, [event for event in events if event["group"] == group])
            for group in sorted({event["group"] for event in events})
        }
        primary = (expected_groups or {}).get(name)
        checked = [primary] if primary else sorted(groups)
        passed = bool(checked) and all(
            group in groups and groups[group]["shape_passed"] for group in checked
        )
        if passed:
            verified_groups.update(checked)
        runs.append({
            "log_name": name,
            "source_log_sha256": (source_log_hashes or {}).get(name),
            "event_excerpt_sha256": sha256_file(path),
            "event_count": len(events),
            "events": events,
            "groups": groups,
            "checked_groups": checked,
            "incidental_groups": sorted(set(groups) - set(checked)),
            "status": "PASS" if passed else "FAIL",
        })
    observed_groups = sorted({group for run in runs for group in run["groups"]})
    passed = bool(runs) and all(run["status"] == "PASS" for run in runs)
    return {
        "schema": TOOL_SCHEMA,
        "source_revision": source_revision,
        "source_revision_role": "INTENDED_BASELINE_ONLY",
        "build_source_revision_verified": False,
        "audit_tool_sha256": sha256_file(Path(__file__)),
        "python_model_sha256": sha256_file(MODEL_PATH),
        "status": "PASS" if passed else "FAIL",
        "observation_scope": "SCOREBOARD_CONTROL_MESSAGES_ONLY",
        "runs": runs,
        "observed_groups": observed_groups,
        "verified_shape_groups": sorted(verified_groups),
        "count_event_shape_comparison_complete": passed and (
            verified_groups == set(LABEL_TO_GROUP.values())
        ),
        "independent_uvm_vcs_timing_comparison_complete": False,
        "covergroup_sample_invocations_observed": False,
        "sample_values_compared": False,
        "startup_delay_verified": False,
        "coverage_credit_granted": 0,
        "unknowns_are_misses": False,
        "full_simulation_started": False,
        "limitations": [
            "Control messages precede event triggers; they do not record actual covergroup sample calls or RTL sample tuples.",
            "Same-time named event triggers need not imply two separate sample invocations; that requires instrumentation inside the sample branch.",
            "The scheduler target is inferred from observed count messages and first-count alignment; startup delay, stimulus and absolute timing are not verified.",
            "A single-count group cannot establish count cadence. Incidental groups never satisfy the three-group comparison gate.",
            "No testcase-by-testcase waveform, shared/non-AON, sleep/pause, update/restart or interrupt-pin parity is established.",
            "No VCS/URG hit counts are read or imported. A pinned baseline revision does not attest the prebuilt simv's complete source tree.",
        ],
    }


def _read_verified_json(path: Path) -> dict[str, Any]:
    sidecar = Path(str(path) + ".sha256").read_text(encoding="ascii").split()
    if sidecar != [sha256_file(path), path.name]:
        raise ValueError(f"SHA-256 sidecar mismatch: {path.name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path.name}")
    return data


def audit_evidence(directory: Path) -> dict[str, Any]:
    """Replay a public evidence bundle, checking its excerpts and provenance."""
    directory = Path(directory)
    provenance = _read_verified_json(directory / "provenance.json")
    source_hashes = _read_verified_json(directory / "source-hashes.json")
    if (provenance.get("schema") != "aon-timer-uvm-vcs-timing-evidence-provenance-v2"
            or provenance.get("source_revision") != SOURCE_REVISION
            or not provenance.get("logs")):
        raise ValueError("unsupported timing evidence provenance")
    paths = []
    primary_groups = {}
    for row in provenance["logs"]:
        name = row["log_name"]
        relative = Path(row["event_excerpt"])
        path = directory / relative
        if (relative.is_absolute() or ".." in relative.parts
                or not path.resolve().is_relative_to(directory.resolve())
                or path.name != name):
            raise ValueError("event excerpt must stay inside the evidence directory")
        if (sha256_file(path) != row["event_excerpt_sha256"]
                or len(parse_events(path)) != row["event_count"]
                or source_hashes.get(name) != row["sha256"]):
            raise ValueError("event excerpt/hash provenance mismatch")
        if (row.get("uvm_error_count") != 0 or row.get("uvm_fatal_count") != 0
                or row.get("test_passed_checks") is not True):
            raise ValueError("UVM run does not report zero errors/fatals and passed checks")
        paths.append(path)
        primary_groups[name] = row["primary_group"]
    report = audit_logs(paths, expected_groups=primary_groups, source_log_hashes=source_hashes)
    report["input_provenance_sha256"] = sha256_file(directory / "provenance.json")
    report["input_source_hashes_sha256"] = sha256_file(directory / "source-hashes.json")
    schema_path = ROOT / "configs" / "coverage_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    pinned_hash = next(row["sha256"] for row in schema["source_files"]
                       if row["path"] == "hw/ip/aon_timer/dv/env/aon_timer_scoreboard.sv")
    report["current_build_tree_scoreboard_matches_pinned"] = (
        provenance.get("vcs", {}).get("current_scoreboard_sha256") == pinned_hash
    )
    report["coverage_schema_sha256"] = sha256_file(schema_path)
    report["evidence_bundle_replayed"] = True
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--evidence-dir", type=Path)
    inputs.add_argument("--log", type=Path, action="append")
    parser.add_argument("--expected-group", action="append", default=[], metavar="LOG_NAME=GROUP")
    parser.add_argument("--source-hashes", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.evidence_dir:
            if args.expected_group or args.source_hashes:
                raise ValueError("--evidence-dir reads primary groups and source hashes from the bundle")
            report = audit_evidence(args.evidence_dir)
        else:
            primary = {}
            for item in args.expected_group:
                name, separator, group = item.partition("=")
                if not separator or name in primary:
                    raise ValueError("expected-group must be a unique LOG_NAME=GROUP")
                primary[name] = group
            hashes = json.loads(args.source_hashes.read_text(encoding="utf-8")) if args.source_hashes else None
            if hashes is not None and not isinstance(hashes, dict):
                raise ValueError("source hashes must be a JSON object")
            report = audit_logs(args.log, expected_groups=primary, source_log_hashes=hashes)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    Path(str(args.output) + ".sha256").write_text(
        f"{sha256_file(args.output)}  {args.output.name}\n", encoding="ascii"
    )
    print(json.dumps({key: report[key] for key in (
        "status", "count_event_shape_comparison_complete",
        "independent_uvm_vcs_timing_comparison_complete", "coverage_credit_granted",
    )}))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
