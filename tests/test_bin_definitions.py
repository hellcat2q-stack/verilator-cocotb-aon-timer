from __future__ import annotations

import unittest
import json
from pathlib import Path

from tools.import_bin_definitions import PINNED_REVISION, build_catalog


class BinDefinitionImportTests(unittest.TestCase):
    def test_import_deduplicates_per_instance_rows_without_hit_data(self):
        manifest = {
            "source": {"open_titan_commit": PINNED_REVISION},
            "counts": {"unique_type_bin_definitions": 1, "aon_timer_bins": 0},
            "bins": [
                {
                    "covergroup": "sample_pkg::shared_cg",
                    "bin_type": "coverpoint",
                    "coverpoint_or_cross": "cp_bit",
                    "bin_name": "auto[0]",
                    "source_file": "hw/dv/sample.sv",
                    "source_line": 12,
                    "hit_count": 99,
                },
                {
                    "covergroup": "sample_pkg::shared_cg",
                    "bin_type": "coverpoint",
                    "coverpoint_or_cross": "cp_bit",
                    "bin_name": "auto[0]",
                    "source_file": "hw/dv/sample.sv",
                    "source_line": 12,
                    "hit_count": 88,
                },
            ],
        }
        catalog = build_catalog(manifest, manifest_sha256="a" * 64)

        self.assertEqual(catalog["definition_count"], 1)
        self.assertEqual(catalog["definitions"][0]["instance_record_count"], 2)
        self.assertNotIn("hit_count", catalog["definitions"][0])
        self.assertFalse(catalog["hit_counts_included"])

    def test_auto_bin_ranges_are_parsed_using_aon_signal_width(self):
        manifest = {
            "source": {"open_titan_commit": PINNED_REVISION},
            "counts": {"unique_type_bin_definitions": 2, "aon_timer_bins": 2},
            "bins": [
                {
                    "covergroup": "aon_timer_env_pkg::aon_timer_env_cov::wake_up_timer_thold_hit_cg",
                    "bin_type": "coverpoint",
                    "coverpoint_or_cross": "wkup_count_cp",
                    "bin_name": "auto[0080000000000000:00ffffffffffffff]",
                    "source_file": "hw/ip/aon_timer/dv/env/aon_timer_env_cov.sv",
                    "source_line": 65,
                },
                {
                    "covergroup": "aon_timer_env_pkg::aon_timer_env_cov::watchdog_timer_bark_thold_hit_cg",
                    "bin_type": "coverpoint",
                    "coverpoint_or_cross": "wdog_count_cp",
                    "bin_name": "auto[16777216:33554431]",
                    "source_file": "hw/ip/aon_timer/dv/env/aon_timer_env_cov.sv",
                    "source_line": 80,
                },
            ],
        }
        catalog = build_catalog(manifest, manifest_sha256="b" * 64)
        by_item = {item["item"]: item for item in catalog["definitions"]}

        self.assertEqual(by_item["wkup_count_cp"]["value_range"], [0x0080000000000000, 0x00FFFFFFFFFFFFFF])
        self.assertEqual(by_item["wdog_count_cp"]["value_range"], [16777216, 33554431])

    def test_cross_records_keep_both_same_sample_bin_labels(self):
        manifest = {
            "source": {"open_titan_commit": PINNED_REVISION},
            "counts": {"unique_type_bin_definitions": 1, "aon_timer_bins": 1},
            "bins": [
                {
                    "covergroup": "aon_timer_env_pkg::aon_timer_env_cov::watchdog_timer_bark_thold_hit_cg",
                    "bin_type": "cross",
                    "coverpoint_or_cross": "wdog_thold_cpXwdog_bark_rst",
                    "bin_name": "wdog_thold_cp=auto[16777216:33554431] x wdog_bark_int=auto[1]",
                    "source_file": "hw/ip/aon_timer/dv/env/aon_timer_env_cov.sv",
                    "source_line": 85,
                }
            ],
        }
        definition = build_catalog(manifest, manifest_sha256="c" * 64)["definitions"][0]

        self.assertEqual(
            definition["cross_definition"]["members"],
            [
                {"coverpoint": "wdog_thold_cp", "bin_label": "auto[16777216:33554431]", "value_range": [16777216, 33554431]},
                {"coverpoint": "wdog_bark_int", "bin_label": "auto[1]", "value_range": [1, 1]},
            ],
        )

    def test_wrong_source_revision_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "pinned OpenTitan revision"):
            build_catalog({"source": {"open_titan_commit": "0" * 40}, "bins": []}, manifest_sha256="d" * 64)

    def test_checked_in_reference_catalog_has_audited_auto_and_cross_bins(self):
        catalog_path = Path(__file__).resolve().parents[1] / "references" / "bin_definitions.v1.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        self.assertEqual(catalog["definition_count"], 4507)
        self.assertEqual(catalog["aon_timer_definition_count"], 4279)
        self.assertEqual(len(catalog["auto_bin_partition_audit"]), 6)
        self.assertTrue(all(item["complete_non_overlapping_partition"] for item in catalog["auto_bin_partition_audit"]))
        self.assertEqual(len(catalog["cross_bin_partition_audit"]), 3)
        self.assertTrue(all(item["complete_cartesian_product"] for item in catalog["cross_bin_partition_audit"]))
        array_bins = [item for item in catalog["definitions"] if "array_bin" in item]
        self.assertEqual(len(array_bins), 160)
        self.assertTrue(all(item["array_bin"]["individual_value_range"] is None for item in array_bins))


if __name__ == "__main__":
    unittest.main()
