"""Regression for measured native event behavior and conservative repaired-variant gates."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.pinned_sampling_fixed_adapter import PinnedSamplingFixedAdapterV1
from tools.stage10_sample_fix.audit import audit_evidence, bounded_match
from tools.stage10_full_simulation_preflight import build_preflight, DEFAULT_SAMPLE_FIX_AUDIT

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence/stage10_sample_fix/2026-11-16-v1"


class PinnedSamplingFixTests(unittest.TestCase):
    def test_source_local_regwen_stays_distinct_from_ral_reset_value(self):
        adapter = PinnedSamplingFixedAdapterV1("regwen", "test", 1)
        self.assertEqual(adapter.config["wdog_regwen"], 0)
        adapter.on_write_address(0x18, 1)
        self.assertEqual(adapter.config["wdog_regwen"], 1)
        adapter.on_write_address(0x18, 0)
        adapter.on_write_address(0x18, 1)
        self.assertEqual(adapter.config["wdog_regwen"], 0)

    def test_count_and_expiry_have_one_sample_with_expiry_state(self):
        adapter = PinnedSamplingFixedAdapterV1("expiry", "test", 1)
        adapter.config["wkup_thold"] = 3
        adapter.wkup_enabled = 1
        for edge in range(1, 9):
            adapter.sample_aon_edge(edge, 0)
        samples = adapter.trace.samples
        self.assertEqual(len(samples), 4)
        self.assertEqual(samples[-1]["producer_events"], ["count", "expiry"])
        self.assertEqual(samples[-1]["fields"]["wkup_int"], 1)

    def test_native_probes_and_independent_three_case_trace_agree(self):
        report = audit_evidence(EVIDENCE)
        self.assertEqual(report["event_probe"]["property_wait_count"], 1)
        self.assertEqual(report["event_probe"]["named_event_wait_count"], 5)
        self.assertEqual(report["fork_probe"]["original_count"], 10)
        self.assertEqual(report["fork_probe"]["isolated_count"], 5)
        self.assertTrue(report["fixed_reference_short_cases_match"])
        self.assertEqual([c["uvm_sample_count_in_body"] for c in report["cases"]], [22, 30, 30])
        self.assertFalse(report["original_reference_parity_verified"])
        self.assertFalse(report["complete_parity_verified"])

    def test_matching_counts_do_not_hide_value_timing_or_duplicate_errors(self):
        cases = audit_evidence(EVIDENCE)["cases"]
        for error in ("rtl", "duplicates", "tuples"):
            changed = copy.deepcopy(cases)
            if error == "rtl":
                changed[0]["rtl_counters_and_output_pins_at_aon_edges_equal"] = False
            elif error == "duplicates":
                changed[0]["producer_events_are_unique"] = False
            else:
                next(iter(changed[0]["samples"]["groups"].values()))["ordered_tuples_and_times_equal"] = False
            self.assertFalse(bounded_match(changed))

    def test_fix_does_not_clear_full_gate(self):
        report = build_preflight()
        self.assertTrue(report["checks"]["fixed_reference_three_short_cases_match"])
        self.assertEqual(report["summary"]["fixed_reference_actual_sample_body_count"], 82)
        self.assertEqual(report["summary"]["fixed_adapter_sample_body_count"], 82)
        self.assertEqual(report["full_simulation_start_gate"], "BLOCKED")
        self.assertFalse(report["full_simulation_started"])
        self.assertEqual(len(report["blockers"]), 5)

    def test_rehashed_fixed_variant_cannot_be_promoted_to_original_parity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "copy"
            shutil.copytree(EVIDENCE, root)
            path = root / "audit.json"
            payload = json.loads(path.read_text())
            payload["original_reference_parity_verified"] = True
            path.write_text(json.dumps(payload))
            path.with_suffix(".json.sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest() + "  audit.json\n")
            with self.assertRaisesRegex(ValueError, "does not replay from captured"):
                build_preflight(sample_fix_audit_path=path)


if __name__ == "__main__":
    unittest.main()
