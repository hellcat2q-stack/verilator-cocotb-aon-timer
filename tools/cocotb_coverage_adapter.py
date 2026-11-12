"""Capture source-aligned raw coverage samples from the Cocotb test harness.

This adapter records only sample calls whose data and trigger are observable in
the current testbench: timer configuration writes, INTR_STATE reads,
INTR_TEST writes, and AON interrupt-pin changes. It does not infer count-based
timer samples or emit canonical bin vectors.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    from coverage_model import CoverageTrace
except ModuleNotFoundError:  # Support package-style imports in unit tests.
    from tools.coverage_model import CoverageTrace


WKUP_CTRL = 0x04
WKUP_THOLD_HI = 0x08
WKUP_THOLD_LO = 0x0C
WKUP_COUNT_HI = 0x10
WKUP_COUNT_LO = 0x14
WDOG_REGWEN = 0x18
WDOG_CTRL = 0x1C
WDOG_BARK_THOLD = 0x20
WDOG_BITE_THOLD = 0x24
WDOG_COUNT = 0x28
INTR_STATE = 0x2C
INTR_TEST = 0x30
WKUP_CAUSE = 0x34

VALID_CSR_ADDRESSES = {
    WKUP_CTRL,
    WKUP_THOLD_HI,
    WKUP_THOLD_LO,
    WKUP_COUNT_HI,
    WKUP_COUNT_LO,
    WDOG_REGWEN,
    WDOG_CTRL,
    WDOG_BARK_THOLD,
    WDOG_BITE_THOLD,
    WDOG_COUNT,
    INTR_STATE,
    INTR_TEST,
    WKUP_CAUSE,
}


def simulation_time_ns() -> float | None:
    try:
        from cocotb.utils import get_sim_time

        return float(get_sim_time(units="ns"))
    except (ImportError, RuntimeError, TypeError):
        return None


class CocotbCoverageAdapter:
    """Maintain the source scoreboard's observable mirror and record samples."""

    def __init__(self, testcase: str, run_id: str | None = None, seed: int | None = None):
        self.run_id = run_id or os.environ.get("RUN_ID", "stage04-untracked")
        self.seed = int(seed if seed is not None else os.environ.get("RANDOM_SEED", "1"))
        self.testcase = testcase
        self.trace = CoverageTrace(self.run_id, testcase, self.seed)
        self.config = {
            "prescale": 0,
            "bark_thold": 0,
            "bite_thold": 0,
            "wkup_thold": 0,
            "wdog_regwen": 1,
            "pause_in_sleep": 0,
            "wkup_cause": 0,
        }
        self.wkup_enabled = 0
        self.wdog_enabled = 0
        self.expected_intr_state = 0
        self._pin_task = None

    @staticmethod
    def _annotate(record: dict[str, Any], event: str) -> dict[str, Any]:
        record["capture_event"] = event
        time_ns = simulation_time_ns()
        if time_ns is not None:
            record["simulation_time_ns"] = time_ns
        return record

    def on_write_address(self, address: int, value: int) -> None:
        """Mirror the UVM address-phase sample order for valid CSR writes."""
        if address not in VALID_CSR_ADDRESSES:
            return

        self._annotate(self.trace.sample_timer_cfg(**self.config), "tl_addr_phase")

        # The pinned scoreboard updates expected interrupt state before it
        # invokes intr_test_cg.sample() at the address phase.
        if address == INTR_TEST:
            self._sample_intr_test(value, "tl_addr_phase_intr_test")

        self._update_address_phase_mirror(address, value)

    def _update_address_phase_mirror(self, address: int, value: int) -> None:
        if address == WKUP_CTRL:
            self.config["prescale"] = (value >> 1) & 0xFFF
            self.wkup_enabled = value & 1
        elif address == WDOG_CTRL:
            self.wdog_enabled = value & 1
            self.config["pause_in_sleep"] = (value >> 1) & 1
        elif address == WKUP_THOLD_LO:
            self.config["wkup_thold"] = (self.config["wkup_thold"] & 0xFFFFFFFF00000000) | value
        elif address == WKUP_THOLD_HI:
            self.config["wkup_thold"] = (self.config["wkup_thold"] & 0xFFFFFFFF) | (value << 32)
        elif address == WDOG_BARK_THOLD:
            self.config["bark_thold"] = value & 0xFFFFFFFF
        elif address == WDOG_BITE_THOLD:
            self.config["bite_thold"] = value & 0xFFFFFFFF
        elif address == WDOG_REGWEN:
            self.config["wdog_regwen"] = value & 1
        elif address == WKUP_CAUSE and (value & 1) == 0:
            self.config["wkup_cause"] = 0

    def on_write_data(self, address: int, value: int) -> None:
        """Apply scoreboard state updates performed on the TL data phase."""
        if address == INTR_STATE:
            self.expected_intr_state &= ~(value & 0b11)
        elif address == INTR_TEST:
            self._sample_intr_test(value, "tl_data_phase_intr_test")

    def _sample_intr_test(self, value: int, event: str) -> None:
        for interrupt in range(2):
            bit = (value >> interrupt) & 1
            if bit:
                self.expected_intr_state |= 1 << interrupt
            enabled = self.wkup_enabled if interrupt == 0 else self.wdog_enabled
            record = self.trace.sample_interrupt_test(
                intr=interrupt,
                intr_test=bit,
                intr_en=enabled,
                intr_state=(self.expected_intr_state >> interrupt) & 1,
            )
            self._annotate(record, event)

    def on_read_data(self, address: int, value: int) -> None:
        """Record the paired interrupt samples on an INTR_STATE data read."""
        if address == INTR_STATE:
            for interrupt in range(2):
                enabled = self.wkup_enabled if interrupt == 0 else self.wdog_enabled
                record = self.trace.sample_interrupt(
                    intr=interrupt,
                    intr_en=enabled,
                    intr_state=(value >> interrupt) & 1,
                )
                self._annotate(record, "tl_data_phase_intr_state_read")
        elif address == WKUP_CTRL:
            self.config["prescale"] = (value >> 1) & 0xFFF
            self.wkup_enabled = value & 1
        elif address == WDOG_CTRL:
            self.wdog_enabled = value & 1
            self.config["pause_in_sleep"] = (value >> 1) & 1
        elif address == WKUP_THOLD_LO:
            self.config["wkup_thold"] = (self.config["wkup_thold"] & 0xFFFFFFFF00000000) | value
        elif address == WKUP_THOLD_HI:
            self.config["wkup_thold"] = (self.config["wkup_thold"] & 0xFFFFFFFF) | (value << 32)
        elif address == WDOG_BARK_THOLD:
            self.config["bark_thold"] = value & 0xFFFFFFFF
        elif address == WDOG_BITE_THOLD:
            self.config["bite_thold"] = value & 0xFFFFFFFF
        elif address == WDOG_REGWEN:
            self.config["wdog_regwen"] = value & 1
        elif address == WKUP_CAUSE:
            self.config["wkup_cause"] = value & 1

    def start_pin_monitor(self, dut) -> None:
        import cocotb

        self._pin_task = cocotb.start_soon(self._monitor_aon_interrupt_pins(dut))

    async def _monitor_aon_interrupt_pins(self, dut) -> None:
        from cocotb.triggers import Edge, First, ReadOnly

        # In aon_timer_scoreboard, AON pin 0 is reset request and pin 1 is
        # wakeup request. Both values are sampled whenever either pin changes.
        pins = (dut.rst_req_o, dut.wkup_req_o)
        while True:
            await First(Edge(pins[0]), Edge(pins[1]))
            await ReadOnly()
            values: list[int] = []
            for pin in pins:
                try:
                    value = int(pin.value)
                except (ValueError, TypeError):
                    values = []
                    break
                if value not in (0, 1):
                    values = []
                    break
                values.append(value)
            if values:
                for index, value in enumerate(values):
                    record = self.trace.sample_interrupt_pin(
                        intr_pin=index, intr_pin_value=value
                    )
                    self._annotate(record, "aon_intr_pins_change")

    def close(self) -> Path:
        if self._pin_task is not None:
            self._pin_task.kill()
            self._pin_task = None
        output_dir = Path(
            os.environ.get("COVERAGE_TRACE_DIR", Path.cwd() / "coverage-traces")
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{self.run_id}__{self.testcase}__seed{self.seed}.json"
        path = output_dir / filename
        payload = self.trace.to_dict()
        payload["capture_adapter"] = {
            "schema": "aon-timer-cocotb-raw-trace-v1",
            "status": "PARTIAL_SOURCE_SAMPLE_TRACE",
            "integrated_sample_sites": [
                "timer_cfg_cg on accepted valid CSR write address phase",
                "intr_test_cg on INTR_TEST address and data phase invocations",
                "intr_cg on INTR_STATE read data phase",
                "intr_pins_cg on AON reset-request or wakeup-request pin change",
            ],
            "not_integrated": [
                "wake_up_timer_thold_hit_cg count-event samples",
                "watchdog_timer_bark_thold_hit_cg count-event samples",
                "watchdog_timer_bite_thold_hit_cg count-event samples",
                "conditional resets_cg and 228 shared/non-AON identities",
            ],
            "canonical_vector_generated": False,
            "value_partition_status": "UNRESOLVED",
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path
