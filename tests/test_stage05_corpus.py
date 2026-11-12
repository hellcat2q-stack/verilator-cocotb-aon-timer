import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.run_stage05_corpus import parse_results_xml, summarize_coverage_trace
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

    def test_coverage_trace_summary_verifies_hash_counts_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_root = Path(temp_dir)
            trace_dir = run_root / "coverage-traces"
            trace_dir.mkdir()
            trace = {
                "schema_id": "aon_timer_uvm_source_trace_v1",
                "run_id": "run-1",
                "seed": 1,
                "source_revision": "9f20940d494a223cc950a5b98f748fb28109d458",
                "testcase": "case_a",
                "coverage_status": "SAMPLE_TRACE_ONLY",
                "canonical_bin_vector": None,
                "sample_count": 2,
                "samples": [
                    {"covergroup": "timer_cfg_cg", "resolved_canonical_bin_identity_hits": []},
                    {"covergroup": "timer_cfg_cg", "resolved_canonical_bin_identity_hits": []},
                ],
                "sample_counts_by_covergroup": {"timer_cfg_cg": 2},
                "resolved_canonical_bin_identity_hit_counts": {},
            }
            trace_path = trace_dir / "case_a.json"
            trace_path.write_text(json.dumps(trace) + "\n", encoding="utf-8")
            digest = hashlib.sha256(trace_path.read_bytes()).hexdigest()
            runner_manifest = {
                "run_id": "run-1",
                "seed": 1,
                "source_revision": "9f20940d494a223cc950a5b98f748fb28109d458",
                "coverage_schema_id": "aon_timer_uvm_source_trace_v1",
                "testcases": ["case_a"],
                "coverage_vector": None,
                "coverage_trace": {
                    "status": "PARTIAL_SOURCE_SAMPLE_TRACE",
                    "canonical_vector_generated": False,
                    "files": {
                        "case_a.json": {
                            "sha256": digest,
                            "sample_count": 2,
                            "sample_counts_by_covergroup": {"timer_cfg_cg": 2},
                            "coverage_status": "SAMPLE_TRACE_ONLY",
                        },
                    },
                },
            }

            summary = summarize_coverage_trace(run_root, runner_manifest)

        self.assertTrue(summary["validated"])
        self.assertFalse(summary["canonical_vector_generated"])
        self.assertEqual(summary["total_sample_count"], 2)
        self.assertEqual(summary["sample_counts_by_covergroup"], {"timer_cfg_cg": 2})
        self.assertEqual(summary["files"]["case_a.json"]["validation"], "PASS")

    def test_coverage_trace_summary_rejects_modified_file_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_root = Path(temp_dir)
            trace_dir = run_root / "coverage-traces"
            trace_dir.mkdir()
            trace_path = trace_dir / "case_a.json"
            trace_path.write_text(json.dumps({"samples": [], "sample_count": 0}), encoding="utf-8")
            runner_manifest = {
                "coverage_trace": {
                    "status": "PARTIAL_SOURCE_SAMPLE_TRACE",
                    "canonical_vector_generated": False,
                    "files": {"case_a.json": {"sha256": "0" * 64}},
                },
            }
            summary = summarize_coverage_trace(run_root, runner_manifest)

        self.assertFalse(summary["validated"])
        self.assertEqual(summary["files"]["case_a.json"]["validation"], "FAIL")


if __name__ == "__main__":
    unittest.main()
