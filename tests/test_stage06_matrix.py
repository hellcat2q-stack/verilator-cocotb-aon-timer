import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools.stage06_matrix import (
    CATALOG_PATH,
    build_matrix,
    load_canonical_ids,
    load_run_vector,
    write_outputs,
)


def make_corpus(attempts):
    for attempt in attempts:
        attempt.setdefault("tests_run", 4 if attempt.get("result") == "PASS" else 0)
        attempt.setdefault("tests_passed", attempt["tests_run"] if attempt.get("result") == "PASS" else 0)
        attempt.setdefault("tests_failed", 0)
    return {
        "schema": "aon-timer-stage05-corpus-manifest-v1",
        "freeze_id": "test-freeze",
        "pool_id": "test-pool",
        "pool_sha256": "a" * 64,
        "source_revision": "9f20940d494a223cc950a5b98f748fb28109d458",
        "coverage_schema_id": "aon_timer_uvm_source_trace_v1",
        "attempt_count": len(attempts),
        "attempts": attempts,
    }


class Stage06MatrixTests(unittest.TestCase):
    def setUp(self):
        _, self.bin_ids = load_canonical_ids()
        self.identity_hash = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["canonical_bin_ids_sha256"]

    def write_corpus(self, root, attempts):
        path = root / "corpus.json"
        path.write_text(json.dumps(make_corpus(attempts)), encoding="utf-8")
        return path

    def test_missing_vectors_are_unknown_not_uncovered(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corpus = self.write_corpus(root, [{
                "run_id": "run-1", "seed": 1, "result": "PASS", "shell_exit_code": 0
            }])
            ids, rows, audit = build_matrix(corpus)

        self.assertEqual(len(ids), 4507)
        self.assertEqual(len(rows[0]["cells"]), 4507)
        self.assertEqual(set(rows[0]["cells"].values()), {"?"})
        self.assertEqual(audit["matrix_status"], "PARTIAL_OR_UNAVAILABLE")
        self.assertEqual(audit["union"]["covered_bin_count"], 0)
        self.assertEqual(audit["union"]["unknown_bin_count"], 4507)
        self.assertEqual(audit["union"]["known_uncovered_bin_count"], 0)

    def test_valid_partial_vector_preserves_zero_unknown_and_failed_credit_policy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corpus = self.write_corpus(root, [
                {"run_id": "pass-1", "seed": 1, "result": "PASS", "shell_exit_code": 0},
                {"run_id": "fail-1", "seed": 2, "result": "FAIL", "shell_exit_code": 1},
            ])
            vector_dir = root / "vectors"
            vector_dir.mkdir()
            (vector_dir / "pass-1.json").write_text(json.dumps({
                "schema": "aon-timer-stage06-run-vector-v1",
                "run_id": "pass-1",
                "source_revision": "9f20940d494a223cc950a5b98f748fb28109d458",
                "coverage_schema_id": "aon_timer_uvm_source_trace_v1",
                "pool_id": "test-pool",
                "pool_sha256": "a" * 64,
                "seed": 1,
                "canonical_bin_count": 4507,
                "canonical_bin_ids_sha256": self.identity_hash,
                "mapping_status": "PARTIAL_VALIDATED",
                "vector_status": "PARTIAL",
                "bins": {self.bin_ids[0]: 1, self.bin_ids[1]: 0},
            }), encoding="utf-8")
            ids, rows, audit = build_matrix(corpus, vector_dir=vector_dir)

        self.assertEqual(rows[0]["cells"][ids[0]], "1")
        self.assertEqual(rows[0]["cells"][ids[1]], "0")
        self.assertEqual(rows[0]["cells"][ids[2]], "?")
        self.assertEqual(rows[1]["metadata"]["vector_status"], "FAILED_RUN_EXCLUDED")
        self.assertEqual(set(rows[1]["cells"].values()), {"?"})
        self.assertEqual(audit["failed_run_coverage_credit"], 0)
        self.assertEqual(audit["union"]["covered_bin_count"], 1)
        self.assertEqual(audit["union"]["known_uncovered_bin_count"], 1)
        self.assertEqual(audit["union"]["unknown_bin_count"], 4505)

    def test_vector_rejects_unmapped_identity_even_when_bin_label_looks_plausible(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "vector.json"
            path.write_text(json.dumps({
                "schema": "aon-timer-stage06-run-vector-v1",
                "run_id": "run-1",
                "source_revision": "9f20940d494a223cc950a5b98f748fb28109d458",
                "coverage_schema_id": "aon_timer_uvm_source_trace_v1",
                "pool_id": "test-pool",
                "pool_sha256": "a" * 64,
                "seed": 1,
                "canonical_bin_count": 4507,
                "canonical_bin_ids_sha256": self.identity_hash,
                "mapping_status": "UNVALIDATED_GUESS",
                "vector_status": "PARTIAL",
                "bins": {self.bin_ids[0]: 1},
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mapping_status"):
                load_run_vector(
                    path,
                    run_id="run-1",
                    source_revision="9f20940d494a223cc950a5b98f748fb28109d458",
                    coverage_schema_id="aon_timer_uvm_source_trace_v1",
                    pool_id="test-pool",
                    pool_sha256="a" * 64,
                    seed=1,
                    canonical_ids=self.bin_ids,
                    identity_sha256=self.identity_hash,
                )

    def test_complete_exact_vector_is_required_for_complete_matrix_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corpus = self.write_corpus(root, [{
                "run_id": "complete-1", "seed": 1, "result": "PASS", "shell_exit_code": 0
            }])
            vector_dir = root / "vectors"
            vector_dir.mkdir()
            (vector_dir / "complete-1.json").write_text(json.dumps({
                "schema": "aon-timer-stage06-run-vector-v1",
                "run_id": "complete-1",
                "source_revision": "9f20940d494a223cc950a5b98f748fb28109d458",
                "coverage_schema_id": "aon_timer_uvm_source_trace_v1",
                "pool_id": "test-pool",
                "pool_sha256": "a" * 64,
                "seed": 1,
                "canonical_bin_count": 4507,
                "canonical_bin_ids_sha256": self.identity_hash,
                "mapping_status": "EXACT_VALIDATED",
                "vector_status": "COMPLETE",
                "bins": {identity: int(index == 0) for index, identity in enumerate(self.bin_ids)},
            }), encoding="utf-8")

            _, rows, audit = build_matrix(corpus, vector_dir=vector_dir)

        self.assertEqual(audit["matrix_status"], "COMPLETE")
        self.assertEqual(rows[0]["metadata"]["known_hit_count"], 1)
        self.assertEqual(rows[0]["metadata"]["known_miss_count"], 4506)
        self.assertEqual(audit["union"]["unknown_bin_count"], 0)
        self.assertEqual(audit["union"]["known_uncovered_bin_count"], 4506)

    def test_csv_output_contains_metadata_and_all_4507_identity_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corpus = self.write_corpus(root, [{
                "run_id": "run-1", "seed": 1, "result": "PASS", "shell_exit_code": 0
            }])
            ids, rows, audit = build_matrix(corpus)
            paths = write_outputs(ids, rows, audit, root / "out")
            with Path(paths["matrix_csv"]).open(encoding="utf-8", newline="") as stream:
                matrix_rows = list(csv.reader(stream))

        self.assertEqual(len(matrix_rows[0]), 12 + 4507)
        self.assertEqual(len(matrix_rows), 2)
        self.assertEqual(matrix_rows[1][12], "?")
        self.assertEqual(matrix_rows[1][-1], "?")

    def test_all_failed_corpus_has_unknown_union_not_false_known_misses(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corpus = self.write_corpus(root, [{
                "run_id": "failed-1", "seed": 1, "result": "FAIL", "shell_exit_code": 1
            }])
            _, _, audit = build_matrix(corpus)

        self.assertEqual(audit["union"]["covered_bin_count"], 0)
        self.assertEqual(audit["union"]["unknown_bin_count"], 4507)
        self.assertEqual(audit["union"]["known_uncovered_bin_count"], 0)

    def test_pass_manifest_with_failed_testcase_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corpus = self.write_corpus(root, [{
                "run_id": "inconsistent", "seed": 1, "result": "PASS", "shell_exit_code": 0,
                "tests_run": 4, "tests_passed": 3, "tests_failed": 1,
            }])
            with self.assertRaisesRegex(ValueError, "all testcase outcomes"):
                build_matrix(corpus)

    def test_orphan_vector_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corpus = self.write_corpus(root, [{
                "run_id": "expected", "seed": 1, "result": "PASS", "shell_exit_code": 0
            }])
            vector_dir = root / "vectors"
            vector_dir.mkdir()
            (vector_dir / "orphan.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown run_id"):
                build_matrix(corpus, vector_dir=vector_dir)


if __name__ == "__main__":
    unittest.main()
