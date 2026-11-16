"""v2 adapter: fixed reference plus measured reset and sleep control inputs."""
from __future__ import annotations
import json
try:
    from pinned_sampling_fixed_adapter import PinnedSamplingFixedAdapterV1
except ModuleNotFoundError:
    from tools.pinned_sampling_fixed_adapter import PinnedSamplingFixedAdapterV1


class PinnedSamplingMatrixAdapterV2(PinnedSamplingFixedAdapterV1):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Match the DUT's two-flop sleep synchronizer in the AON domain.
        self._sleep_sync_stages = [0, 0]

    def _sync_sleep_input(self, sleep: int) -> int:
        synchronized = self._sleep_sync_stages[0]
        self._sleep_sync_stages = [int(bool(sleep)), synchronized]
        return synchronized

    def reset_local_state(self) -> None:
        """Mirror the fourth declared repair: the reference scoreboard's reset body."""
        self.config.update({"prescale": 0, "bark_thold": 0, "bite_thold": 0,
            "wkup_thold": 0, "wdog_regwen": 1, "pause_in_sleep": 0,
            "wkup_cause": 0})
        self._regwen_ral_mirror = 1
        self.wkup_enabled = self.wdog_enabled = 0
        self.expected_intr_state = self.expected_bite_reset = 0
        self._count_mirror.update({"wkup": 0, "wdog": 0})
        self._sleep_sync_stages = [0, 0]
        for scheduler in (self._wkup_scheduler, self._bark_scheduler, self._bite_scheduler):
            scheduler.disable()
        self._wkup_update_pending = self._wdog_update_pending = False

    def on_reset_asserted(self) -> None:
        self.reset_local_state()

    def sample_aon_edge(self, wkup_count: int, wdog_count: int, sleep: int) -> None:
        timers = (
            ("wakeup", self._wkup_scheduler, bool(self.wkup_enabled), self._wkup_target_cycles(),
             self._wkup_update_pending, self.config["prescale"] + 1),
            ("bark", self._bark_scheduler, bool(self.wdog_enabled), self._wdog_target_cycles("bark_thold"),
             self._wdog_update_pending, 1),
            ("bite", self._bite_scheduler, bool(self.wdog_enabled), self._wdog_target_cycles("bite_thold"),
             self._wdog_update_pending, 1),
        )
        for name, scheduler, enabled, target, update, delay in timers:
            if name != "wakeup" and self.config["pause_in_sleep"] and sleep:
                continue
            producers = scheduler.tick(enabled=enabled, target_cycles=target,
                update_due=update, post_expiry_cycles=delay)
            if not producers:
                continue
            if "expiry" in producers:
                if name == "wakeup": self.expected_intr_state |= 1
                elif name == "bark": self.expected_intr_state |= 2
                else: self.expected_bite_reset = 1
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
        if not (self.config["pause_in_sleep"] and sleep):
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
                self._sleep_sync_stages = [0, 0]
                continue
            self.sample_aon_edge(int(dut.dbg_wkup_count_o.value), int(dut.dbg_wdog_count_o.value),
                self._sync_sleep_input(int(dut.sleep_mode_i.value)))

    def close(self):
        path = super().close()
        payload = json.loads(path.read_text())
        payload["schema_id"] = "aon_timer_pinned_sampling_matrix_trace_v1"
        payload["source_variant"] = "pinned-sampling-fixes-v2"
        payload["capture_adapter"]["schema"] = "aon-timer-pinned-sampling-matrix-adapter-v2"
        payload["capture_adapter"]["reset_local_mirror_restored"] = True
        payload["capture_adapter"]["sleep_pin_is_explicit_input"] = True
        payload["capture_adapter"]["complete_parity_verified"] = False
        payload["coverage_credit_granted"] = 0
        payload["canonical_bin_vector"] = None
        payload["resolved_canonical_bin_identity_hit_counts"] = {}
        for sample in payload["samples"]:
            sample["resolved_canonical_bin_identity_hits"] = []
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return path
