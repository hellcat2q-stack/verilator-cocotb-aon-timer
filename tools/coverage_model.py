"""Source-faithful AON Timer coverage sample trace.

This records the arguments passed at each source-defined covergroup sample
call. It deliberately does not fabricate a 4,507-bin vector while the exact
VCS/URG bin identity manifest and auto-bin partitions are unavailable.
"""

from __future__ import annotations

import json
import hashlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SOURCE_REVISION = "9f20940d494a223cc950a5b98f748fb28109d458"
SUPPORTED_COVERAGE_SCHEMA_IDS = {
    "aon_timer_uvm_source_trace_v1",
    "aon_timer_uvm_source_trace_v2",
}
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "configs" / "coverage_schema.json"
BIN_CATALOG_PATH = Path(__file__).resolve().parents[1] / "references" / "canonical_bin_catalog.json"
BIN_IDS_PATH = Path(__file__).resolve().parents[1] / "references" / "canonical_bin_ids.txt"


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        schema = json.load(stream)
    if schema.get("source_revision") != SOURCE_REVISION:
        raise ValueError("coverage schema source revision does not match this model")
    if schema.get("schema_id") not in SUPPORTED_COVERAGE_SCHEMA_IDS:
        raise ValueError("unsupported coverage trace schema")
    return schema


class TimerSampleScheduler:
    """Model the pinned scoreboard's startup and countdown sample cadence."""

    def __init__(self, startup_cycles: int = 4):
        if startup_cycles < 0:
            raise ValueError("startup_cycles must be non-negative")
        self.startup_cycles = startup_cycles
        self.waiting_for_enable = True
        self.startup_remaining = startup_cycles
        self.countdown_cycles = 0
        self.post_expiry_remaining = 0

    def enable(self) -> None:
        if self.waiting_for_enable:
            self.waiting_for_enable = False
            self.startup_remaining = self.startup_cycles
            self.countdown_cycles = 0

    def disable(self) -> None:
        self.waiting_for_enable = True
        self.startup_remaining = self.startup_cycles
        self.countdown_cycles = 0
        self.post_expiry_remaining = 0

    def restart_after_expiry(self) -> None:
        self.disable()

    def tick(
        self,
        *,
        enabled: bool,
        target_cycles: int,
        update_due: bool = False,
        post_expiry_cycles: int = 0,
    ) -> list[str]:
        """Return sample events emitted on this AON clock edge."""
        if target_cycles < 0:
            raise ValueError("target_cycles must be non-negative")
        if post_expiry_cycles < 0:
            raise ValueError("post_expiry_cycles must be non-negative")
        if not enabled:
            self.disable()
            return []
        if self.post_expiry_remaining:
            self.post_expiry_remaining -= 1
            return []
        self.enable()
        if self.startup_remaining:
            self.startup_remaining -= 1
            if self.startup_remaining or target_cycles:
                return []
            self.waiting_for_enable = True
            self.startup_remaining = self.startup_cycles
            self.post_expiry_remaining = post_expiry_cycles
            return ["expiry"]
        if update_due:
            self.countdown_cycles = 0
            if target_cycles == 0:
                self.waiting_for_enable = True
                self.startup_remaining = self.startup_cycles
                self.post_expiry_remaining = post_expiry_cycles
                return ["expiry"]
            self.countdown_cycles = 1
            if self.countdown_cycles == target_cycles:
                self.waiting_for_enable = True
                self.startup_remaining = self.startup_cycles
                self.post_expiry_remaining = post_expiry_cycles
                return ["count", "expiry"]
            return ["count"]
        if self.countdown_cycles < target_cycles:
            self.countdown_cycles += 1
            if self.countdown_cycles == target_cycles:
                self.waiting_for_enable = True
                self.post_expiry_remaining = post_expiry_cycles
                return ["count", "expiry"]
            return ["count"]
        self.waiting_for_enable = True
        self.startup_remaining = self.startup_cycles
        self.post_expiry_remaining = post_expiry_cycles
        return ["expiry"]


