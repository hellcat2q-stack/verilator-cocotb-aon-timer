from __future__ import annotations

import unittest

from tools.stage08_preflight import audit_preconditions


class Stage08PreflightTests(unittest.TestCase):
    def test_complete_exact_prerequisites_allow_readiness(self):
        canonical = ["pkg::cg||variable||cp||name:value||0"]
        catalog = {
            "definition_count": 1,
            "aon_timer_definition_count": 1,
            "shared_or_other_definition_count": 0,
            "definitions": [{"scope": "pkg::cg", "kind": "variable", "item": "cp", "bin_name": "value"}],
            "auto_bin_partition_audit": [{"complete_non_overlapping_partition": True}],
            "cross_bin_partition_audit": [{"complete_cartesian_product": True}],
        }
        matrix = {
            "matrix_status": "COMPLETE_EXACT",
            "canonical_bin_count_observed": 1,
            "union": {"unknown_bin_count": 0},
        }
        scheduler = {"allowed_to_schedule": True}
        sample_sites = {
            "sample_site_mapping": {"status": "COMPLETE", "complete": True, "unmapped": []}
        }

        result = audit_preconditions(catalog, canonical, matrix, scheduler, sample_sites)

        self.assertTrue(result["ready_for_online_coverage_feedback"])
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["blockers"], [])

    def test_partial_vectors_and_incomplete_mapping_keep_feedback_disabled(self):
        canonical = ["pkg::cg||variable||cp||name:value||0"]
        catalog = {
            "definition_count": 1,
            "aon_timer_definition_count": 1,
            "shared_or_other_definition_count": 0,
            "definitions": [
                {
                    "scope": "pkg::cg",
                    "kind": "variable",
                    "item": "cp",
                    "bin_name": "other",
                }
            ],
            "auto_bin_partition_audit": [],
            "cross_bin_partition_audit": [],
        }
        matrix = {
            "matrix_status": "PARTIAL_OR_UNAVAILABLE",
            "canonical_bin_count_observed": 1,
            "union": {"unknown_bin_count": 1},
        }
        scheduler = {"allowed_to_schedule": False}
        sample_sites = {
            "sample_site_mapping": {
                "status": "PARTIAL_CAPTURE_ONLY",
                "complete": False,
                "unmapped": ["count events", "conditional reset", "shared identities"],
            }
        }

        result = audit_preconditions(catalog, canonical, matrix, scheduler, sample_sites)

        self.assertFalse(result["ready_for_online_coverage_feedback"])
        self.assertIn("Stage 06 does not contain a complete exact run matrix.", result["blockers"])
        self.assertIn("Stage 07 has not enabled coverage-based scheduling.", result["blockers"])
        self.assertEqual(result["unmapped_sample_site_count"], 3)
        self.assertIn("sample or identity mapping item(s) remain unresolved", result["blockers"][-1])

    def test_missing_or_inconsistent_sample_mapping_fails_closed(self):
        canonical = ["pkg::cg||variable||cp||name:value||0"]
        catalog = {
            "definition_count": 1,
            "aon_timer_definition_count": 1,
            "shared_or_other_definition_count": 0,
            "definitions": [{"scope": "pkg::cg", "kind": "variable", "item": "cp", "bin_name": "value"}],
            "auto_bin_partition_audit": [{"complete_non_overlapping_partition": True}],
            "cross_bin_partition_audit": [{"complete_cartesian_product": True}],
        }
        matrix = {"matrix_status": "COMPLETE_EXACT", "canonical_bin_count_observed": 1, "union": {"unknown_bin_count": 0}}
        scheduler = {"allowed_to_schedule": True}

        for mapping in (
            {},
            {"sample_site_mapping": None},
            {"sample_site_mapping": {"status": "COMPLETE", "complete": True, "unmapped": ["one missing site"]}},
            {"sample_site_mapping": {"status": "COMPLETE", "complete": True, "unmapped": None}},
        ):
            with self.subTest(mapping=mapping):
                result = audit_preconditions(catalog, canonical, matrix, scheduler, mapping)
                self.assertFalse(result["ready_for_online_coverage_feedback"])
                self.assertFalse(result["sample_sites_complete"])


if __name__ == "__main__":
    unittest.main()
