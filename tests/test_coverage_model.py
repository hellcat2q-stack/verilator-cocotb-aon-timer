import unittest
import csv
import hashlib
import json
import tempfile
from pathlib import Path

from tools.coverage_model import CoverageTrace, load_bin_catalog, load_schema
from tools.import_bin_catalog import extract_bin_ids


class CoverageTraceTests(unittest.TestCase):
    def setUp(self):
        self.trace = CoverageTrace("unit-run-0", "coverage_model_unit", 17)

    def test_catalog_importer_extracts_only_unique_header_identities(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "matrix.csv"
            manifest_path = root / "manifest.json"
            header = [f"meta_{index}" for index in range(13)] + [
                "report_id",
                "scope||variable||cp_a||name:a||0",
                "scope||cross||cp_b||name:b||0",
            ]
            with csv_path.open("w", encoding="utf-8", newline="") as stream:
                csv.writer(stream).writerow(header)
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema": "aon-timer-stage06-bin-manifest-v1",
                        "bin_count": 2,
                        "bin_key_format": "group::variable_or_cross::item::bin_name",
                        "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )

            bin_ids, source = extract_bin_ids(csv_path, manifest_path)

        self.assertEqual(bin_ids, header[14:])
        self.assertEqual(source["manifest"]["bin_count"], 2)

    def test_catalog_importer_rejects_csv_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "matrix.csv"
            manifest_path = root / "manifest.json"
            with csv_path.open("w", encoding="utf-8", newline="") as stream:
                csv.writer(stream).writerow([f"meta_{i}" for i in range(13)] + ["report_id", "bin"])
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema": "aon-timer-stage06-bin-manifest-v1",
                        "bin_count": 1,
                        "bin_key_format": "group::variable_or_cross::item::bin_name",
                        "csv_sha256": "0" * 64,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "SHA-256"):
                extract_bin_ids(csv_path, manifest_path)

    def test_timer_cfg_preserves_endpoints_and_array_membership(self):
        sample = self.trace.sample_timer_cfg(
            prescale=0,
            bark_thold=0xFFFFFFFF,
            bite_thold=1,
            wkup_thold=0xFFFFFFFFFFFFFFFF,
            wdog_regwen=1,
            pause_in_sleep=0,
            wkup_cause=0,
        )
        self.assertIn("timer_cfg_cg.prescale_cp.prescale_0", sample["resolved_explicit_bin_memberships"])
        self.assertIn("timer_cfg_cg.bark_thold_cp.bark_max", sample["resolved_explicit_bin_memberships"])
        self.assertIn("timer_cfg_cg.wkup_thold_cp.wkup_max", sample["resolved_explicit_bin_memberships"])
        self.assertIn("timer_cfg_cg.bark_thold_cp.bark[]", sample["unpartitioned_array_declarations"])
        self.assertIn(
            "aon_timer_env_pkg::aon_timer_env_cov::timer_cfg_cg||variable||bark_thold_cp||name:bark_max||0",
            sample["resolved_canonical_bin_identity_hits"],
        )
        self.assertEqual(sample["fields"]["wkup_thold"], 0xFFFFFFFFFFFFFFFF)

    def test_cross_observation_uses_values_from_one_sample(self):
        first = self.trace.sample_wakeup_timer_thold_hit(
            wkup_int=0, wkup_thold=7, wkup_count=6
        )
        second = self.trace.sample_wakeup_timer_thold_hit(
            wkup_int=1, wkup_thold=12, wkup_count=12
        )
        cross_name = "wkup_thold_cpXwkup_int_cp"
        self.assertEqual(first["same_sample_cross_observations"][cross_name], {"wkup_thold": 7, "wkup_int": 0})
        self.assertEqual(second["same_sample_cross_observations"][cross_name], {"wkup_thold": 12, "wkup_int": 1})
        self.assertEqual(len(self.trace.samples), 2)

    def test_watchdog_crosses_preserve_each_call_as_a_separate_tuple(self):
        bark = self.trace.sample_watchdog_bark_thold_hit(
            wdog_bark_int=1, wdog_thold=12, wdog_count=12
        )
        bite = self.trace.sample_watchdog_bite_thold_hit(
            wdog_bite_rst=0, wdog_thold=20, wdog_count=19
        )
        self.assertEqual(
            bark["same_sample_cross_observations"]["wdog_thold_cpXwdog_bark_rst"],
            {"wdog_thold": 12, "wdog_bark_int": 1},
        )
        self.assertEqual(
            bite["same_sample_cross_observations"]["wdog_thold_cpXwdog_bite_rst"],
            {"wdog_thold": 20, "wdog_bite_rst": 0},
        )

    def test_interrupt_read_sample_has_all_cross_members(self):
        sample = self.trace.sample_interrupt(intr=1, intr_en=1, intr_state=1)
        self.assertEqual(
            sample["same_sample_cross_observations"][
                "cross_cp_intr_cp_intr_en_cp_intr_state"
            ],
            {"intr": 1, "intr_en": 1, "intr_state": 1},
        )

    def test_bit_width_boundaries_are_checked(self):
        with self.assertRaises(ValueError):
            self.trace.sample_watchdog_bark_thold_hit(
                wdog_bark_int=1, wdog_thold=1 << 32, wdog_count=0
            )
        with self.assertRaises(ValueError):
            self.trace.sample_interrupt(intr=2, intr_en=0, intr_state=0)

    def test_timer_sample_scheduler_matches_start_count_expiry_and_restart(self):
        from tools.coverage_model import TimerSampleScheduler

        scheduler = TimerSampleScheduler(startup_cycles=4)
        self.assertEqual(
            [scheduler.tick(enabled=True, target_cycles=2) for _ in range(4)],
            [[], [], [], []],
        )
        self.assertEqual(scheduler.tick(enabled=True, target_cycles=2), ["count"])
        self.assertEqual(
            scheduler.tick(enabled=True, target_cycles=2, post_expiry_cycles=1),
            ["count", "expiry"],
        )
        self.assertEqual(scheduler.tick(enabled=True, target_cycles=2), [])
        for _ in range(4):
            self.assertEqual(scheduler.tick(enabled=True, target_cycles=2), [])
        self.assertEqual(scheduler.tick(enabled=True, target_cycles=2), ["count"])

    def test_timer_sample_scheduler_emits_expiry_for_zero_countdown(self):
        from tools.coverage_model import TimerSampleScheduler

        scheduler = TimerSampleScheduler(startup_cycles=2)
        self.assertEqual(scheduler.tick(enabled=True, target_cycles=0), [])
        self.assertEqual(scheduler.tick(enabled=True, target_cycles=0), ["expiry"])

    def test_timer_sample_scheduler_resets_and_counts_on_first_edge_after_update(self):
        from tools.coverage_model import TimerSampleScheduler

        scheduler = TimerSampleScheduler(startup_cycles=0)
        self.assertEqual(scheduler.tick(enabled=True, target_cycles=4), ["count"])
        self.assertEqual(
            scheduler.tick(enabled=True, target_cycles=2, update_due=True), ["count"]
        )
        self.assertEqual(scheduler.tick(enabled=True, target_cycles=2), ["count", "expiry"])

    def test_timer_sample_scheduler_zero_target_update_emits_expiry_only(self):
        from tools.coverage_model import TimerSampleScheduler

        scheduler = TimerSampleScheduler(startup_cycles=0)
        self.assertEqual(scheduler.tick(enabled=True, target_cycles=4), ["count"])
        self.assertEqual(scheduler.tick(enabled=True, target_cycles=0, update_due=True), ["expiry"])

    def test_interrupt_pin_transition_history_is_per_pin(self):
        first = self.trace.sample_interrupt_pin(intr_pin=0, intr_pin_value=0)
        second = self.trace.sample_interrupt_pin(intr_pin=1, intr_pin_value=1)
        third = self.trace.sample_interrupt_pin(intr_pin=0, intr_pin_value=1)
        self.assertIsNone(first["observed_transition"])
        self.assertIsNone(second["observed_transition"])
        self.assertEqual(third["observed_transition"], [0, 1])

    def test_illegal_interrupt_test_cross_is_recorded(self):
        sample = self.trace.sample_interrupt_test(
            intr=0, intr_test=1, intr_en=1, intr_state=0
        )
        self.assertTrue(sample["illegal_cross_condition"])

    def test_reset_transition_bin_requires_four_consecutive_states(self):
        samples = [
            self.trace.sample_resets(resets=value)
            for value in (0b01, 0b00, 0b10, 0b11)
        ]
        self.assertEqual(
            samples[-1]["resolved_sequence_bin"],
            "resets_cg.resets_trans.rst1_start_first_end_first",
        )

    def test_canonical_vector_is_not_fabricated(self):
        record = self.trace.to_dict()
        self.assertIsNone(record["canonical_bin_count"])
        self.assertIsNone(record["canonical_bin_vector"])
        self.assertEqual(record["canonical_bin_identity_count"], 4507)
        self.assertEqual(
            record["coverage_status"],
            "SAMPLE_TRACE_WITH_COUNT_EVENTS_CANONICAL_IDENTITIES_AVAILABLE_VALUE_PARTITIONS_UNMAPPED",
        )

    def test_canonical_bin_catalog_has_all_unique_reference_identities(self):
        catalog, bin_ids = load_bin_catalog()
        self.assertEqual(len(bin_ids), 4507)
        self.assertEqual(len(set(bin_ids)), 4507)
        self.assertEqual(catalog["aon_timer_scope_bin_count"], 4279)
        self.assertEqual(catalog["shared_or_other_scope_bin_count"], 228)
        self.assertTrue(catalog["source"]["matrix_csv_sha256"])

    def test_schema_carries_source_revision_and_identity_catalog(self):
        schema = load_schema()
        self.assertEqual(schema["reference_counts"]["canonical_bins"], 4507)
        self.assertTrue(schema["reference_counts"]["identity_catalog_available"])
        self.assertEqual(schema["environment_parameters"]["num_interrupts"], 2)
        group_names = {group["name"] for group in schema["groups"]}
        self.assertIn("timer_cfg_cg", group_names)
        self.assertIn("intr_test_cg", group_names)


if __name__ == "__main__":
    unittest.main()
