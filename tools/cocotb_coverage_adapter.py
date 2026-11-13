"""Capture source-aligned raw coverage samples from the Cocotb test harness."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    from coverage_model import CoverageTrace, TimerSampleScheduler
except ModuleNotFoundError:  # Support package-style imports in unit tests.
    from tools.coverage_model import CoverageTrace, TimerSampleScheduler


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
        self.expected_bite_reset = 0
        self._count_mirror = {"wkup": 0, "wdog": 0}
        self._wkup_scheduler = TimerSampleScheduler()
        self._bark_scheduler = TimerSampleScheduler()
        self._bite_scheduler = TimerSampleScheduler()
        self._wkup_update_pending = False
        self._wdog_update_pending = False
        self._tasks = []

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
        elif address == WKUP_CAUSE:
            self._mirror_wkup_interrupt_status(value)

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
        elif address == WKUP_COUNT_LO:
            self._count_mirror["wkup"] = (self._count_mirror["wkup"] & 0xFFFFFFFF00000000) | value
        elif address == WKUP_COUNT_HI:
            self._count_mirror["wkup"] = (self._count_mirror["wkup"] & 0xFFFFFFFF) | (value << 32)
        elif address == WDOG_BARK_THOLD:
            self.config["bark_thold"] = value & 0xFFFFFFFF
        elif address == WDOG_BITE_THOLD:
            self.config["bite_thold"] = value & 0xFFFFFFFF
        elif address == WDOG_COUNT:
            self._count_mirror["wdog"] = value & 0xFFFFFFFF
        elif address == WDOG_REGWEN:
            # WDOG_REGWEN is W0C: writing zero locks it until reset; writing
            # one never unlocks a previously locked register.
            self.config["wdog_regwen"] &= value & 1
        elif address == WKUP_CAUSE and (value & 1) == 0:
            self.config["wkup_cause"] = 0

    def on_write_data(self, address: int, value: int) -> None:
        """Apply scoreboard state updates performed on the TL data phase."""
        if address in {WKUP_THOLD_HI, WKUP_THOLD_LO, WKUP_COUNT_HI, WKUP_COUNT_LO, WKUP_CTRL}:
            self._wkup_update_pending = True
        if address in {WDOG_BARK_THOLD, WDOG_BITE_THOLD, WDOG_COUNT}:
            self._wdog_update_pending = True
        if address == INTR_STATE:
            self.expected_intr_state &= ~(value & 0b11)
        elif address == INTR_TEST:
            self._sample_intr_test(value, "tl_data_phase_intr_test")
        elif address == WKUP_CAUSE:
            self._mirror_wkup_interrupt_status(value)

    def on_read_address(self, address: int, request_data: int = 0) -> None:
        """Mirror local side effects before RAL predicts returned read data."""
        if address == WKUP_CAUSE:
            self._mirror_wkup_interrupt_status(request_data)

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

    def on_read_data(self, address: int, value: int, request_data: int = 0) -> None:
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
        elif address == WKUP_CAUSE:
            self._mirror_wkup_interrupt_status(request_data)
        # The pinned scoreboard reads local RAL mirrors before calling
        # predict(UVM_PREDICT_READ), so a read response does not update its
        # local coverage fields until a later qualifying CSR write.

    def _mirror_wkup_interrupt_status(self, request_data: int) -> None:
        """Match the pinned scoreboard's WKUP_CAUSE case assignment."""
        self.expected_intr_state = (self.expected_intr_state & ~1) | (request_data & 1)

    def start_pin_monitor(self, dut) -> None:
        import cocotb

        self._tasks = [
            cocotb.start_soon(self._monitor_aon_interrupt_pins(dut)),
            cocotb.start_soon(self._monitor_timer_samples(dut)),
        ]

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

    def _wkup_target_cycles(self) -> int:
        count = self._count_mirror["wkup"]
        threshold = self.config["wkup_thold"]
        if count > threshold:
            return 0
        return (threshold - count + 1) * (self.config["prescale"] + 1)

    def _wdog_target_cycles(self, threshold_key: str) -> int:
        count = self._count_mirror["wdog"]
        threshold = self.config[threshold_key]
        return threshold - count if count < threshold else 0

    async def _monitor_timer_samples(self, dut) -> None:
        from cocotb.triggers import ReadOnly, RisingEdge

        while True:
            await RisingEdge(dut.clk_aon_i)
            await ReadOnly()
            if int(dut.rst_aon_ni.value) == 0:
                self._wkup_scheduler.disable()
                self._bark_scheduler.disable()
                self._bite_scheduler.disable()
                self._wkup_update_pending = False
                self._wdog_update_pending = False
                continue
            try:
                wkup_count = int(dut.dbg_wkup_count_o.value)
                wdog_count = int(dut.dbg_wdog_count_o.value)
            except (AttributeError, ValueError, TypeError):
                continue

            timer_events = (
                (
                    "wakeup",
                    self._wkup_scheduler,
                    bool(self.wkup_enabled),
                    self._wkup_target_cycles(),
                    self._wkup_update_pending,
                    self.config["prescale"] + 1,
                ),
                (
                    "bark",
                    self._bark_scheduler,
                    bool(self.wdog_enabled),
                    self._wdog_target_cycles("bark_thold"),
                    self._wdog_update_pending,
                    1,
                ),
                (
                    "bite",
                    self._bite_scheduler,
                    bool(self.wdog_enabled),
                    self._wdog_target_cycles("bite_thold"),
                    self._wdog_update_pending,
                    1,
                ),
            )
            for timer_name, scheduler, enabled, target_cycles, update_due, restart_delay in timer_events:
                events = scheduler.tick(
                    enabled=enabled,
                    target_cycles=target_cycles,
                    update_due=update_due,
                    post_expiry_cycles=restart_delay,
                )
                for event in events:
                    if event == "expiry":
                        if timer_name == "wakeup":
                            self.expected_intr_state |= 1
                        elif timer_name == "bark":
                            self.expected_intr_state |= 2
                        else:
                            self.expected_bite_reset = 1
                    if timer_name == "wakeup":
                        record = self.trace.sample_wakeup_timer_thold_hit(
                            wkup_int=self.expected_intr_state & 1,
                            wkup_thold=self.config["wkup_thold"],
                            wkup_count=wkup_count,
                        )
                    elif timer_name == "bark":
                        record = self.trace.sample_watchdog_bark_thold_hit(
                            wdog_bark_int=(self.expected_intr_state >> 1) & 1,
                            wdog_thold=self.config["bark_thold"],
                            wdog_count=wdog_count,
                        )
                    else:
                        record = self.trace.sample_watchdog_bite_thold_hit(
                            wdog_bite_rst=self.expected_bite_reset,
                            wdog_thold=self.config["bite_thold"],
                            wdog_count=wdog_count,
                        )
                    record["capture_event"] = f"aon_countdown_{timer_name}_{event}"
                    record["scoreboard_countdown_cycles"] = scheduler.countdown_cycles
                    record["scoreboard_target_cycles"] = target_cycles
                    record["rtl_count"] = wkup_count if timer_name == "wakeup" else wdog_count
                    self._annotate(record, record["capture_event"])

            self._wkup_update_pending = False
            self._wdog_update_pending = False

    def close(self) -> Path:
        for task in self._tasks:
            task.kill()
        self._tasks.clear()
        output_dir = Path(
            os.environ.get("COVERAGE_TRACE_DIR", Path.cwd() / "coverage-traces")
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{self.run_id}__{self.testcase}__seed{self.seed}.json"
        path = output_dir / filename
        payload = self.trace.to_dict()
        payload["capture_adapter"] = {
            "schema": "aon-timer-cocotb-raw-trace-v2",
            "status": "PARTIAL_SOURCE_SAMPLE_TRACE",
            "integrated_sample_sites": [
                "timer_cfg_cg on accepted valid CSR write address phase",
                "intr_test_cg on INTR_TEST address and data phase invocations",
                "intr_cg on INTR_STATE read data phase",
                "intr_pins_cg on AON reset-request or wakeup-request pin change",
                "three timer count-event groups on AON clocks using source countdown lengths and RTL counts",
            ],
            "not_integrated": [
                "conditional resets_cg and 228 shared/non-AON identities",
                "canonical auto-bin and cross identity mapping for count-event samples",
            ],
            "count_event_capture": {
                "status": "SCOREBOARD_CADENCE_MODELED_RTL_COUNTERS_OBSERVED",
                "startup_cycles": 4,
                "counter_source": "aon_timer_tb read-only debug outputs from pinned RTL internal counter state",
                "sleep_mode": "fixed low by aon_timer_tb",
                "canonical_bin_vector_generated": False,
            },
            "canonical_vector_generated": False,
            "value_partition_status": "UNRESOLVED",
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path
