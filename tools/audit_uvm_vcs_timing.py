"""Audit a compact UVM/VCS scoreboard timing trace against the Python model.

The parser consumes only UVM_HIGH scoreboard lines for the three AON timer
count-event groups.  It checks event order, count values, equal AON-clock
spacing, and the scoreboard's same-edge ``count`` + ``expiry`` behavior.  A
run may declare one primary group so that an incidental event from another
watchdog timer is retained as diagnostic data without being mistaken for a
failed primary run.  It does not read coverage counts, URG databases, or
vector rows, and it never creates canonical coverage credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SOURCE_REVISION = "9f20940d494a223cc950a5b98f748fb28109d458"
TOOL_SCHEMA = "aon-timer-uvm-vcs-timing-audit-v1"

COUNT_RE = re.compile(
    r"UVM_INFO\s+@\s+(?P<time>\d+)\s+ps:.*?\(aon_timer_scoreboard\.sv:(?:289|368|437)\).*?"
    r"(?P<label>WKUP|WDOG Bark|WDOG Bite) Timer count:\s+(?P<count>\d+)"
)
EXPIRY_RE = re.compile(
    r"UVM_INFO\s+@\s+(?P<time>\d+)\s+ps:.*?\(aon_timer_scoreboard\.sv:(?:292|371|440)\).*?"
    r"(?P<label>WKUP|WDOG Bark|WDOG Bite) Timer expired check for interrupts"
)

LABEL_TO_GROUP = {
    "WKUP": "wake_up_timer_thold_hit_cg",
    "WDOG Bark": "watchdog_timer_bark_thold_hit_cg",
    "WDOG Bite": "watchdog_timer_bite_thold_hit_cg",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(Path(path).read_text(errors="replace").splitlines(), 1):
        match = COUNT_RE.search(line)
        if match:
            label = match.group("label")
            events.append({
                "line": line_number,
                "kind": "count",
                "group": LABEL_TO_GROUP[label],
                "label": label,
                "time_ps": int(match.group("time")),
                "count": int(match.group("count")),
            })
            continue
        match = EXPIRY_RE.search(line)
        if match:
            label = match.group("label")
            events.append({
                "line": line_number,
                "kind": "expiry",
                "group": LABEL_TO_GROUP[label],
                "label": label,
                "time_ps": int(match.group("time")),
            })
    return events


def _check_group(group: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    counts = [event for event in events if event["kind"] == "count"]
    expiries = [event for event in events if event["kind"] == "expiry"]
    count_values = [event["count"] for event in counts]
    count_times = [event["time_ps"] for event in counts]
    intervals = [right - left for left, right in zip(count_times, count_times[1:])]
    same_edge_expiry = bool(counts and expiries and expiries[-1]["time_ps"] == counts[-1]["time_ps"])
    expected_values = list(range(1, len(counts) + 1))
    passed = bool(counts and expiries) and (
        count_values == expected_values
        and len(set(intervals)) <= 1
        and all(interval > 0 for interval in intervals)
        and same_edge_expiry
    )
    return {
        "group": group,
        "count_event_count": len(counts),
        "expiry_event_count": len(expiries),
        "count_values": count_values,
        "count_timestamps_ps": count_times,
        "count_intervals_ps": intervals,
        "expiry_timestamps_ps": [event["time_ps"] for event in expiries],
        "same_edge_count_expiry": same_edge_expiry,
        "python_scheduler_shape": {
            "startup_cycles": 4,
            "count_values": expected_values,
            "expiry_shares_final_count_edge": True,
        },
        "passed": passed,
    }


def audit_logs(
    paths: list[Path],
    *,
    source_revision: str = SOURCE_REVISION,
    expected_groups: dict[str, str] | None = None,
    source_log_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    if source_revision != SOURCE_REVISION:
        raise ValueError("source revision differs from the pinned OpenTitan revision")
    runs: list[dict[str, Any]] = []
    for path in paths:
        events = parse_events(path)
        groups = {
            group: _check_group(group, [event for event in events if event["group"] == group])
            for group in sorted(LABEL_TO_GROUP.values())
            if any(event["group"] == group for event in events)
        }
        expected_group = (expected_groups or {}).get(Path(path).name)
        checked_groups = [expected_group] if expected_group else sorted(groups)
        checked_group_results = [groups[group] for group in checked_groups if group in groups]
        all_checked_groups_present = len(checked_group_results) == len(checked_groups)
        runs.append({
            "log_name": Path(path).name,
            "log_sha256": (source_log_hashes or {}).get(Path(path).name, sha256_file(path)),
            "event_excerpt_sha256": sha256_file(path),
            "event_count": len(events),
            "groups": groups,
            "expected_group": expected_group,
            "checked_groups": checked_groups,
            "incidental_groups": sorted(set(groups) - set(checked_groups)),
            "status": "PASS" if all_checked_groups_present and checked_group_results and all(
                item["passed"] for item in checked_group_results
            ) else "FAIL",
        })
    observed_groups = sorted({group for run in runs for group in run["groups"]})
    return {
        "schema": TOOL_SCHEMA,
        "source_revision": source_revision,
        "status": "PASS" if runs and all(run["status"] == "PASS" for run in runs) else "FAIL",
        "runs": runs,
        "observed_groups": observed_groups,
        "observed_group_count": len(observed_groups),
        "expected_group_count": 3,
        "independent_uvm_vcs_timing_comparison_complete": len(observed_groups) == 3
        and bool(runs)
        and all(run["status"] == "PASS" for run in runs),
        "coverage_credit_granted": 0,
        "unknowns_are_misses": False,
        "full_simulation_started": False,
        "limitations": [
            "This is a compact UVM_HIGH scoreboard event-shape comparison; it does not import VCS/URG hit counts.",
            "The VCS and Cocotb runs use separate test stimuli; this audit establishes cadence shape, not testcase-by-testcase waveform equivalence.",
            "Shared/non-AON covergroups and interrupt pin timing are outside this count-event audit.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, action="append", required=True)
    parser.add_argument(
        "--expected-group",
        action="append",
        default=[],
        metavar="LOG_NAME=GROUP",
        help="Restrict a run's pass/fail check to its primary group; incidental events remain recorded.",
    )
    parser.add_argument(
        "--source-hashes",
        type=Path,
        help="Optional JSON object mapping compact log names to hashes of the complete source logs.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected_groups: dict[str, str] = {}
    for item in args.expected_group:
        name, separator, group = item.partition("=")
        if not separator or not name or not group:
            parser.error(f"invalid --expected-group {item!r}; use LOG_NAME=GROUP")
        expected_groups[name] = group
    source_log_hashes = None
    if args.source_hashes:
        source_log_hashes = json.loads(args.source_hashes.read_text(encoding="utf-8"))
        if not isinstance(source_log_hashes, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in source_log_hashes.items()
        ):
            parser.error("--source-hashes must contain a JSON object of string names to string hashes")
    report = audit_logs(args.log, expected_groups=expected_groups, source_log_hashes=source_log_hashes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "observed_groups": report["observed_groups"],
        "independent_uvm_vcs_timing_comparison_complete": report[
            "independent_uvm_vcs_timing_comparison_complete"
        ],
        "coverage_credit_granted": report["coverage_credit_granted"],
    }))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
