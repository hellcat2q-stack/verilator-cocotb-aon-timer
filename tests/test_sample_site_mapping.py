import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from tools.audit_sample_site_mapping import _trace_files, build_audit


class SampleSiteMappingAuditTests(unittest.TestCase):
    def test_extra_broken_evidence_cannot_leave_a_valid_corpus_passing(self):
        root = Path(__file__).resolve().parents[1]
        pinned_paths = _trace_files(root / "evidence")
        template = json.loads(pinned_paths[0].read_text(encoding="utf-8"))
        cases = {
            "invalid_json": "{invalid",
            "wrong_revision": json.dumps({**template, "source_revision": "unrelated-revision"}),
            "wrong_schema": json.dumps({**template, "schema_id": "unknown-schema"}),
            "malformed_sample": json.dumps({**template, "samples": [None], "sample_count": 1}),
            "unknown_group": json.dumps({**template, "samples": [{"covergroup": "unknown"}],
                                         "sample_count": 1, "sample_counts_by_covergroup": {"unknown": 1}}),
        }
        for name, data in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_dir:
                extra = Path(temp_dir) / "extra.json"
                extra.write_text(data, encoding="utf-8")
                with patch("tools.audit_sample_site_mapping._trace_files", return_value=pinned_paths + [extra]):
                    report = build_audit()
                self.assertFalse(report["aon_capture_protocol_complete"])

    def test_unexpected_event_and_nonobject_cross_fail_structural_checks(self):
        root = Path(__file__).resolve().parents[1]
        pinned_paths = _trace_files(root / "evidence")
        template = next(json.loads(path.read_text(encoding="utf-8")) for path in pinned_paths
                        if '"intr_test_cg"' in path.read_text(encoding="utf-8"))
        source = next(sample for sample in template["samples"] if sample["covergroup"] == "intr_test_cg")
        for changed_sample in (
            {**source, "capture_event": "invented-event"},
            {**source, "same_sample_cross_observations": {
                name: None for name in source["same_sample_cross_observations"]}},
        ):
            with self.subTest(sample=changed_sample), tempfile.TemporaryDirectory() as temp_dir:
                extra = Path(temp_dir) / "extra.json"
                extra.write_text(json.dumps({**template, "samples": [changed_sample], "sample_count": 1,
                                             "sample_counts_by_covergroup": {"intr_test_cg": 1}}), encoding="utf-8")
                with patch("tools.audit_sample_site_mapping._trace_files", return_value=pinned_paths + [extra]):
                    report = build_audit()
                self.assertFalse(report["aon_capture_protocol_complete"])
                group = next(row for row in report["groups"] if row["covergroup"] == "intr_test_cg")
                self.assertFalse(group["structural_checks_passed"])

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
