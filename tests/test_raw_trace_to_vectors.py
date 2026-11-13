from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.raw_trace_to_vectors import convert_corpus
from tools.stage06_matrix import load_canonical_ids, load_run_vector


SOURCE_REVISION = "9f20940d494a223cc950a5b98f748fb28109d458"
COVERAGE_SCHEMA = "aon_timer_uvm_source_trace_v2"
BIN_ID = "aon_timer_env_pkg::aon_timer_env_cov::timer_cfg_cg||variable||prescale_cp||name:prescale_0||0"


class RawTraceToVectorTests(unittest.TestCase):
    def make_fixture(self, root: Path) -> tuple[Path, Path, Path, Path, Path]:
        trace_dir = root / "traces"
        output_dir = root / "vectors"
        trace_dir.mkdir()
        ids_path = root / "bin_ids.txt"
        ids_path.write_text(BIN_ID + "\n", encoding="utf-8")
        ids_hash = hashlib.sha256(ids_path.read_bytes()).hexdigest()
        catalog_path = root / "catalog.json"
        catalog_path.write_text(json.dumps({
            "schema": "aon-timer-canonical-bin-catalog-v1",
            "canonical_bin_count": 1,
            "canonical_bin_ids_sha256": ids_hash,
        }), encoding="utf-8")

        trace = {
            "schema_id": COVERAGE_SCHEMA,
            "source_revision": SOURCE_REVISION,
            "run_id": "run-1",
            "testcase": "case_a",
            "seed": 1,
            "coverage_status": "SAMPLE_TRACE_ONLY_CANONICAL_IDENTITIES_AVAILABLE_VALUE_PARTITIONS_UNMAPPED",
            "canonical_bin_vector": None,
            "sample_count": 1,
            "sample_counts_by_covergroup": {"timer_cfg_cg": 1},
            "resolved_canonical_bin_identity_hit_counts": {BIN_ID: 1},
            "samples": [{
                "covergroup": "timer_cfg_cg",
                "resolved_canonical_bin_identity_hits": [BIN_ID],
            }],
        }
        trace_path = trace_dir / "case_a.json"
        trace_path.write_text(json.dumps(trace, sort_keys=True) + "\n", encoding="utf-8")
        trace_hash = hashlib.sha256(trace_path.read_bytes()).hexdigest()
        corpus = {
            "schema": "aon-timer-stage05-corpus-manifest-v1",
            "source_revision": SOURCE_REVISION,
            "coverage_schema_id": COVERAGE_SCHEMA,
            "pool_id": "pool-1",
            "pool_sha256": "a" * 64,
            "attempt_count": 1,
            "attempts": [{
                "run_id": "run-1",
                "seed": 1,
                "result": "PASS",
                "testcases": [{"name": "case_a", "result": "PASS"}],
                "coverage_trace": {
                    "status": "PARTIAL_SOURCE_SAMPLE_TRACE",
                    "canonical_vector_generated": False,
                    "validated": True,
                    "file_count": 1,
                    "total_sample_count": 1,
                    "sample_counts_by_covergroup": {"timer_cfg_cg": 1},
                    "resolved_canonical_bin_identity_hit_counts": {BIN_ID: 1},
                    "files": {
                        "case_a.json": {
                            "sha256": trace_hash,
                            "sample_count": 1,
                            "sample_counts_by_covergroup": {"timer_cfg_cg": 1},
                            "coverage_status": trace["coverage_status"],
                        },
                    },
                },
            }],
        }
        corpus_path = root / "corpus.json"
        corpus_path.write_text(json.dumps(corpus), encoding="utf-8")
        return corpus_path, trace_dir, output_dir, catalog_path, ids_path

    def test_conversion_emits_only_known_hits_and_loads_as_partial_vector(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            corpus, trace_dir, output_dir, catalog, ids_path = self.make_fixture(Path(temp_dir))
            summary = convert_corpus(
                corpus,
                trace_dir,
                output_dir,
                catalog_path=catalog,
                ids_path=ids_path,
            )
            vector_path = output_dir / "run-1.json"
            _, ids = load_canonical_ids(catalog, ids_path)
            bins, vector_status, mapping_status = load_run_vector(
                vector_path,
                run_id="run-1",
                source_revision=SOURCE_REVISION,
                coverage_schema_id=COVERAGE_SCHEMA,
                pool_id="pool-1",
                pool_sha256="a" * 64,
                seed=1,
                canonical_ids=ids,
                identity_sha256=hashlib.sha256(ids_path.read_bytes()).hexdigest(),
            )

        self.assertEqual(summary["vector_count"], 1)
        self.assertFalse(summary["zero_misses_inferred"])
        self.assertEqual(bins, {BIN_ID: "1"})
        self.assertEqual(vector_status, "PARTIAL")
        self.assertEqual(mapping_status, "PARTIAL_VALIDATED")

    def test_conversion_rejects_tampered_trace_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            corpus, trace_dir, output_dir, catalog, ids_path = self.make_fixture(Path(temp_dir))
            (trace_dir / "case_a.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                convert_corpus(
                    corpus,
                    trace_dir,
                    output_dir,
                    catalog_path=catalog,
                    ids_path=ids_path,
                )


if __name__ == "__main__":
    unittest.main()
