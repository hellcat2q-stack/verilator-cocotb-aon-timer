from __future__ import annotations

import unittest

from tools.cocotb_coverage_adapter import (
    INTR_STATE,
    INTR_TEST,
    WDOG_CTRL,
    WKUP_CTRL,
    WKUP_THOLD_LO,
    CocotbCoverageAdapter,
)


class CocotbCoverageAdapterTests(unittest.TestCase):
    def make_adapter(self) -> CocotbCoverageAdapter:
        return CocotbCoverageAdapter("adapter_test", run_id="unit-test", seed=1)

    def test_configuration_sample_uses_pre_write_mirror(self):
        adapter = self.make_adapter()
        adapter.on_write_address(WKUP_THOLD_LO, 0x1234)
        adapter.on_write_address(WKUP_CTRL, 7)

        first, second = adapter.trace.samples
        self.assertEqual(first["fields"]["wkup_thold"], 0)
        self.assertEqual(second["fields"]["wkup_thold"], 0x1234)
        self.assertEqual(second["fields"]["prescale"], 0)
        self.assertEqual(second["capture_event"], "tl_addr_phase")

    def test_intr_test_records_both_scoreboard_channel_invocations(self):
        adapter = self.make_adapter()
        adapter.on_write_address(INTR_TEST, 0b11)
        adapter.on_write_data(INTR_TEST, 0b11)

        samples = [sample for sample in adapter.trace.samples if sample["covergroup"] == "intr_test_cg"]
        self.assertEqual(len(samples), 4)
        self.assertEqual(
            [sample["capture_event"] for sample in samples],
            [
                "tl_addr_phase_intr_test",
                "tl_addr_phase_intr_test",
                "tl_data_phase_intr_test",
                "tl_data_phase_intr_test",
            ],
        )
        self.assertTrue(all(sample["fields"]["intr_state"] == 1 for sample in samples))

    def test_intr_state_read_records_each_interrupt_with_current_enable(self):
        adapter = self.make_adapter()
        adapter.on_write_address(WKUP_CTRL, 1)
        adapter.on_write_address(WDOG_CTRL, 2)
        adapter.on_read_data(INTR_STATE, 0b10)

        samples = [sample for sample in adapter.trace.samples if sample["covergroup"] == "intr_cg"]
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0]["fields"], {"intr": 0, "intr_en": 1, "intr_state": 0})
        self.assertEqual(samples[1]["fields"], {"intr": 1, "intr_en": 0, "intr_state": 1})


if __name__ == "__main__":
    unittest.main()