def load_bin_catalog() -> tuple[dict[str, Any], list[str]]:
    with BIN_CATALOG_PATH.open(encoding="utf-8") as stream:
        catalog = json.load(stream)
    bin_ids = BIN_IDS_PATH.read_text(encoding="utf-8").splitlines()
    expected_hash = catalog["canonical_bin_ids_sha256"]
    actual_hash = hashlib.sha256(BIN_IDS_PATH.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError("canonical bin identity list does not match its catalog hash")
    if len(bin_ids) != catalog["canonical_bin_count"] or len(set(bin_ids)) != len(bin_ids):
        raise ValueError("canonical bin identity list count or uniqueness check failed")
    return catalog, bin_ids


class CoverageTrace:
    """Record raw SV covergroup sample tuples without inventing bin IDs."""

    def __init__(self, run_id: str, testcase: str, seed: int):
        if not run_id or not testcase:
            raise ValueError("run_id and testcase must be non-empty")
        if not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a non-negative integer")

        self.schema = load_schema()
        self.bin_catalog, self.bin_ids = load_bin_catalog()
        self.run_id = run_id
        self.testcase = testcase
        self.seed = seed
        self.samples: list[dict[str, Any]] = []
        self._sample_counts: Counter[str] = Counter()
        self._last_interrupt_pin: dict[int, int] = {}
        self._reset_history: list[int] = []
        self._resolved_explicit_hits: Counter[str] = Counter()
        self._canonical_identity_hits: Counter[str] = Counter()

        self._groups = {group["name"]: group for group in self.schema["groups"]}
        self._canonical_id_by_source_bin: dict[tuple[str, str, str, str], str] = {}
        for identity in self.bin_ids:
            scope, kind, item, bin_label, instance_index = identity.split("||")
            group_name = scope.split("::")[-1]
            # This initial bridge covers the AON Timer's explicitly named bins.
            # Shared covergroups and generated/array bins need their own semantics.
            if group_name in self._groups and instance_index == "0":
                self._canonical_id_by_source_bin[
                    (group_name, kind, item, bin_label.removeprefix("name:"))
                ] = identity

    def _validate_fields(self, group_name: str, fields: dict[str, int]) -> None:
        group = self._groups[group_name]
        expected_fields = set(group["fields"])
        if set(fields) != expected_fields:
            raise ValueError(
                f"{group_name} expects fields {sorted(expected_fields)}, "
                f"got {sorted(fields)}"
            )

        for field_name, value in fields.items():
            if not isinstance(value, int):
                raise ValueError(f"{group_name}.{field_name} must be an integer")
            spec = group["fields"][field_name]
            width = spec.get("width")
            if isinstance(width, int):
                maximum = (1 << width) - 1
                if not 0 <= value <= maximum:
                    raise ValueError(
                        f"{group_name}.{field_name}={value} is outside 0..{maximum}"
                    )
            elif field_name in {"intr", "intr_pin"}:
                num_interrupts = self.schema["environment_parameters"]["num_interrupts"]
                if not 0 <= value < num_interrupts:
                    raise ValueError(
                        f"{group_name}.{field_name} must be in 0..{num_interrupts - 1}"
                    )

    def _record(self, group_name: str, fields: dict[str, int]) -> dict[str, Any]:
        self._validate_fields(group_name, fields)
        group = self._groups[group_name]
        cross_observations: dict[str, dict[str, int]] = {}
        for cross in group.get("crosses", []):
            observation: dict[str, int] = {}
            for member in cross["members"]:
                coverpoint = next(
                    (point for point in group["coverpoints"] if point["name"] == member),
                    None,
                )
                if coverpoint is None:
                    raise ValueError(f"schema cross references unknown coverpoint: {member}")
                source_field = coverpoint.get("field")
                if source_field is not None:
                    observation[source_field] = fields[source_field]
            cross_observations[cross["name"]] = observation

        explicit_bins: list[str] = []
        canonical_identities: list[str] = []
        array_declarations: list[str] = []
        for coverpoint in group["coverpoints"]:
            field_name = coverpoint.get("field")
            if field_name is None:
                continue
            value = fields[field_name]
            for bin_spec in coverpoint.get("explicit_bins", []):
                if value in bin_spec["values"]:
                    qualified_name = (
                        f"{group_name}.{coverpoint['name']}.{bin_spec['name']}"
                    )
                    explicit_bins.append(qualified_name)
                    self._resolved_explicit_hits[qualified_name] += 1
                    canonical_identity = self._canonical_id_by_source_bin.get(
                        (group_name, "variable", coverpoint["name"], bin_spec["name"])
                    )
                    if canonical_identity is not None:
                        canonical_identities.append(canonical_identity)
                        self._canonical_identity_hits[canonical_identity] += 1
            array_spec = coverpoint.get("array_bins")
            if array_spec and array_spec["range"][0] <= value <= array_spec["range"][1]:
                array_declarations.append(
                    f"{group_name}.{coverpoint['name']}.{array_spec['name']}[]"
                )

        sample_index = self._sample_counts[group_name]
        self._sample_counts[group_name] += 1
        record = {
            "sample_index": len(self.samples),
            "group_sample_index": sample_index,
            "covergroup": group_name,
            "fields": dict(fields),
            "same_sample_cross_observations": cross_observations,
            "resolved_explicit_bin_memberships": explicit_bins,
            "resolved_canonical_bin_identity_hits": canonical_identities,
            "unpartitioned_array_declarations": array_declarations,
        }
        self.samples.append(record)
        return record

    def sample_timer_cfg(
        self,
        *,
        prescale: int,
        bark_thold: int,
        bite_thold: int,
        wkup_thold: int,
        wdog_regwen: int,
        pause_in_sleep: int,
        wkup_cause: int,
    ) -> dict[str, Any]:
        return self._record(
            "timer_cfg_cg",
            {
                "prescale": prescale,
                "bark_thold": bark_thold,
                "bite_thold": bite_thold,
                "wkup_thold": wkup_thold,
                "wdog_regwen": wdog_regwen,
                "pause_in_sleep": pause_in_sleep,
                "wkup_cause": wkup_cause,
            },
        )

    def sample_wakeup_timer_thold_hit(
        self, *, wkup_int: int, wkup_thold: int, wkup_count: int
    ) -> dict[str, Any]:
        return self._record(
            "wake_up_timer_thold_hit_cg",
            {"wkup_int": wkup_int, "wkup_thold": wkup_thold, "wkup_count": wkup_count},
        )

    def sample_watchdog_bite_thold_hit(
        self, *, wdog_bite_rst: int, wdog_thold: int, wdog_count: int
    ) -> dict[str, Any]:
        return self._record(
            "watchdog_timer_bite_thold_hit_cg",
            {
                "wdog_bite_rst": wdog_bite_rst,
                "wdog_thold": wdog_thold,
                "wdog_count": wdog_count,
            },
        )

    def sample_watchdog_bark_thold_hit(
        self, *, wdog_bark_int: int, wdog_thold: int, wdog_count: int
    ) -> dict[str, Any]:
        return self._record(
            "watchdog_timer_bark_thold_hit_cg",
            {
                "wdog_bark_int": wdog_bark_int,
                "wdog_thold": wdog_thold,
                "wdog_count": wdog_count,
            },
        )

    def sample_interrupt(self, *, intr: int, intr_en: int, intr_state: int) -> dict[str, Any]:
        return self._record(
            "intr_cg", {"intr": intr, "intr_en": intr_en, "intr_state": intr_state}
        )

    def sample_interrupt_test(
        self, *, intr: int, intr_test: int, intr_en: int, intr_state: int
    ) -> dict[str, Any]:
        record = self._record(
            "intr_test_cg",
            {
                "intr": intr,
                "intr_test": intr_test,
                "intr_en": intr_en,
                "intr_state": intr_state,
            },
        )
        record["illegal_cross_condition"] = bool(intr_test and not intr_state)
        return record

    def sample_interrupt_pin(self, *, intr_pin: int, intr_pin_value: int) -> dict[str, Any]:
        fields = {"intr_pin": intr_pin, "intr_pin_value": intr_pin_value}
        self._validate_fields("intr_pins_cg", fields)
        previous = self._last_interrupt_pin.get(intr_pin)
        record = self._record("intr_pins_cg", fields)
        record["previous_pin_value"] = previous
        record["observed_transition"] = (
            [previous, intr_pin_value] if previous is not None else None
        )
        self._last_interrupt_pin[intr_pin] = intr_pin_value
        return record

    def sample_resets(self, *, resets: int) -> dict[str, Any]:
        fields = {"resets": resets}
        self._validate_fields("resets_cg", fields)
        previous = self._reset_history[-1] if self._reset_history else None
        self._reset_history.append(resets)
        record = self._record("resets_cg", fields)
        record["previous_reset_state"] = previous
        record["reset_history"] = list(self._reset_history[-4:])

        if len(self._reset_history) >= 4:
            observed = self._reset_history[-4:]
            encodings = [f"{state:02b}" for state in observed]
            reset_bins = {
                ("01", "00", "10", "11"): "rst1_start_first_end_first",
                ("10", "00", "01", "11"): "rst1_start_last_end_last",
                ("01", "00", "01", "11"): "rst1_start_first_end_last",
                ("10", "00", "10", "11"): "rst1_start_last_end_first",
            }
            bin_name = reset_bins.get(tuple(encodings))
            if bin_name is not None:
                identity = f"resets_cg.resets_trans.{bin_name}"
                self._resolved_explicit_hits[identity] += 1
                record["resolved_sequence_bin"] = identity
        return record

    def to_dict(self) -> dict[str, Any]:
        coverage_status = (
            "SAMPLE_TRACE_WITH_COUNT_EVENTS_CANONICAL_IDENTITIES_AVAILABLE_VALUE_PARTITIONS_UNMAPPED"
            if self.schema["schema_id"] == "aon_timer_uvm_source_trace_v2"
            else "SAMPLE_TRACE_ONLY_CANONICAL_IDENTITIES_AVAILABLE_VALUE_PARTITIONS_UNMAPPED"
        )
        return {
            "schema_id": self.schema["schema_id"],
            "source_revision": SOURCE_REVISION,
            "run_id": self.run_id,
            "testcase": self.testcase,
            "seed": self.seed,
            "coverage_status": coverage_status,
            "canonical_bin_count": None,
            "canonical_bin_vector": None,
            "canonical_bin_identity_count": self.bin_catalog["canonical_bin_count"],
            "canonical_bin_identity_list_sha256": self.bin_catalog[
                "canonical_bin_ids_sha256"
            ],
            "sample_count": len(self.samples),
            "sample_counts_by_covergroup": dict(sorted(self._sample_counts.items())),
            "resolved_explicit_bin_hits": dict(sorted(self._resolved_explicit_hits.items())),
            "resolved_canonical_bin_identity_hit_counts": dict(
                sorted(self._canonical_identity_hits.items())
            ),
            "samples": self.samples,
        }

    def write_json(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
