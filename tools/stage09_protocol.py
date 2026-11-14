"""Frozen engineering comparison inputs and deterministic online selectors."""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]
REVISION = "9f20940d494a223cc950a5b98f748fb28109d458"
ARRAY_PATH = ROOT / "references/array_bin_ranges.v1.json"
POLICIES = ("ucb", "random", "full", "ucb_no_reward")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def checked_arrays():
    """Fail closed on modified, gapped, duplicated or foreign reference bins."""
    payload = ARRAY_PATH.read_bytes()
    expected = ARRAY_PATH.with_suffix(".json.sha256").read_text().split()[0]
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError("array reference checksum mismatch")
    document = json.loads(payload)
    if document["source_revision"] != REVISION:
        raise ValueError("array reference revision mismatch")
    canonical = set((ROOT / "references/canonical_bin_ids.txt").read_text().splitlines())
    arrays = document["arrays"]
    seen = set()
    for name, count, width, cp in (
        ("prescale", 32, 12, "prescale_cp"), ("bark", 32, 32, "bark_thold_cp"),
        ("bite", 32, 32, "bite_thold_cp"), ("wkup", 64, 64, "wkup_thold_cp"),
    ):
        entries = arrays[name]
        if len(entries) != count:
            raise ValueError("wrong array length")
        next_low = 1
        for ordinal, entry in enumerate(entries):
            low, high = entry["value_range"]
            identity = entry["canonical_identity"]
            label = f"aon_timer_env_pkg::aon_timer_env_cov::timer_cfg_cg||variable||{cp}||name:{name}[{ordinal}]||0"
            if (entry["ordinal"] != ordinal or low != next_low or high < low
                    or identity != label or identity not in canonical or identity in seen):
                raise ValueError("invalid array partition or identity")
            seen.add(identity)
            next_low = high + 1
        if next_low != 2 ** width:
            raise ValueError("array reference does not span declared width")
    return arrays


def validate_freeze():
    freeze_path = ROOT / "configs/stage09/freeze.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    expected = {
        "configs/stage09/action-pool.json": ROOT / "configs/stage09/action-pool.json",
        "configs/stage09/protocol.json": ROOT / "configs/stage09/protocol.json",
    }
    if freeze.get("schema") != "aon-timer-stage09-input-freeze-v1" or freeze.get("status") != "FROZEN_BEFORE_FORMAL_RUN":
        raise ValueError("invalid Stage 09 freeze")
    if freeze.get("source_revision") != REVISION:
        raise ValueError("frozen source revision mismatch")
    for name, path in expected.items():
        if freeze.get("sha256", {}).get(name) != digest(path):
            raise ValueError(f"frozen input changed: {name}")
    if freeze.get("array_reference_sha256") != digest(ARRAY_PATH):
        raise ValueError("frozen array reference changed")
    return freeze


