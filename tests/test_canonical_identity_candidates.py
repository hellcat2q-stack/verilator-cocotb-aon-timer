import json
import unittest
from pathlib import Path

from tools.audit_canonical_identity_candidates import build_audit, classify_identity


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
        self.assertEqual(report["coverage_credit_granted"], 0)


if __name__ == "__main__":
    unittest.main()
