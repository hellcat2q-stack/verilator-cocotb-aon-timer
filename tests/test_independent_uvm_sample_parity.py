"""Guard against promoting producer messages and partial matches to sample parity."""
import unittest

from tools.stage10_sample_parity.audit import compare_samples
from tools.stage10_sample_parity.collect_vcs import parse_log


class ActualInvocationTest(unittest.TestCase):
    def test_control_events_do_not_create_sample_invocations(self):
        payload = parse_log('''UVM_INFO @ 100 ps: component (aon_timer_scoreboard.sv:9) [test] WKUP Timer count: 4
UVM_INFO @ 100 ps: component (aon_timer_scoreboard.sv:10) [test] WKUP Timer expired check for interrupts
AON_PARITY {"kind":"sample","time_ps":100,"seq":0,"group":"wake_up_timer_thold_hit_cg","wkup_int":1,"wkup_thold":3,"wkup_count":17179869188}
UVM_ERROR : 0
UVM_FATAL : 0
TEST PASSED CHECKS
''')
        self.assertEqual(len(payload["control_events"]), 2)
        self.assertEqual(payload["sample_invocations"], 1)
        self.assertEqual(payload["records"][0]["wkup_count"], 17179869188)

    def test_unknown_reset_not_converted_to_miss_or_zero(self):
        payload = parse_log('AON_PARITY {"kind":"reset","time_ps":0,"rst_n":x,"rst_aon_n":0}')
        self.assertIsNone(payload["records"][0]["rst_n"])
        self.assertIsNone(payload["uvm_error_count"])

    def test_duplicate_sample_is_a_mismatch(self):
        record = {"group": "timer", "time_ps":100, "fields":{"count":4}}
        result = compare_samples([record], [record, record])
        self.assertFalse(result["same_time_multisets_equal"])
        self.assertEqual(result["groups"]["timer"]["only_cocotb_times_ps"], [100])

    def test_field_mismatch_is_preserved(self):
        left = [{"group":"timer", "time_ps":100, "fields":{"count":17179869188}}]
        right = [{"group":"timer", "time_ps":100, "fields":{"count":4}}]
        result = compare_samples(left, right)
        self.assertFalse(result["same_time_multisets_equal"])
        self.assertEqual(result["groups"]["timer"]["matched_time_field_differences"][0]["fields"]["count"], {"uvm":17179869188,"cocotb":4})


if __name__ == "__main__":
    unittest.main()
