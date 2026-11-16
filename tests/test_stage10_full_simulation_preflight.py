import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.stage10_full_simulation_preflight import (
    DEFAULT_CLASSIFICATION,
    DEFAULT_LEGACY_VECTOR_HEADER_AUDIT,
    DEFAULT_UVM_TIMING_SHAPE_AUDIT,
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
        self.assertTrue(report["checks"]["array_vcs_python_boundary_parity_verified"])
        self.assertEqual(report["summary"]["array_vcs_python_boundary_probes_passed"], 636)
        self.assertTrue(report["checks"]["stage09_replay_audit_is_288_of_288"])
        self.assertTrue(report["checks"]["identity_bridge_audit_is_complete_as_audit"])
        self.assertEqual(report["summary"]["identity_bridge_deterministic_candidate_count"], 2102)
        self.assertEqual(report["summary"]["identity_bridge_ambiguous_candidate_count"], 2064)
        self.assertFalse(report["checks"]["stage06_exact_matrix_is_available"])
        self.assertFalse(report["checks"]["legacy_identity_bridge_is_complete"])
        self.assertTrue(report["checks"]["aon_capture_protocol_is_complete"])
        self.assertFalse(report["checks"]["shared_scope_mapping_is_complete"])
        self.assertTrue(report["checks"]["count_event_cadence_model_is_present"])
        self.assertTrue(report["checks"]["uvm_control_event_shape_diagnostic_is_replayed"])
        self.assertFalse(report["checks"]["independent_uvm_vcs_timing_comparison_complete"])
        self.assertEqual(report["summary"]["uvm_control_message_count"], 21)
        self.assertFalse(report["summary"]["uvm_build_source_revision_verified"])
        self.assertFalse(report["summary"]["uvm_build_tree_scoreboard_matches_pinned"])
        self.assertEqual(report["summary"]["uvm_control_event_run_count"], 4)
        self.assertTrue(report["checks"]["legacy_vector_header_audit_is_current_and_diagnostic_only"])
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

    def test_candidate_promotion_in_diagnostic_is_rejected_even_with_valid_sidecar(self):
        import hashlib

        with tempfile.TemporaryDirectory() as temp_dir:
            copied = Path(temp_dir) / "audit.json"
            report = json.loads(DEFAULT_LEGACY_VECTOR_HEADER_AUDIT.read_text(encoding="utf-8"))
            report["promotion_allowed"] = True
            copied.write_text(json.dumps(report), encoding="utf-8")
            copied.with_suffix(".json.sha256").write_text(
                f"{hashlib.sha256(copied.read_bytes()).hexdigest()}  audit.json\n", encoding="ascii"
            )
            with self.assertRaisesRegex(ValueError, "diagnostic-only"):
                build_preflight(legacy_vector_header_audit_path=copied)

    def test_require_ready_exits_nonzero_and_writes_blocker_report(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "preflight.json"
            result = subprocess.run(
                [sys.executable, str(root / "tools/stage10_full_simulation_preflight.py"),
                 "--require-ready", "--output", str(output)],
                cwd=root, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["full_simulation_start_gate"], "BLOCKED")
            self.assertFalse(report["full_simulation_started"])

    def test_shape_evidence_cannot_be_promoted_with_a_rehashed_report(self):
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "timing"
            shutil.copytree(DEFAULT_UVM_TIMING_SHAPE_AUDIT.parent, copied)
            path = copied / "audit.json"
            report = json.loads(path.read_text(encoding="utf-8"))
            report["independent_uvm_vcs_timing_comparison_complete"] = True
            path.write_text(json.dumps(report), encoding="utf-8")
            Path(str(path) + ".sha256").write_text(
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}  audit.json\n", encoding="ascii"
            )
            with self.assertRaisesRegex(ValueError, "does not replay from diagnostic"):
                build_preflight(uvm_timing_shape_audit_path=path)


if __name__ == "__main__":
    unittest.main()
