"""Separate adapter/schema for the explicitly repaired pinned reference.

The original adapter and all historical traces stay unchanged. Native named
events can coalesce count+expiry producers into one invocation at a timestamp.
"""
from __future__ import annotations
import json

try:
    from cocotb_coverage_adapter import CocotbCoverageAdapter, WDOG_REGWEN
except ModuleNotFoundError:
    from tools.cocotb_coverage_adapter import CocotbCoverageAdapter, WDOG_REGWEN


class PinnedSamplingFixedAdapterV1(CocotbCoverageAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # This is the SV local bit's initial value, not the register reset value.
        self.config["wdog_regwen"] = 0
        self._regwen_ral_mirror = 1

    def _update_address_phase_mirror(self, address: int, value: int) -> None:
        if address == WDOG_REGWEN:
            self._regwen_ral_mirror &= value & 1
            self.config["wdog_regwen"] = self._regwen_ral_mirror
        else:
            super()._update_address_phase_mirror(address, value)

    async def _monitor_aon_interrupt_pins(self, dut) -> None:
        from cocotb.triggers import Edge, First, ReadOnly

        pins = (dut.rst_req_o, dut.wkup_req_o)
        while True:
            await First(Edge(pins[0]), Edge(pins[1]))
            await ReadOnly()
            values = [int(pin.value) for pin in pins]
            for index in (1, 0):
                record = self.trace.sample_interrupt_pin(intr_pin=index, intr_pin_value=values[index])
                self._annotate(record, "aon_intr_pins_change")

    def sample_aon_edge(self, wkup_count: int, wdog_count: int) -> None:
        timers = (
            ("wakeup", self._wkup_scheduler, bool(self.wkup_enabled), self._wkup_target_cycles(),
             self._wkup_update_pending, self.config["prescale"] + 1),
            ("bark", self._bark_scheduler, bool(self.wdog_enabled), self._wdog_target_cycles("bark_thold"),
             self._wdog_update_pending, 1),
            ("bite", self._bite_scheduler, bool(self.wdog_enabled), self._wdog_target_cycles("bite_thold"),
             self._wdog_update_pending, 1),
        )
        for name, scheduler, enabled, target, update, delay in timers:
            producers = scheduler.tick(enabled=enabled, target_cycles=target,
                                       update_due=update, post_expiry_cycles=delay)
            if not producers:
                continue
            if "expiry" in producers:
                if name == "wakeup":
                    self.expected_intr_state |= 1
                elif name == "bark":
                    self.expected_intr_state |= 2
                else:
                    self.expected_bite_reset = 1
            # A native named event wakes the waiting consumer once. On the
            # final count edge the expiry state is already set when it resumes.
            if name == "wakeup":
                record = self.trace.sample_wakeup_timer_thold_hit(
                    wkup_int=self.expected_intr_state & 1, wkup_thold=self.config["wkup_thold"], wkup_count=wkup_count)
            elif name == "bark":
                record = self.trace.sample_watchdog_bark_thold_hit(
                    wdog_bark_int=(self.expected_intr_state >> 1) & 1, wdog_thold=self.config["bark_thold"], wdog_count=wdog_count)
            else:
                record = self.trace.sample_watchdog_bite_thold_hit(
                    wdog_bite_rst=self.expected_bite_reset, wdog_thold=self.config["bite_thold"], wdog_count=wdog_count)
            record["producer_events"] = producers
            record["rtl_count"] = wkup_count if name == "wakeup" else wdog_count
            record["scoreboard_countdown_cycles"] = scheduler.countdown_cycles
            record["scoreboard_target_cycles"] = target
            self._annotate(record, f"aon_native_named_event_{name}")
        self._wkup_update_pending = False
        self._wdog_update_pending = False

    async def _monitor_timer_samples(self, dut) -> None:
        from cocotb.triggers import ReadOnly, RisingEdge

        while True:
            await RisingEdge(dut.clk_aon_i)
            await ReadOnly()
            if not int(dut.rst_aon_ni.value):
                for scheduler in (self._wkup_scheduler, self._bark_scheduler, self._bite_scheduler):
                    scheduler.disable()
                self._wkup_update_pending = self._wdog_update_pending = False
                continue
            self.sample_aon_edge(int(dut.dbg_wkup_count_o.value), int(dut.dbg_wdog_count_o.value))

    def close(self):
        path = super().close()
        payload = json.loads(path.read_text())
        payload["parent_tuple_definitions_schema_id"] = payload["schema_id"]
        payload["schema_id"] = "aon_timer_pinned_sampling_fix_trace_v1"
        payload["source_variant"] = "pinned-sampling-fixes-v1"
        payload["coverage_status"] = "DIAGNOSTIC_FIXED_VARIANT_NO_CANONICAL_CREDIT"
        payload["coverage_credit_granted"] = 0
        payload["resolved_canonical_bin_identity_hit_counts"] = {}
        for sample in payload["samples"]:
            sample["resolved_canonical_bin_identity_hits"] = []
        payload["capture_adapter"]["schema"] = "aon-timer-pinned-sampling-fixed-adapter-v1"
        payload["capture_adapter"]["count_event_capture"]["status"] = "FIXED_REFERENCE_NAMED_EVENT_CADENCE_DIAGNOSTIC"
        payload["capture_adapter"]["complete_parity_verified"] = False
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return path
