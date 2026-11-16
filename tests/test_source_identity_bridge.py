import json
import unittest
from pathlib import Path

from tools.audit_source_identity_bridge import (
    _cross_candidates,
    build_audit,
    parse_value_range,
)


class SourceIdentityBridgeTests(unittest.TestCase):
    def test_parser_accepts_sized_urg_and_source_ranges(self):
        self.assertEqual(
            parse_value_range("values:{ [ 64'h0000000000000000 : 64'h007fffffffffffff ] }"),
            (0, 0x007FFFFFFFFFFFFF),
        )
        self.assertEqual(parse_value_range("values:{ [ 0 : 4294967295 ] }"), (0, 4294967295))
        self.assertEqual(parse_value_range("auto[0080000000000000:00ffffffffffffff]"), (0x0080000000000000, 0x00FFFFFFFFFFFFFF))
        self.assertEqual(parse_value_range("values:[{ [ 1 ] }]"), (1, 1))

    def test_pinned_audit_is_complete_as_audit_data_but_not_promoted(self):
        root = Path(__file__).resolve().parents[1]
        canonical = (root / "references/canonical_bin_ids.txt").read_text(encoding="utf-8").splitlines()
        catalog = json.loads((root / "references/bin_definitions.v1.json").read_text(encoding="utf-8"))
        report = build_audit(canonical, catalog)
        self.assertEqual(report["canonical_identity_count"], 4507)
        self.assertEqual(report["source_definition_count"], 4507)
        self.assertEqual(report["classification_counts"], {
            "CROSS_EXACT_LABEL_CANDIDATE": 16,
            "CROSS_EXPANSION_CANDIDATE": 2064,
            "EXACT_SOURCE_DEFINITION": 341,
            "RANGE_EXACT_CANDIDATE": 12,
            "RANGE_ORDER_CANDIDATE": 2074,
        })
        self.assertEqual(report["coverage_credit_granted"], 0)
        self.assertFalse(report["promotion_allowed"])
        self.assertTrue(report["candidate_definition_ids_are_unique_for_exact_and_deterministic_rows"])

    def test_cross_wildcard_is_candidate_and_not_exact_credit(self):
        identity = "pkg::cg||cross||cross||name:*X*||0"
        peers = [
            {"bin_name": "a=auto[0] x b=set", "definition_id": "d0"},
            {"bin_name": "a=auto[1] x b=unset", "definition_id": "d1"},
        ]
        status, candidates, details = _cross_candidates(identity, peers)
        self.assertEqual(status, "CROSS_EXPANSION_CANDIDATE")
        self.assertEqual(len(candidates), 2)
        self.assertEqual(details["candidate_count"], 2)


if __name__ == "__main__":
    unittest.main()
