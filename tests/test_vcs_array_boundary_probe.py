import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.vcs_array_boundary_probe import ROOT, audit, boundary_cases, native_bin_semantics

EVIDENCE = ROOT / "evidence/stage10_vcs_array_boundary/2026-11-16-v1"


class VcsArrayBoundaryTests(unittest.TestCase):
    def test_published_native_calibration_replays_all_boundaries(self):
        result = audit(EVIDENCE / "plan.json", EVIDENCE / "observations.json")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["cases_passed"], 636)
        self.assertEqual(result["unrepresentable_cases_rejected_without_truncation"], 4)
        self.assertTrue(result["vcs_run_provenance_verified"])
        self.assertFalse(result["uvm_sample_timing_parity_verified"])
        self.assertEqual(result["coverage_credit_granted"], 0)

    def test_native_bin_ranges_compare_numerically_without_guessing_ordinals(self):
        self.assertEqual(native_bin_semantics("prescale[0x080:0x0fe]", "prescale", 12),
                         native_bin_semantics("prescale[128:254]", "prescale", 12))
        with self.assertRaises(ValueError):
            native_bin_semantics("prescale[1]", "prescale", 12)
        with self.assertRaises(ValueError):
            native_bin_semantics("prescale[4000:4096]", "prescale", 12)

    def test_boundary_plan_rejects_out_of_domain_values_without_wrapping(self):
        catalog = json.loads((ROOT / "references/array_bin_ranges.v1.json").read_text(encoding="utf-8"))
        cases, invalid = boundary_cases(catalog)
        self.assertEqual(len(cases), 636)
        self.assertEqual(len(invalid), 4)
        self.assertTrue(all(row["value"] == 2 ** row["width"] for row in invalid))

    def test_wrong_native_bin_fails_even_in_a_consistent_test_fixture(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            for name in ("plan.json", "observations.json", "attestation.json"):
                shutil.copyfile(EVIDENCE / name, target / name)
            observed_path = target / "observations.json"
            observed = json.loads(observed_path.read_text(encoding="utf-8"))
            observed["cases"][1]["hit_bin_names"] = ["bark[134217728:268435454]"]
            observed_path.write_text(json.dumps(observed), encoding="utf-8")
            attestation_path = target / "attestation.json"
            attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
            attestation["observations_sha256"] = hashlib.sha256(observed_path.read_bytes()).hexdigest()
            attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
            result = audit(target / "plan.json", observed_path)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["cases_passed"], 635)


if __name__ == "__main__":
    unittest.main()
