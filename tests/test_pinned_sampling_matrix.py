"""Unit checks for matrix-only reset and sleep behavior."""
import unittest

from tools.pinned_sampling_matrix_adapter import PinnedSamplingMatrixAdapterV2


class PinnedSamplingMatrixTests(unittest.TestCase):
    def test_sleep_input_uses_two_aon_edge_synchronizer(self):
        adapter = PinnedSamplingMatrixAdapterV2("sleep-sync", "test", 1)
        self.assertEqual(adapter._sync_sleep_input(1), 0)
        self.assertEqual(adapter._sync_sleep_input(1), 1)
        self.assertEqual(adapter._sync_sleep_input(0), 1)
        self.assertEqual(adapter._sync_sleep_input(0), 0)

    def test_hard_reset_restores_scoreboard_local_state(self):
        adapter = PinnedSamplingMatrixAdapterV2("reset", "test", 1)
        adapter.config.update({"prescale": 7, "bark_thold": 8, "bite_thold": 9,
            "wkup_thold": 10, "wdog_regwen": 0, "pause_in_sleep": 1,
            "wkup_cause": 1})
        adapter.wkup_enabled = adapter.wdog_enabled = 1
        adapter.expected_intr_state = adapter.expected_bite_reset = 1
        adapter._count_mirror.update({"wkup": 11, "wdog": 12})
        adapter.on_reset_asserted()
        self.assertEqual(adapter.config, {"prescale": 0, "bark_thold": 0, "bite_thold": 0,
            "wkup_thold": 0, "wdog_regwen": 1, "pause_in_sleep": 0, "wkup_cause": 0})
        self.assertEqual(adapter._count_mirror, {"wkup": 0, "wdog": 0})
        self.assertEqual((adapter.wkup_enabled, adapter.wdog_enabled,
            adapter.expected_intr_state, adapter.expected_bite_reset), (0, 0, 0, 0))

    def test_watchdog_clock_and_pending_update_pause_in_sleep(self):
        adapter = PinnedSamplingMatrixAdapterV2("sleep", "test", 1)
        adapter.config["pause_in_sleep"] = 1
        adapter.config["bark_thold"] = 30
        adapter.wdog_enabled = 1
        adapter._wdog_update_pending = True
        for edge in range(1, 9):
            adapter.sample_aon_edge(0, edge, sleep=1)
        self.assertEqual(adapter._bark_scheduler.countdown_cycles, 0)
        self.assertTrue(adapter._wdog_update_pending)
        adapter.sample_aon_edge(0, 9, sleep=0)
        self.assertFalse(adapter._wdog_update_pending)
        self.assertEqual(adapter._bark_scheduler.countdown_cycles, 0)

    def test_matrix_protocol_has_eight_cases_and_full_is_disabled(self):
        from json import loads
        from pathlib import Path
        protocol = loads((Path(__file__).parents[1] / "configs/stage10-sample-matrix-v1.json").read_text())
        self.assertEqual(protocol["case_ids"], list(range(8)))
        self.assertFalse(protocol["full_simulation_started"])
        self.assertEqual(protocol["coverage_credit_granted"], 0)


if __name__ == "__main__":
    unittest.main()