def make_inputs():
    arrays = checked_arrays()
    actions = []
    for block in range(8):
        steps = []
        for index in range(block * 8, (block + 1) * 8):
            endpoint = 0 if index < 32 else 1
            steps.append({
                "wkup_threshold": arrays["wkup"][index]["value_range"][endpoint],
                "wdog_bark_threshold": arrays["bark"][index % 32]["value_range"][endpoint],
                "wdog_bite_threshold": arrays["bite"][index % 32]["value_range"][endpoint],
                "prescale": arrays["prescale"][index % 32]["value_range"][endpoint],
                "wdog_pause_in_sleep": index % 2,
            })
        actions.append({"name": f"aon_s09_config_block_{block}",
                        "base_test": "aon_timer_config_batch_sequence", "stimulus": {"steps": steps}})
    for name, wakeup, watchdog, prescale in (("zero", 0, 0, 0), ("max", 2**64-1, 2**32-1, 4095)):
        actions.append({"name": f"aon_s09_endpoint_{name}", "base_test": "aon_timer_config_batch_sequence",
                        "stimulus": {"steps": [{"wkup_threshold": wakeup, "wdog_bark_threshold": watchdog,
                            "wdog_bite_threshold": watchdog, "prescale": prescale, "wdog_pause_in_sleep": 0}]}})
    old_pool = json.loads((ROOT / "configs/stage05-test-pool.json").read_text())
    for case in old_pool["testcases"][:2]:
        actions.append({"name": "aon_s09_" + case["name"].removeprefix("aon_timer_").removesuffix("_sequence"),
                        "base_test": case["name"], "stimulus": case["stimulus"]})
    pool = {"schema": "aon-timer-stage08-action-pool-v1", "pool_id": "stage09-array-partition-blocks-v1",
            "source_revision": REVISION, "deterministic": True, "seed_list": [1], "actions": actions,
            "scope": "Python reference configuration-array membership and source-named positives; no VCS parity claim"}
    protocol = {"schema": "aon-timer-stage09-engineering-comparison-v1",
                "experiment_id": "stage09-array-blocks-v1", "source_revision": REVISION,
                "coverage_schema_id": "aon_timer_uvm_source_trace_v2",
                "pool_path": "configs/stage09/action-pool.json", "freeze_path": "configs/stage09/freeze.json",
                "policies": list(POLICIES), "selection_seeds": [1, 7, 19], "simulation_seed": 1,
                "attempt_budget_per_policy_seed": 24, "workers": 1,
                "timeout_seconds_per_attempt": 120, "simulation_time_limit_ns_per_attempt": 25000,
                "total_simulation_time_cap_ns_per_policy_seed": 600000,
                "exploration_coefficient": 0.01,
                "reward": "new_observed_positive_count / 4507; failures get zero and consume attempts",
                "full_definition": "round_robin_over_all_actions_in_frozen_order",
                "random_definition": "uniform_with_replacement; no guaranteed initial exploration",
                "ucb_definition": "one warmup per action, then mean novelty plus exploration bonus",
                "ablation_definition": "same UCB warmup and exploration, with all selection reward means set to zero",
                "comparison_scope": "Engineering pilot only; not paper cluster UCB, paper Full or full functional coverage",
                "wall_time_policy": "precompile once before all methods; report actual simulation cost separately; no wall-time superiority claim"}
    return pool, protocol


def choose(arms, history, policy, seed, exploration):
    if policy not in POLICIES:
        raise ValueError("unsupported comparison policy")
    if policy == "full":
        return arms[len(history) % len(arms)], "round_robin", {}
    if policy == "random":
        rng = random.Random(seed)
        action = None
        for _ in range(len(history) + 1):
            action = rng.choice(arms)
        return action, "uniform_random", {}
    counts = Counter(row["testcase"] for row in history)
    for arm in arms:
        if not counts[arm]:
            return arm, "warmup", {}
    scores = {}
    for arm in arms:
        average = (sum(row["reward"] for row in history if row["testcase"] == arm) / counts[arm]
                   if policy == "ucb" else 0.0)
        scores[arm] = average + exploration * math.sqrt(2 * math.log(len(history)) / counts[arm])
    return max(arms, key=lambda arm: scores[arm]), policy, scores


def freeze_inputs():
    target = ROOT / "configs/stage09"
    target.mkdir(exist_ok=False)
    pool, protocol = make_inputs()
    for name, value in (("action-pool.json", pool), ("protocol.json", protocol)):
        (target / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    freeze = {"schema": "aon-timer-stage09-input-freeze-v1", "status": "FROZEN_BEFORE_FORMAL_RUN",
              "source_revision": REVISION,
              "sha256": {"configs/stage09/" + name: digest(target / name)
                         for name in ("action-pool.json", "protocol.json")},
              "array_reference_sha256": digest(ARRAY_PATH)}
    (target / "freeze.json").write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"actions": len(pool["actions"]), "policies": protocol["policies"],
                      "attempts_planned": len(protocol["policies"]) * len(protocol["selection_seeds"]) * protocol["attempt_budget_per_policy_seed"]}))


if __name__ == "__main__":
    freeze_inputs()
