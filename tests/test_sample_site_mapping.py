import unittest
from pathlib import Path

from tools.audit_sample_site_mapping import build_audit


class SampleSiteMappingAuditTests(unittest.TestCase):
    def test_pinned_trace_corpus_covers_all_aon_sites_structurally(self):
        root = Path(__file__).resolve().parents[1]
        report = build_audit(trace_root=root / "evidence")
        self.assertEqual(report["trace_file_count"], 326)
        self.assertEqual(report["valid_trace_file_count"], 326)
        self.assertEqual(report["sample_count"], 17743)
        self.assertTrue(report["aon_capture_protocol_complete"])
        self.assertEqual(report["shared_scope"]["definition_count"], 228)
        self.assertFalse(report["mapping_gates"]["shared_scope_mapping_complete"])
        self.assertFalse(report["mapping_gates"]["timing_parity_complete"])
        self.assertEqual(report["coverage_credit_granted"], 0)
        self.assertFalse(report["unknowns_are_misses"])
        self.assertEqual(report["unknown_group_sample_count"], 0)
        self.assertTrue(all(group["structural_checks_passed"] for group in report["groups"]))

    def test_count_event_metadata_is_present_but_not_uvm_vcs_parity(self):
        root = Path(__file__).resolve().parents[1]
        report = build_audit(trace_root=root / "evidence")
        timing = report["count_event_timing"]
        self.assertTrue(timing["cadence_model_present"])
        self.assertFalse(timing["independent_uvm_vcs_comparison_complete"])
        self.assertEqual(
            timing["status"],
            "MODELED_RTL_COUNTERS_NO_INDEPENDENT_UVM_VCS_PARITY",
        )


if __name__ == "__main__":
    unittest.main()
