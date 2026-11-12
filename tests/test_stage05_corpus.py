import json
import tempfile
import unittest
from pathlib import Path

from tools.run_stage05_corpus import parse_results_xml
from tools.stage05_corpus import (
    DEFAULT_FREEZE_PATH,
    DEFAULT_POOL_PATH,
    EXPECTED_TESTCASES,
    canonical_pool_sha256,
    load_frozen_pool,
)


class Stage05CorpusTests(unittest.TestCase):
    def test_frozen_pool_has_unique_seed_and_supported_testcase_order(self):
        pool, freeze, pool_hash = load_frozen_pool()
        self.assertEqual(pool["source_revision"], "9f20940d494a223cc950a5b98f748fb28109d458")
        self.assertEqual(freeze["status"], "FROZEN_BEFORE_FORMAL_RUN")
        self.assertEqual([case["name"] for case in pool["testcases"]], EXPECTED_TESTCASES)
        self.assertEqual(pool["seed_list"], [1])
        self.assertEqual(pool["budget"]["suite_runs"], 1)
        self.assertEqual(len(pool_hash), 64)
        self.assertFalse(pool["coverage_policy"]["generate_coverage_vector"])

    def test_freeze_rejects_modified_pool_hash(self):
        freeze = json.loads(DEFAULT_FREEZE_PATH.read_text(encoding="utf-8"))
        freeze["pool_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            freeze_path = Path(temp_dir) / "freeze.json"
            freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                load_frozen_pool(DEFAULT_POOL_PATH, freeze_path)

    def test_freeze_hash_is_stable_across_lf_and_crlf(self):
        lf_bytes = b'{\n  "pool": 1\n}\n'
        crlf_bytes = lf_bytes.replace(b"\n", b"\r\n")
        self.assertEqual(canonical_pool_sha256(lf_bytes), canonical_pool_sha256(crlf_bytes))

    def test_results_xml_reports_passes_and_simulation_time(self):
        content = """<testsuites><testsuite>
          <testcase name="case_a" sim_time_ns="10.5" />
          <testcase name="case_b" sim_time_ns="20"><failure message="failed" /></testcase>
        </testsuite></testsuites>"""
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "results.xml"
            report.write_text(content, encoding="utf-8")
            outcomes, total_ns = parse_results_xml(report)

        self.assertEqual([case["result"] for case in outcomes], ["PASS", "FAIL"])
        self.assertAlmostEqual(total_ns, 30.5)


if __name__ == "__main__":
    unittest.main()
