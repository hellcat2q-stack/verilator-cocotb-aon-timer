import json
from pathlib import Path
import tempfile
import unittest

from tools.audit_legacy_urg_layouts import (
    LAYOUT_SCHEMA, align_by_semantics, audit_layouts, expand_layout, extract_page, semantic_identity,
)


def identity(name):
    return f"pkg::cg||variable||cp||name:{name}||0"


def report(name, rows):
    return {"report_id": name, "pages": [{"scope": "pkg::cg", "rows": rows}]}


def row(name, number=1):
    return {"kind": "variable", "item": "cp", "label": f"name:{name}", "number": number}


class LegacyUrgLayoutTests(unittest.TestCase):
    def test_named_bins_are_aligned_by_name_when_html_order_changes(self):
        old = [identity("set"), identity("unset")]
        new = list(reversed(old))
        pairs = align_by_semantics(old, new)
        self.assertEqual(len(pairs), 2)
        self.assertTrue(all(p["reference_identity"] == p["report_identity"] for p in pairs))
        self.assertTrue(all(p["reference_position"] != p["report_position"] for p in pairs))

    def test_covered_and_uncovered_singleton_wrappers_have_same_semantics(self):
        old = "pkg::cg||variable||cp||values:[{ [ 1 ] }]||0"
        new = "pkg::cg||variable||cp||values:{ [ 1 ] }||0"
        self.assertEqual(semantic_identity(old), semantic_identity(new))
        self.assertIsNone(semantic_identity("pkg::cg||variable||cp||values:{ [ 0 ] [ 1 ] }||0"))

    def test_compressed_values_crosses_and_duplicate_names_are_not_promoted(self):
        auto_range = "pkg::cg||variable||cp||values:{ [ 0 : 9 ] }||0"
        wildcard = "pkg::cg||cross||cpXflag||name:*X*||0"
        self.assertIsNone(semantic_identity(auto_range))
        self.assertIsNone(semantic_identity(wildcard))
        self.assertEqual(align_by_semantics([auto_range, wildcard], [auto_range, wildcard]), [])
        self.assertEqual(align_by_semantics([identity("set"), identity("set")], [identity("set")]), [])
        aggregate = [identity("bin_group"), identity("bin_group").removesuffix("0") + "1"]
        self.assertEqual(align_by_semantics(aggregate, aggregate), [])

    def test_audit_exposes_semantic_counterexample_despite_equal_cardinality(self):
        old = report("reference", [row("set"), row("unset")])
        new = report("next", [row("unset"), row("set")])
        result = audit_layouts({"schema": LAYOUT_SCHEMA, "reports": [old, new]}, sorted([identity("set"), identity("unset")]))
        self.assertEqual(result["status"], "UNSAFE_LEGACY_POSITIONAL_BRIDGE")
        self.assertEqual(result["confirmed_semantic_position_conflicts"], 2)
        self.assertFalse(result["positional_mapping_promotion_allowed"])
        self.assertEqual(result["coverage_credit_granted"], 0)

    def test_reference_header_must_match_and_repeated_instance_tables_deduplicate(self):
        old = report("reference", [row("set"), row("set")])
        self.assertEqual(sum(map(len, expand_layout(old).values())), 1)
        with self.assertRaisesRegex(ValueError, "does not reproduce"):
            audit_layouts({"schema": LAYOUT_SCHEMA, "reports": [old, report("next", [row("set")])]}, [identity("wrong")])

    def test_html_export_discards_counts_paths_test_names_and_scores(self):
        html = '''<html><title>Unified Coverage Report :: Group :: pkg::cg</title>
        <a>/private/server/path</a><span class="repname">Summary for Variable cp</span>
        <span class="repname">Covered bins</span><table><tr>
        <td>NAME</td><td>COUNT</td><td>SUBSUMED VALUES</td><td>NUMBER</td><td>TEST</td>
        </tr><tr><td>set</td><td>98765</td><td>{ [ 1 ] }</td><td>1</td><td>private-test</td></tr></table></html>'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "grp0.html"
            path.write_text(html, encoding="utf-8")
            page = extract_page(path)
        self.assertEqual(page["rows"], [{"kind": "variable", "item": "cp", "label": "values:{ [ 1 ] }", "number": 1}])
        self.assertNotIn("98765", str(page))
        self.assertNotIn("private-test", str(page))
        self.assertNotIn("/private/server/path", str(page))

    def test_recovered_layouts_reproduce_header_and_conflicts_without_server(self):
        root = Path(__file__).resolve().parents[1]
        evidence = root / "evidence/stage10_legacy_urg_layout/2026-11-15-v1"
        layouts = json.loads((evidence / "layouts.json").read_text(encoding="utf-8"))
        canonical = (root / "references/canonical_bin_ids.txt").read_text(encoding="utf-8").splitlines()
        result = audit_layouts(layouts, canonical)
        self.assertTrue(result["reference_header_reproduced"])
        self.assertEqual(result["canonical_identity_count"], 4507)
        self.assertEqual(result["report_count"], 5)
        self.assertEqual(result["confirmed_semantic_position_conflicts"], 559)
        self.assertTrue(all(row["explicit_semantic_alignment_count"] == 345 for row in result["comparisons"]))
        self.assertFalse(result["positional_mapping_promotion_allowed"])


if __name__ == "__main__":
    unittest.main()
