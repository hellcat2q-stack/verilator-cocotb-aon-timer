import shutil
import tempfile
import unittest
from pathlib import Path

from tools.stage10_full_simulation_preflight import (
    DEFAULT_CLASSIFICATION,
    build_preflight,
)


class Stage10FullSimulationPreflightTests(unittest.TestCase):
    def test_report_confirms_simulation_is_not_ready_or_started(self):
        report = build_preflight()
        self.assertEqual(report["status"], "BLOCKED_BEFORE_FULL_SIMULATION")
        self.assertFalse(report["full_simulation_started"])
        self.assertEqual(report["full_simulation_start_gate"], "BLOCKED")
        self.assertEqual(report["coverage_credit_added"], 0)
        self.assertIsNone(report["full_coverage_rate_percent"])
        self.assertFalse(report["unknowns_are_misses"])
        self.assertTrue(report["checks"]["array_source_python_partition_audit_passed"])
        self.assertTrue(report["checks"]["stage09_replay_audit_is_288_of_288"])
        self.assertTrue(report["checks"]["identity_bridge_audit_is_complete_as_audit"])
        self.assertEqual(report["summary"]["identity_bridge_deterministic_candidate_count"], 2102)
        self.assertEqual(report["summary"]["identity_bridge_ambiguous_candidate_count"], 2064)
        self.assertFalse(report["checks"]["stage06_exact_matrix_is_available"])
        self.assertFalse(report["checks"]["legacy_identity_bridge_is_complete"])
        self.assertTrue(report["checks"]["aon_capture_protocol_is_complete"])
        self.assertFalse(report["checks"]["shared_scope_mapping_is_complete"])
        self.assertTrue(report["checks"]["count_event_cadence_model_is_present"])
        self.assertGreater(len(report["blockers"]), 0)

    def test_stale_classification_hash_sidecar_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            copied_report = Path(temp_dir) / "classification.json"
            shutil.copyfile(DEFAULT_CLASSIFICATION, copied_report)
            copied_report.with_suffix(".json.sha256").write_text(
                "0" * 64 + "  classification.json\n", encoding="ascii"
            )
            with self.assertRaisesRegex(ValueError, "SHA-256 sidecar"):
                build_preflight(classification_path=copied_report)


if __name__ == "__main__":
    unittest.main()
