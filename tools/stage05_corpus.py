"""Freeze validation and result helpers for the initial Stage 05 corpus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POOL_PATH = ROOT / "configs" / "stage05-test-pool.json"
DEFAULT_FREEZE_PATH = ROOT / "configs" / "stage05-freeze.json"
EXPECTED_TESTCASES = [
    "aon_timer_smoke_sequence",
    "aon_timer_jump_sequence",
    "aon_timer_prescaler_sequence",
    "aon_timer_intr_test_sequence",
]
EXPECTED_STIMULUS_FIELDS = {
    "aon_timer_smoke_sequence": {
        "wkup_threshold", "wdog_bark_threshold", "wdog_bite_threshold", "wdog_pause_in_sleep"
    },
    "aon_timer_jump_sequence": {
        "initial_count", "initial_threshold", "counter_run_aon_cycles", "threshold_below_live_count_by"
    },
    "aon_timer_prescaler_sequence": {
        "prescaler_values", "wkup_threshold", "count_readback_settle_aon_cycles", "max_expiry_aon_cycles"
    },
    "aon_timer_intr_test_sequence": {"intr_test_mask", "intr_propagation_aon_cycles"},
}
PINNED_REVISION = "9f20940d494a223cc950a5b98f748fb28109d458"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_pool_sha256(pool_bytes: bytes) -> str:
    """Hash frozen JSON text consistently across LF/CRLF checkouts."""
    return hashlib.sha256(pool_bytes.replace(b"\r\n", b"\n")).hexdigest()


def load_frozen_pool(
    pool_path: Path = DEFAULT_POOL_PATH,
    freeze_path: Path = DEFAULT_FREEZE_PATH,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    pool_path = Path(pool_path).resolve()
    freeze_path = Path(freeze_path).resolve()
    pool_bytes = pool_path.read_bytes()
    pool = json.loads(pool_bytes)
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))

    if freeze.get("schema") != "aon-timer-stage05-freeze-v1":
        raise ValueError("unsupported stage05 freeze schema")
    if freeze.get("status") != "FROZEN_BEFORE_FORMAL_RUN":
        raise ValueError("the test pool is not frozen")
    if freeze.get("source_revision") != PINNED_REVISION:
        raise ValueError("freeze source revision does not match the pinned RTL")
    if pool.get("schema") != "aon-timer-stage05-test-pool-v1":
        raise ValueError("unsupported stage05 test pool schema")
    if pool.get("source_revision") != PINNED_REVISION:
        raise ValueError("test pool source revision does not match the pinned RTL")
    if pool.get("pool_id") == "":
        raise ValueError("pool_id must not be empty")
    if pool.get("deterministic") is not True:
        raise ValueError("the initial test pool must declare deterministic=true")

    expected_pool_path = (ROOT / freeze["pool_path"]).resolve()
    if pool_path != expected_pool_path:
        raise ValueError("the supplied test pool path differs from the frozen path")

    # Freeze against canonical text bytes so Windows CRLF checkout conversion
    # does not invalidate an otherwise identical JSON document.
    pool_hash = canonical_pool_sha256(pool_bytes)
    if pool_hash != freeze.get("pool_sha256"):
        raise ValueError("test pool SHA-256 does not match the freeze record")

    testcases = pool.get("testcases")
    if not isinstance(testcases, list):
        raise ValueError("testcases must be a list")
    names = [case.get("name") for case in testcases]
    if names != EXPECTED_TESTCASES:
        raise ValueError(f"frozen testcase order must be {EXPECTED_TESTCASES}")
    for case in testcases:
        if not case.get("official_mapping") or not isinstance(case.get("stimulus"), dict):
            raise ValueError(f"testcase {case['name']} needs an official mapping and stimulus object")
        stimulus = case["stimulus"]
        if set(stimulus) != EXPECTED_STIMULUS_FIELDS[case["name"]]:
            raise ValueError(f"testcase {case['name']} has an unexpected stimulus schema")
        for name, value in stimulus.items():
            if name == "prescaler_values":
                if (
                    not isinstance(value, list)
                    or len(value) < 2
                    or any(not isinstance(item, int) or isinstance(item, bool) or not 0 <= item <= 4095 for item in value)
                    or len(set(value)) != len(value)
                ):
                    raise ValueError("prescaler_values must contain at least two unique 12-bit integers")
            elif not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{case['name']}.{name} must be an integer")
        for key in EXPECTED_STIMULUS_FIELDS[case["name"]] - {"prescaler_values"}:
            if stimulus[key] < 0:
                raise ValueError(f"{case['name']}.{key} must be non-negative")

    smoke = testcases[0]["stimulus"]
    if any(not 1 <= smoke[key] <= 10 for key in ("wkup_threshold", "wdog_bark_threshold", "wdog_bite_threshold")):
        raise ValueError("smoke thresholds must remain in the official 1..10 constraint range")
    if smoke["wdog_pause_in_sleep"] not in (0, 1):
        raise ValueError("wdog_pause_in_sleep must be 0 or 1")
    jump = testcases[1]["stimulus"]
    if any(jump[key] > 0xFFFFFFFF for key in ("initial_count", "initial_threshold")):
        raise ValueError("the initial jump profile must fit the 32-bit count datapath")
    if jump["counter_run_aon_cycles"] == 0 or jump["threshold_below_live_count_by"] == 0:
        raise ValueError("jump timing and below-count offset must be positive")
    prescaler = testcases[2]["stimulus"]
    if (
        not 0 < prescaler["wkup_threshold"] <= 0xFFFFFFFF
        or prescaler["count_readback_settle_aon_cycles"] < 0
        or prescaler["max_expiry_aon_cycles"] == 0
    ):
        raise ValueError("prescaler threshold/timing parameters are outside the supported domain")
    intr_test = testcases[3]["stimulus"]
    if not 0 < intr_test["intr_test_mask"] <= 0b11 or intr_test["intr_propagation_aon_cycles"] == 0:
        raise ValueError("intr-test mask or propagation interval is outside the two-interrupt domain")

    seeds = pool.get("seed_list")
    if not isinstance(seeds, list) or not seeds:
        raise ValueError("seed_list must be a non-empty list")
    if any(not isinstance(seed, int) or isinstance(seed, bool) or seed < 0 for seed in seeds):
        raise ValueError("all seeds must be non-negative integers")
    if len(seeds) != len(set(seeds)):
        raise ValueError("seed_list must not contain duplicates")

    budget = pool.get("budget", {})
    if budget.get("suite_runs") != len(seeds):
        raise ValueError("suite_runs must equal the frozen number of seeds")
    if budget.get("workers") != 1:
        raise ValueError("the initial corpus protocol requires workers=1")
    for field in ("wall_clock_timeout_seconds_per_run", "simulation_time_limit_ns_per_suite"):
        if not isinstance(budget.get(field), int) or budget[field] <= 0:
            raise ValueError(f"budget.{field} must be a positive integer")

    coverage = pool.get("coverage_policy", {})
    if coverage.get("generate_coverage_vector") is not False:
        raise ValueError("this frozen protocol must not claim an unmapped coverage vector")
    if coverage.get("expected_canonical_bin_count") != 4507:
        raise ValueError("the frozen protocol must retain the 4,507-bin reference count")

    return pool, freeze, pool_hash
