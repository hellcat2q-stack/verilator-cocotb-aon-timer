from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.audit_array_bin_observations import (
    DEFAULT_CORPUS,
    DEFAULT_TRACE_DIR,
    locate_array_bin,
    audit_observations,
)


ROOT = Path(__file__).resolve().parents[1]


class ArrayBinObservationAuditTests(unittest.TestCase):
    def test_classifier_handles_boundaries_and_zero_outside_the_array_domain(self):
        catalog = json.loads((ROOT / "references" / "array_bin_ranges.v1.json").read_text(encoding="utf-8"))
        bins = catalog["arrays"]["prescale"]

        self.assertIsNone(locate_array_bin("prescale", 0, bins))
        self.assertEqual(locate_array_bin("prescale", 1, bins)["ordinal"], 0)
        self.assertEqual(locate_array_bin("prescale", bins[0]["value_range"][1], bins)["ordinal"], 0)
        self.assertEqual(locate_array_bin("prescale", bins[1]["value_range"][0], bins)["ordinal"], 1)
        self.assertEqual(locate_array_bin("prescale", 4095, bins)["ordinal"], 31)

    def test_real_frozen_traces_produce_positive_reference_observations_only(self):
        result = audit_observations(DEFAULT_CORPUS, DEFAULT_TRACE_DIR)

        self.assertEqual(result["timer_cfg_samples_audited"], 78)
        self.assertEqual(result["observed_reference_array_bin_count"], 6)
        self.assertEqual(result["positive_observation_count"], 40)
        self.assertFalse(result["canonical_vector_generated"])
        self.assertFalse(result["unknown_bins_inferred_as_misses"])
        self.assertFalse(result["verilator_partition_equivalence_verified"])
        self.assertTrue(all(item["canonical_identity"] for item in result["positive_observations"]))

    def test_tampered_trace_bytes_are_rejected(self):
        corpus = json.loads(DEFAULT_CORPUS.read_text(encoding="utf-8"))
        first_filename = next(iter(corpus["attempts"][0]["coverage_trace"]["files"]))
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_dir = Path(temp_dir)
            for source in DEFAULT_TRACE_DIR.iterdir():
                shutil.copyfile(source, trace_dir / source.name)
            (trace_dir / first_filename).write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "raw trace hash mismatch"):
                audit_observations(DEFAULT_CORPUS, trace_dir)


if __name__ == "__main__":
    unittest.main()
