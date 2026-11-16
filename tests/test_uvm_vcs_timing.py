import tempfile
import unittest
from pathlib import Path

from tools.audit_uvm_vcs_timing import audit_logs


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
        self.assertTrue(report["independent_uvm_vcs_timing_comparison_complete"])
        self.assertEqual(report["coverage_credit_granted"], 0)

    def test_missing_expiry_is_fail_closed(self):
        text = "UVM_INFO @ 100 ps: (aon_timer_scoreboard.sv:289) WKUP Timer count:          1\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vcs.log"
            path.write_text(text, encoding="utf-8")
            report = audit_logs([path])
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["independent_uvm_vcs_timing_comparison_complete"])
