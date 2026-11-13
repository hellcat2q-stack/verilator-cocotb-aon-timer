from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.audit_array_bin_partition import ARRAYS, expected_partition


class ArrayBinPartitionAuditTests(unittest.TestCase):
    def test_even_partition_puts_remainder_in_final_bin(self):
        self.assertEqual(expected_partition(1, 10, 3), [[1, 3], [4, 6], [7, 10]])

    def test_reference_catalog_has_source_partition_shape(self):
        root = Path(__file__).resolve().parents[1]
        catalog = json.loads((root / "references" / "array_bin_ranges.v1.json").read_text(encoding="utf-8"))
        for name, spec in ARRAYS.items():
            actual = [item["value_range"] for item in sorted(catalog["arrays"][name], key=lambda item: item["ordinal"])]
            self.assertEqual(actual, expected_partition(spec["domain"][0], spec["domain"][1], spec["count"]))

    def test_partition_model_rejects_invalid_arguments(self):
        with self.assertRaises(ValueError):
            expected_partition(2, 1, 3)
        with self.assertRaises(ValueError):
            expected_partition(1, 2, 0)


if __name__ == "__main__":
    unittest.main()
