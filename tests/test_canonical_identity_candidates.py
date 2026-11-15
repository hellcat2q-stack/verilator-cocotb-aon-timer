import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.audit_canonical_identity_candidates import (
    build_audit,
    build_ordinal_range_candidates,
    classify_identity,
    validate_legacy_header_provenance,
)


def definition(name, value_range=None):
    row = {"scope": "pkg::cg", "kind": "variable", "item": "cp", "bin_name": name,
           "definition_id": f"pkg::cg||variable||cp||{name}"}
    if value_range is not None:
        row["value_range"] = value_range
    return row


class CanonicalIdentityCandidateTests(unittest.TestCase):
    def test_direct_label_requires_instance_zero(self):
        source = [definition("low")]
        direct = classify_identity("pkg::cg||variable||cp||name:low||0", source)
        repeated = classify_identity("pkg::cg||variable||cp||name:low||1", source)
        self.assertEqual(direct["classification"], "DIRECT_TYPE_IDENTITY_MATCH")
        self.assertEqual(repeated["classification"], "DIRECT_LABEL_BUT_INSTANCE_IDENTITY_UNRESOLVED")

    def test_exact_value_range_remains_candidate_not_identity_credit(self):
        source = [definition("auto[0:9]", [0, 9])]
        row = classify_identity("pkg::cg||variable||cp||values:{ [ 32'h00000000 : 32'h00000009 ] }||3", source)
        self.assertEqual(row["classification"], "EXACT_VALUE_RANGE_TYPE_CANDIDATE_INSTANCE_UNRESOLVED")
        self.assertEqual(row["candidate_definition_count"], 1)

    def test_adjacent_source_ranges_cover_composite_value_bin(self):
        source = [definition("auto[0:4]", [0, 4]), definition("auto[5:9]", [5, 9])]
        row = classify_identity("pkg::cg||variable||cp||values:{ [ 0 : 9 ] }||0", source)
        self.assertEqual(row["classification"], "COMPOSITE_VALUE_RANGE_TYPE_CANDIDATE_INSTANCE_UNRESOLVED")
        self.assertEqual(row["candidate_definition_count"], 2)

    def test_range_gap_and_cross_label_are_not_guessed(self):
        source = [definition("auto[0:3]", [0, 3]), definition("auto[5:9]", [5, 9])]
        row = classify_identity("pkg::cg||variable||cp||values:{ [ 0 : 9 ] }||0", source)
        cross = classify_identity("pkg::cg||cross||cpXflag||name:*X*||0", source)
        self.assertEqual(row["classification"], "PARTIAL_OR_GAPPED_VALUE_RANGE_CANDIDATE")
        self.assertEqual(cross["classification"], "CROSS_LABEL_OR_EXPANSION_UNRESOLVED")

    def test_overlapping_source_ranges_are_not_claimed_as_partition(self):
        source = [definition("auto[0:6]", [0, 6]), definition("auto[5:9]", [5, 9])]
        row = classify_identity("pkg::cg||variable||cp||values:{ [ 0 : 9 ] }||0", source)
        self.assertEqual(row["classification"], "OVERLAPPING_SOURCE_RANGE_CANDIDATE")

    def test_ordinal_candidates_require_complete_partition_and_zero_based_offsets(self):
        source = [definition("auto[5:9]", [5, 9]), definition("auto[0:4]", [0, 4])]
        complete = [
            "pkg::cg||variable||cp||values:{ [ 0 : 9 ] }||0",
            "pkg::cg||variable||cp||values:{ [ 0 : 9 ] }||1",
        ]
        candidates = build_ordinal_range_candidates(complete, source)
        self.assertEqual([row["candidate_bin_name"] for row in candidates], ["auto[0:4]", "auto[5:9]"])
        self.assertEqual([row["classification"] for row in candidates], ["RANGE_ORDER_CANDIDATE_UNVERIFIED"] * 2)

        skipped_offset = [complete[0], complete[1].removesuffix("1") + "2"]
        self.assertEqual(build_ordinal_range_candidates(skipped_offset, source), [])

    def test_legacy_header_provenance_verifies_manifest_hash_and_identity_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            matrix_path = root / "matrix.csv"
            manifest_path = root / "manifest.json"
            converter_path = root / "converter.py"
            canonical_ids = ["id-a", "id-b"]
            with matrix_path.open("w", encoding="utf-8", newline="") as stream:
                csv.writer(stream).writerow([*(f"meta-{i}" for i in range(13)), "report_id", *canonical_ids])
            manifest_path.write_text(json.dumps({
                "schema": "aon-timer-stage06-bin-manifest-v1",
                "bin_count": len(canonical_ids),
                "bin_key_format": "group::variable_or_cross::item::bin_name",
                "csv_sha256": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
            }), encoding="utf-8")
            converter_path.write_text("# pinned converter source\n", encoding="utf-8")

            result = validate_legacy_header_provenance(canonical_ids, manifest_path, matrix_path, converter_path)
            self.assertTrue(result["matrix_header_matches_frozen_canonical_ids"])
            self.assertEqual(result["bin_count"], 2)
            with self.assertRaisesRegex(ValueError, "does not match frozen canonical identity order"):
                validate_legacy_header_provenance(["id-a", "wrong"], manifest_path, matrix_path, converter_path)

    def test_audit_grants_no_coverage_credit(self):
        canonical = [f"pkg::cg||variable||cp||name:bin{i}||0" for i in range(4507)]
        catalog = {"schema": "aon-timer-bin-definitions-v1",
                   "source_revision": "9f20940d494a223cc950a5b98f748fb28109d458",
                   "definitions": [definition(f"bin{i}") for i in range(4507)]}
        report = build_audit(canonical, catalog)
        self.assertEqual(report["classification_counts"], {"DIRECT_TYPE_IDENTITY_MATCH": 4507})
        self.assertEqual(report["coverage_credit_granted"], 0)
        self.assertEqual(report["unknowns_inferred_as_misses"], 0)

    def test_pinned_catalog_classification_counts_are_reproducible(self):
        root = Path(__file__).resolve().parents[1]
        canonical_ids = (root / "references/canonical_bin_ids.txt").read_text(encoding="utf-8").splitlines()
        catalog = json.loads((root / "references/bin_definitions.v1.json").read_text(encoding="utf-8"))
        report = build_audit(canonical_ids, catalog)
        self.assertEqual(report["classification_counts"], {
            "COMPOSITE_VALUE_RANGE_TYPE_CANDIDATE_INSTANCE_UNRESOLVED": 2074,
            "CROSS_LABEL_OR_EXPANSION_UNRESOLVED": 2080,
            "DIRECT_TYPE_IDENTITY_MATCH": 341,
            "EXACT_VALUE_RANGE_TYPE_CANDIDATE_INSTANCE_UNRESOLVED": 2,
            "VALUE_LABEL_OR_SOURCE_MAPPING_UNRESOLVED": 10,
        })
        self.assertEqual(report["ordinal_range_mapping_candidate_count"], 2076)
        ordinal_definition_ids = [
            row["candidate_definition_id"] for row in report["ordinal_range_mapping_candidates"]
        ]
        direct_definition_ids = {
            definition_id
            for row in report["identities"]
            if row["classification"] == "DIRECT_TYPE_IDENTITY_MATCH"
            for definition_id in row["candidate_definition_ids"]
        }
        self.assertEqual(len(ordinal_definition_ids), len(set(ordinal_definition_ids)))
        self.assertFalse(direct_definition_ids.intersection(ordinal_definition_ids))
        self.assertEqual(report["coverage_credit_granted"], 0)


if __name__ == "__main__":
    unittest.main()
