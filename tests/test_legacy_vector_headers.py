import unittest

from tools.audit_legacy_vector_headers import (
    _array_indexes,
    _classify_header,
    parse_array_range,
    parse_ordinal,
)


def definition(kind, item, label, value_range=None):
    row = {
        "scope": "pkg::cg", "kind": kind, "item": item, "bin_name": label,
        "definition_id": f"pkg::cg||{kind}||{item}||{label}",
    }
    if value_range is not None:
        row["value_range"] = value_range
    return row


class LegacyVectorHeaderTests(unittest.TestCase):
    def test_decimal_ordinals_and_hex_array_endpoints_are_distinct(self):
        self.assertEqual(parse_ordinal("name:auto[10]"), 10)
        self.assertIsNone(parse_ordinal("name:auto[0xa]"))
        self.assertEqual(parse_array_range("name:prescale[0x080:0x0fe]"), ("prescale", 128, 254))
        self.assertEqual(parse_array_range("name:bark[128:254]"), ("bark", 128, 254))
        self.assertIsNone(parse_array_range("name:bark[254:128]"))

    def test_numeric_order_is_independent_of_lexicographic_header_order(self):
        definitions = [definition("variable", "cp", f"auto[{i * 16}:{i * 16 + 15}]", [i * 16, i * 16 + 15])
                       for i in range(12)]
        identities = sorted(f"pkg::cg||variable||cp||name:auto[{i}]||0" for i in range(12))
        report = _classify_header(identities, set(), list(reversed(definitions)), {})
        row = next(row for row in report["identities"] if "name:auto[10]||" in row["identity"])
        self.assertEqual(row["candidate_value_range"], [160, 175])
        self.assertEqual(report["classification_counts"], {"RANGE_CANDIDATE": 12})
        self.assertEqual(report["coverage_credit_granted"], 0)
        self.assertFalse(report["promotion_allowed"])

    def test_incomplete_ordinal_group_does_not_assign_a_source_range(self):
        definitions = [definition("variable", "cp", "auto[0:15]", [0, 15]),
                       definition("variable", "cp", "auto[16:31]", [16, 31])]
        report = _classify_header(["pkg::cg||variable||cp||name:auto[0]||0"], set(), definitions, {})
        self.assertEqual(report["unresolved_count"], 1)

    def test_overlapping_partitions_and_nonzero_instances_are_not_exact(self):
        definitions = [definition("variable", "cp", "auto[0:15]", [0, 15]),
                       definition("variable", "cp", "auto[15:31]", [15, 31])]
        identities = ["pkg::cg||variable||cp||name:auto[0]||0", "pkg::cg||variable||cp||name:auto[1]||0"]
        report = _classify_header(identities, set(), definitions, {})
        self.assertEqual(report["unresolved_count"], 2)
        report = _classify_header(["pkg::cg||variable||cp||name:flag||1"], set(),
                                 [definition("variable", "cp", "flag")], {})
        self.assertEqual(report["unresolved_count"], 1)

    def test_cross_uses_numeric_range_metadata_and_preserves_brackets(self):
        definitions = []
        for index in range(12):
            low, high = index * 16, index * 16 + 15
            for state in ("set", "unset"):
                row = definition("cross", "cross", f"a=auto[{low}:{high}] x b={state}")
                row["cross_definition"] = {"members": [
                    {"coverpoint": "a", "bin_label": f"auto[{low}:{high}]", "value_range": [low, high]},
                    {"coverpoint": "b", "bin_label": state, "value_range": None},
                ]}
                definitions.append(row)
        identities = ["pkg::cg||cross||cross||name:auto[10]Xset||0",
                      "pkg::cg||cross||cross||name:auto[10]Xunset||0"]
        report = _classify_header(identities, set(), definitions, {})
        self.assertEqual(report["classification_counts"], {"CROSS_ORDINAL_CANDIDATE": 2})
        self.assertEqual(report["identities"][0]["candidate_count"], 1)
        self.assertIn("a=auto[160:175] x b=set", report["identities"][0]["candidate_definition_ids"][0])

    def test_array_matches_scope_item_and_range_not_column_position(self):
        canonical = "pkg::cg||variable||cp||name:array[0]||0"
        reference = {"arrays": {"array": [{"ordinal": 0, "canonical_identity": canonical,
                                           "source_interval_label": "array[1:127]", "value_range": [1, 127]}]}}
        indexes = _array_indexes(reference)
        identities = ["pkg::cg||variable||cp||name:array[0x01:0x7f]||0"]
        report = _classify_header(identities, {canonical}, [definition("variable", "cp", "array[0]")], indexes)
        self.assertEqual(report["identities"][0]["candidate_canonical_identity"], canonical)
        report = _classify_header([identities[0].replace("||cp||", "||other||")], {canonical}, [], indexes)
        self.assertEqual(report["unresolved_count"], 1)


if __name__ == "__main__":
    unittest.main()
