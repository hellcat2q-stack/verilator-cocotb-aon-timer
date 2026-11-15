import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.classify_source_definitions import (
    CATALOG_PATH,
    SourceDefinitionClassifier,
    load_catalog,
)


class SourceDefinitionClassifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog, cls.catalog_hash = load_catalog(CATALOG_PATH)
        cls.classifier = SourceDefinitionClassifier(cls.catalog)

    def test_named_timer_bin_is_exact_source_definition_match(self):
        sample = {
            "sample_index": 0,
            "covergroup": "timer_cfg_cg",
            "fields": {"prescale": 0, "bark_thold": 0, "bite_thold": 0,
                        "wkup_thold": 0, "wdog_regwen": 1,
                        "pause_in_sleep": 0, "wkup_cause": 0},
            "resolved_explicit_bin_memberships": ["timer_cfg_cg.prescale_cp.prescale_0"],
            "same_sample_cross_observations": {},
        }
        result = self.classifier.classify_sample(sample)
        ids = {item["definition_id"] for item in result["variable_matches"]}
        self.assertIn(
            "aon_timer_env_pkg::aon_timer_env_cov::timer_cfg_cg||variable||prescale_cp||prescale_0",
            ids,
        )
        self.assertIn(
            "aon_timer_env_pkg::aon_timer_env_cov::timer_cfg_cg||variable||wdog_regwen_cp||auto[1]",
            ids,
        )
        self.assertIn(
            "aon_timer_env_pkg::aon_timer_env_cov::timer_cfg_cg||variable||pause_in_sleep_cp||auto[0]",
            ids,
        )
        self.assertTrue(any(item["match_kind"] == "SOURCE_DEFINITION_EXACT_MATCH"
                            for item in result["variable_matches"]))

    def test_timer_array_is_reported_unresolved_and_never_guessed(self):
        sample = {
            "covergroup": "timer_cfg_cg",
            "fields": {"prescale": 1, "bark_thold": 1, "bite_thold": 1,
                        "wkup_thold": 1, "wdog_regwen": 0,
                        "pause_in_sleep": 0, "wkup_cause": 0},
            "resolved_explicit_bin_memberships": [],
            "same_sample_cross_observations": {},
        }
        result = self.classifier.classify_sample(sample)
        self.assertEqual(len(result["array_partition_unresolved"]), 4)
        self.assertFalse(any("prescale[" in item["definition_id"]
                             for item in result["variable_matches"]))
        self.assertEqual(result["status"], "SOURCE_DEFINITION_PARTIAL_ARRAY_UNRESOLVED")

    def test_count_event_range_and_cross_are_matched_from_same_sample(self):
        sample = {
            "covergroup": "watchdog_timer_bark_thold_hit_cg",
            "fields": {"wdog_bark_int": 1, "wdog_thold": 12, "wdog_count": 12},
            "resolved_explicit_bin_memberships": [],
            "same_sample_cross_observations": {
                "wdog_thold_cpXwdog_bark_rst": {"wdog_thold": 12, "wdog_bark_int": 1}
            },
        }
        result = self.classifier.classify_sample(sample)
        self.assertEqual(len(result["cross_matches"]), 1)
        self.assertEqual(len([item for item in result["variable_matches"]
                              if item["match_kind"] == "SOURCE_DEFINITION_VALUE_RANGE_MATCH"]), 2)
        self.assertTrue(result["cross_matches"][0]["definition_id"].endswith("wdog_bark_int=auto[1]"))

    def test_interrupt_scope_uses_shape_catalog_and_cross_stays_unresolved(self):
        sample = {
            "covergroup": "intr_test_cg",
            "fields": {"intr": 1, "intr_test": 1, "intr_en": 0, "intr_state": 1},
            "resolved_explicit_bin_memberships": [],
            "same_sample_cross_observations": {
                "cross_cp_intr_cp_intr_test_cp_intr_en_cp_intr_state": {
                    "intr": 1, "intr_test": 1, "intr_en": 0, "intr_state": 1
                }
            },
        }
        result = self.classifier.classify_sample(sample)
        self.assertEqual(result["source_scope"],
                         "cip_base_pkg::intr_test_cg::SHAPE{(num_interrupts - 1)=1}")
        self.assertEqual(len(result["variable_matches"]), 4)
        self.assertTrue(any(item["reason"] == "INTERRUPT_CROSS_SCHEMA_UNRESOLVED"
                            for item in result["unresolved"]))

    def test_missing_required_cross_sample_is_reported(self):
        sample = {
            "covergroup": "intr_cg",
            "fields": {"intr": 0, "intr_en": 1, "intr_state": 0},
            "resolved_explicit_bin_memberships": [],
            "same_sample_cross_observations": {},
        }
        result = self.classifier.classify_sample(sample)
        self.assertTrue(any(item["reason"] == "MISSING_SAME_SAMPLE_CROSS_OBSERVATION"
                            for item in result["unresolved"]))

    def test_malformed_membership_and_cross_containers_remain_unresolved(self):
        sample = {
            "covergroup": "timer_cfg_cg",
            "fields": None,
            "resolved_explicit_bin_memberships": {},
            "same_sample_cross_observations": None,
        }
        result = self.classifier.classify_sample(sample)
        reasons = {item.get("reason") for item in result["unresolved"]}
        self.assertIn("MALFORMED_EXPLICIT_MEMBERSHIPS", reasons)
        self.assertIn("MALFORMED_CROSS_OBSERVATIONS", reasons)

    def test_pin_transition_uses_transition_definition(self):
        sample = {
            "covergroup": "intr_pins_cg",
            "fields": {"intr_pin": 0, "intr_pin_value": 1},
            "observed_transition": [0, 1],
            "resolved_explicit_bin_memberships": [],
            "same_sample_cross_observations": {},
        }
        result = self.classifier.classify_sample(sample)
        names = {item["bin_name"] for item in result["variable_matches"]}
        self.assertIn("transitions[0x0=>0x1]", names)

    def test_trace_result_keeps_full_coverage_unreportable(self):
        trace = {
            "schema_id": "aon_timer_uvm_source_trace_v2",
            "source_revision": "9f20940d494a223cc950a5b98f748fb28109d458",
            "run_id": "unit", "testcase": "classifier", "seed": 1,
            "samples": [{
                "sample_index": 0, "covergroup": "wake_up_timer_thold_hit_cg",
                "fields": {"wkup_int": 1, "wkup_thold": 12, "wkup_count": 12},
                "resolved_explicit_bin_memberships": [],
                "same_sample_cross_observations": {
                    "wkup_thold_cpXwkup_int_cp": {"wkup_thold": 12, "wkup_int": 1}
                },
            }],
        }
        result = self.classifier.classify_trace(trace)
        self.assertEqual(result["summary"]["legacy_identity_credit_granted"], 0)
        self.assertIsNone(result["summary"]["full_coverage_rate_percent"])
        self.assertEqual(len(result["definition_ids_observed"]), 3)

    def test_passing_trace_tree_validates_attempt_trace_hashes(self):
        from tools.classify_source_definitions import classify_passing_trace_tree

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            trace_dir = root / "attempt-001" / "coverage-traces"
            trace_dir.mkdir(parents=True)
            trace = {
                "schema_id": "aon_timer_uvm_source_trace_v2",
                "source_revision": "9f20940d494a223cc950a5b98f748fb28109d458",
                "run_id": "run-1", "testcase": "case-1", "seed": 1, "sample_count": 0,
                "samples": [],
            }
            trace_path = trace_dir / "trace.json"
            trace_bytes = (json.dumps(trace, sort_keys=True) + "\n").encode("utf-8")
            trace_path.write_bytes(trace_bytes)
            attempt = {
                "result": "PASS", "run_id": "run-1", "testcase": "case-1",
                "exit_code": 0, "timed_out": False,
                "testcases": [{"name": "case-1", "result": "PASS"}],
                "sample_count": 0, "trace_sha256": hashlib.sha256(trace_bytes).hexdigest(),
            }
            (trace_dir.parent / "attempt.json").write_text(json.dumps(attempt), encoding="utf-8")

            report = classify_passing_trace_tree(root, expected_trace_count=1)

        self.assertEqual(report["trace_count"], 1)
        self.assertEqual(report["sample_count"], 0)
        self.assertFalse(report["coverage_accounting"]["source_definition_matches_are_coverage_credit"])

    def test_passing_trace_tree_rejects_trace_hash_mismatch(self):
        from tools.classify_source_definitions import classify_passing_trace_tree

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            trace_dir = root / "attempt-001" / "coverage-traces"
            trace_dir.mkdir(parents=True)
            trace = {"schema_id": "aon_timer_uvm_source_trace_v2",
                     "source_revision": "9f20940d494a223cc950a5b98f748fb28109d458",
                     "run_id": "run-1", "testcase": "case-1", "seed": 1,
                     "sample_count": 0, "samples": []}
            (trace_dir / "trace.json").write_text(json.dumps(trace), encoding="utf-8")
            (trace_dir.parent / "attempt.json").write_text(
                json.dumps({"result": "PASS", "run_id": "run-1", "testcase": "case-1",
                            "exit_code": 0, "timed_out": False,
                            "testcases": [{"name": "case-1", "result": "PASS"}],
                            "sample_count": 0, "trace_sha256": "0" * 64}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "trace hash mismatch"):
                classify_passing_trace_tree(root)


if __name__ == "__main__":
    unittest.main()
