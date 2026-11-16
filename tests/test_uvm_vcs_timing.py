import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.audit_uvm_vcs_timing import audit_evidence, audit_logs


EVIDENCE = Path(__file__).resolve().parents[1] / "evidence/stage10_uvm_vcs_timing/2026-11-16-v2"
WAKEUP = "wake_up_timer_thold_hit_cg"
BARK = "watchdog_timer_bark_thold_hit_cg"
BITE = "watchdog_timer_bite_thold_hit_cg"


class UvmVcsTimingAuditTests(unittest.TestCase):
    def test_three_groups_match_python_shape(self):
        text = "\n".join([
            "UVM_INFO @ 100 ps: (aon_timer_scoreboard.sv:289) WKUP Timer count:          1",
            "UVM_INFO @ 200 ps: (aon_timer_scoreboard.sv:289) WKUP Timer count:          2",
            "UVM_INFO @ 200 ps: (aon_timer_scoreboard.sv:292) WKUP Timer expired check for interrupts",
            "UVM_INFO @ 300 ps: (aon_timer_scoreboard.sv:368) WDOG Bark Timer count:          1",
            "UVM_INFO @ 300 ps: (aon_timer_scoreboard.sv:371) WDOG Bark Timer expired check for interrupts",
            "UVM_INFO @ 400 ps: (aon_timer_scoreboard.sv:437) WDOG Bite Timer count:          1",
            "UVM_INFO @ 400 ps: (aon_timer_scoreboard.sv:440) WDOG Bite Timer expired check for interrupts",
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vcs.log"
            path.write_text(text + "\n", encoding="utf-8")
            report = audit_logs([path])
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["count_event_shape_comparison_complete"])
        self.assertFalse(report["independent_uvm_vcs_timing_comparison_complete"])
        self.assertFalse(report["covergroup_sample_invocations_observed"])
        self.assertFalse(report["startup_delay_verified"])
        self.assertEqual(report["coverage_credit_granted"], 0)

    def test_missing_expiry_is_fail_closed(self):
        text = "UVM_INFO @ 100 ps: (aon_timer_scoreboard.sv:289) WKUP Timer count:          1\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vcs.log"
            path.write_text(text, encoding="utf-8")
            report = audit_logs([path])
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["independent_uvm_vcs_timing_comparison_complete"])

    def audit_text(self, text, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vcs.log"
            path.write_text(text + "\n", encoding="utf-8")
            return audit_logs([path], **kwargs)

    def test_reversed_or_duplicate_expiry_and_nonuniform_intervals_fail(self):
        count1 = "UVM_INFO @ 100 ps: (aon_timer_scoreboard.sv:289) WKUP Timer count: 1"
        count2 = "UVM_INFO @ 200 ps: (aon_timer_scoreboard.sv:289) WKUP Timer count: 2"
        count3 = "UVM_INFO @ 350 ps: (aon_timer_scoreboard.sv:289) WKUP Timer count: 3"
        expiry1 = "UVM_INFO @ 100 ps: (aon_timer_scoreboard.sv:292) WKUP Timer expired check for interrupts"
        expiry2 = "UVM_INFO @ 200 ps: (aon_timer_scoreboard.sv:292) WKUP Timer expired check for interrupts"
        expiry3 = "UVM_INFO @ 350 ps: (aon_timer_scoreboard.sv:292) WKUP Timer expired check for interrupts"
        for lines in ([expiry1, count1], [count1, expiry1, expiry1],
                      [count1, count3, expiry3], [count1, count2, count3, expiry3],
                      [count2, count1, expiry1], [count1, expiry2]):
            with self.subTest(lines=lines):
                self.assertEqual(self.audit_text("\n".join(lines))["status"], "FAIL")

    def test_incidental_groups_cannot_complete_comparison(self):
        text = "\n".join([
            "UVM_INFO @ 100 ps: (aon_timer_scoreboard.sv:289) WKUP Timer count: 1",
            "UVM_INFO @ 100 ps: (aon_timer_scoreboard.sv:292) WKUP Timer expired check for interrupts",
            "UVM_INFO @ 100 ps: (aon_timer_scoreboard.sv:368) WDOG Bark Timer count: 1",
            "UVM_INFO @ 100 ps: (aon_timer_scoreboard.sv:437) WDOG Bite Timer count: 1",
        ])
        report = self.audit_text(text, expected_groups={"vcs.log": WAKEUP})
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["verified_shape_groups"], [WAKEUP])
        self.assertEqual(report["runs"][0]["incidental_groups"], [BARK, BITE])
        self.assertFalse(report["count_event_shape_comparison_complete"])
        self.assertEqual(self.audit_text(text)["status"], "FAIL")

    def test_actual_scheduler_behavior_is_compared(self):
        text = "\n".join([
            "UVM_INFO @ 100 ps: (aon_timer_scoreboard.sv:289) WKUP Timer count: 1",
            "UVM_INFO @ 100 ps: (aon_timer_scoreboard.sv:292) WKUP Timer expired check for interrupts",
        ])
        with patch("tools.audit_uvm_vcs_timing.TimerSampleScheduler.tick", return_value=["count"]):
            self.assertEqual(self.audit_text(text)["status"], "FAIL")

    def test_public_evidence_replays_without_promoting_parity(self):
        report = audit_evidence(EVIDENCE)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(sum(row["event_count"] for row in report["runs"]), 21)
        self.assertTrue(report["count_event_shape_comparison_complete"])
        self.assertFalse(report["independent_uvm_vcs_timing_comparison_complete"])
        self.assertFalse(report["sample_values_compared"])
        runs = {row["log_name"]: row for row in report["runs"]}
        wakeup = runs["vcs_smoke.log"]["groups"][WAKEUP]
        self.assertEqual(wakeup["measured_count_interval_ps"], 5_000_000)
        self.assertEqual(wakeup["measured_count_interval_us"], 5)
        self.assertFalse(runs["vcs_bark.log"]["groups"][BARK]["cadence_measurable"])
        self.assertIsNone(runs["vcs_bite.log"]["groups"][BITE]["measured_count_interval_ps"])
        self.assertEqual(report["coverage_credit_granted"], 0)
        self.assertFalse(report["full_simulation_started"])

    def test_tampered_excerpt_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "evidence"
            shutil.copytree(EVIDENCE, copied)
            path = copied / "event-excerpts/vcs_smoke.log"
            path.write_text(path.read_text().replace("401707766", "401707767"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "provenance mismatch"):
                audit_evidence(copied)

    def test_unsupported_expected_group_and_incomplete_hashes_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "supported timer group"):
            self.audit_text("", expected_groups={"vcs.log": "typo"})
        with self.assertRaisesRegex(ValueError, "SHA-256 for every input"):
            self.audit_text("", source_log_hashes={})
