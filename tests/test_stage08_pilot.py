"""Pilot checks cover actual failure handling and feedback-dependent choices."""

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from tools.run_stage08_pilot import collect_attempt, export_results_xml, input_sha256, run_command, select_action
from tools.audit_stage08_pilot import audit

RECORDED_PILOT = Path(__file__).resolve().parents[1] / "evidence/stage08_online_pilot/2026-11-14-v3"


class Stage08PilotTests(unittest.TestCase):
    def test_warmup_uses_untried_arms_and_counts_failed_attempts(self):
        self.assertEqual(select_action(["a", "b"], [], 0.01), ("a", "warmup", {}))
        self.assertEqual(select_action(["a", "b"], [
            {"testcase": "a", "reward": 0.0, "result": "FAIL"}], 0.01)[0], "b")

    def test_equal_pulls_use_previous_feedback(self):
        history = [{"testcase": "a", "reward": 0.0}, {"testcase": "b", "reward": 0.1}]
        self.assertEqual(select_action(["a", "b"], history)[0], "b")
        history[0]["reward"], history[1]["reward"] = 0.1, 0.0
        self.assertEqual(select_action(["a", "b"], history)[0], "a")

    def test_exploration_recovers_less_tried_arm(self):
        history = [{"testcase": "a", "reward": 0.0}] * 10 + [{"testcase": "b", "reward": 0.0}]
        self.assertEqual(select_action(["a", "b"], history)[0], "b")

    def test_repository_hash_survives_crlf_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.py"
            path.write_bytes(b"one\r\ntwo\r\n")
            digest = input_sha256(path)
            path.write_bytes(b"one\ntwo\n")
            self.assertEqual(digest, input_sha256(path))

    def test_failed_launch_is_retained_as_budget_consuming_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, timed_out, _ = run_command([str(root / "missing-simulator")], root,
                                             os.environ.copy(), root / "run.log", 1)
            self.assertEqual(code, 127)
            self.assertFalse(timed_out)
            self.assertIn("launch failed", (root / "run.log").read_text())

    def test_success_exit_without_xml_and_trace_is_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "coverage-traces").mkdir()
            passed, cases, _, _ = collect_attempt(root, "run", "a", 1, "revision", "schema", 0)
            self.assertFalse(passed)
            self.assertEqual(cases, [])

    def test_timeout_is_retained_as_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, timed_out, elapsed = run_command(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                root, os.environ.copy(), root / "run.log", 0.05)
            self.assertEqual(code, 124)
            self.assertTrue(timed_out)
            self.assertLess(elapsed, 5)

    def test_public_xml_preserves_outcome_and_redacts_local_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = '<testsuite><testcase name="a" file="/private/project/tools/test_sequences.py" sim_time_ns="10"><failure>/private/project/data</failure></testcase></testsuite>'
            (root / "raw.xml").write_text(original)
            export_results_xml(root / "raw.xml", root / "public.xml", (("/private/project", "[project]"),))
            public = (root / "public.xml").read_text()
            self.assertIn('file="tools/test_sequences.py"', public)
            self.assertIn("<failure>[project]/data</failure>", public)
            self.assertNotIn("/private", public)
            self.assertEqual((root / "raw.xml").read_text(), original)

    def test_cross_run_trace_and_wrong_testcase_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            traces = root / "coverage-traces"
            traces.mkdir()
            trace = {
                "run_id": "previous-run", "testcase": "b", "seed": 1,
                "source_revision": "revision", "schema_id": "schema",
                "coverage_status": "PARTIAL", "canonical_bin_vector": None,
                "sample_count": 0, "samples": [], "sample_counts_by_covergroup": {},
                "resolved_canonical_bin_identity_hit_counts": {},
            }
            (traces / "b.json").write_text(json.dumps(trace))
            (root / "results.xml").write_text('<testsuite><testcase name="b" sim_time_ns="1"/></testsuite>')
            passed, _, _, summary = collect_attempt(root, "new-run", "a", 1, "revision", "schema", 0)
            self.assertFalse(passed)
            self.assertFalse(summary["validated"])

    def test_previous_simulation_evidence_is_rejected_after_input_change(self):
        result = audit(RECORDED_PILOT)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(error.startswith("input changed:") for error in result["errors"]))

    def test_modified_reward_is_rejected_by_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "evidence"
            shutil.copytree(RECORDED_PILOT, target)
            summary_path = target / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["attempts"][0]["reward"] = 1
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            result = audit(target)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("attempt 1: reward", result["errors"])

    def test_modified_simulator_result_is_rejected_by_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "evidence"
            shutil.copytree(RECORDED_PILOT, target)
            xml_path = target / "attempt-001/results.xml"
            xml_path.write_text(xml_path.read_text().replace(
                'name="aon_timer_smoke_sequence"', 'name="unrelated_testcase"'))
            result = audit(target)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("attempt 1: actual simulation outcome", result["errors"])


if __name__ == "__main__":
    unittest.main()
