import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import stage09_protocol
from tools.coverage_model import CoverageTrace
from tools.run_stage09_comparison import replay_trace


class Stage09ProtocolTests(unittest.TestCase):
    def test_frozen_stimuli_span_all_160_reference_array_bins(self):
        arrays = stage09_protocol.checked_arrays()
        pool, protocol = stage09_protocol.make_inputs()
        observed = {name: set() for name in arrays}
        for action in pool["actions"]:
            for step in action["stimulus"].get("steps", []):
                values = {"prescale": step["prescale"], "bark": step["wdog_bark_threshold"],
                          "bite": step["wdog_bite_threshold"], "wkup": step["wkup_threshold"]}
                for name, value in values.items():
                    for entry in arrays[name]:
                        low, high = entry["value_range"]
                        if low <= value <= high:
                            observed[name].add(entry["ordinal"])
        self.assertEqual({name: len(ordinals) for name, ordinals in observed.items()},
                         {"prescale": 32, "bark": 32, "bite": 32, "wkup": 64})
        self.assertEqual(protocol["attempt_budget_per_policy_seed"] * len(protocol["policies"])
                         * len(protocol["selection_seeds"]), 288)
        self.assertNotIn("hits", pool)

    def test_policies_have_distinct_and_reproducible_definitions(self):
        arms = ["b", "a", "c"]
        history = [{"testcase": "b", "reward": 0.0}, {"testcase": "a", "reward": 1.0},
                   {"testcase": "c", "reward": 0.0}]
        self.assertEqual(stage09_protocol.choose(arms, history, "ucb", 7, 0.01)[0], "a")
        self.assertEqual(stage09_protocol.choose(arms, history, "ucb_no_reward", 7, 0.01)[0], "b")
        first = [stage09_protocol.choose(arms, history[:i], "random", 19, 0.01)[0] for i in range(8)]
        replay = [stage09_protocol.choose(arms, history[:i], "random", 19, 0.01)[0] for i in range(8)]
        self.assertEqual(first, replay)
        self.assertEqual([stage09_protocol.choose(arms, history[:i], "full", 1, 0.01)[0]
                          for i in range(4)], ["b", "a", "c", "b"])

    def test_changed_frozen_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "configs/stage09").mkdir(parents=True)
            (root / "references").mkdir()
            values = {"configs/stage09/action-pool.json": "pool",
                      "configs/stage09/protocol.json": "protocol",
                      "references/array_bin_ranges.v1.json": "arrays"}
            for relative, value in values.items():
                (root / relative).write_text(value, encoding="utf-8")
            freeze = {"schema": "aon-timer-stage09-input-freeze-v1",
                      "status": "FROZEN_BEFORE_FORMAL_RUN",
                      "source_revision": stage09_protocol.REVISION,
                      "sha256": {key: stage09_protocol.digest(root / key)
                                 for key in values if key.startswith("configs/")},
                      "array_reference_sha256": stage09_protocol.digest(root / "references/array_bin_ranges.v1.json")}
            (root / "configs/stage09/freeze.json").write_text(json.dumps(freeze), encoding="utf-8")
            with patch.object(stage09_protocol, "ROOT", root), \
                    patch.object(stage09_protocol, "ARRAY_PATH", root / "references/array_bin_ranges.v1.json"):
                self.assertEqual(stage09_protocol.validate_freeze(), freeze)
                (root / "configs/stage09/protocol.json").write_text("changed", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "frozen input changed"):
                    stage09_protocol.validate_freeze()

    def test_empty_sample_trace_is_rejected(self):
        trace = CoverageTrace("run", "case", 1).to_dict()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.json"
            path.write_text(json.dumps(trace), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "empty"):
                replay_trace(path, "run", "case", 1, stage09_protocol.REVISION,
                             trace["schema_id"], 0)


if __name__ == "__main__":
    unittest.main()
