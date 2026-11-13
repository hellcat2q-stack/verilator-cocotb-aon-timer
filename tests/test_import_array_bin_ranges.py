from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from tools.import_array_bin_ranges import (
    EXPECTED_ARRAYS,
    EXPECTED_BINS,
    _read_header,
    build_range_catalog,
)


ROOT = Path(__file__).resolve().parents[1]


def reference_inputs() -> tuple[list[str], list[str], dict, dict, dict]:
    canonical_ids = (ROOT / "references" / "canonical_bin_ids.txt").read_text(encoding="utf-8").splitlines()
    definitions = json.loads((ROOT / "references" / "bin_definitions.v1.json").read_text(encoding="utf-8"))
    protocol = {
        "schema": "aon-timer-stage08-policy-v2",
        "bin_count": EXPECTED_BINS,
        "bin_identity": "VCS cumulative XML coverpoint/bin definitions and crosspoint tuples",
        "mapping_sha256": "a" * 64,
    }
    validation = {"status": "pass", "bin_count": EXPECTED_BINS, "mapping_sha256": "a" * 64}
    definitions_by_identity = {
        "||".join((entry["scope"], entry["kind"], entry["item"], f"name:{entry['bin_name']}", "0")): entry
        for entry in definitions["definitions"]
    }
    columns = []
    for identity in canonical_ids:
        entry = definitions_by_identity.get(identity)
        if entry and "array_bin" in entry:
            name = entry["bin_name"].split("[", 1)[0]
            index = entry["array_bin"]["index"]
            count = EXPECTED_ARRAYS[name]["count"]
            width = EXPECTED_ARRAYS[name]["width"]
            maximum = (1 << width) - 1
            domain = maximum
            low = 1 + index * domain // count
            high = 1 + (index + 1) * domain // count - 1
            columns.append("||".join((
                entry["scope"], "variable", EXPECTED_ARRAYS[name]["coverpoint"],
                f"name:{name}[{low}:{high}]", "0",
            )))
        else:
            columns.append(identity)
    assert len(columns) == EXPECTED_BINS
    return columns, canonical_ids, definitions, protocol, validation


def import_fixture(columns: list[str], canonical_ids: list[str], definitions: dict, protocol: dict, validation: dict):
    return build_range_catalog(
        ["sequence_name", "runtime", *columns],
        header_sha256="b" * 64,
        canonical_ids=canonical_ids,
        definition_catalog=definitions,
        source_protocol=protocol,
        mapping_validation=validation,
        protocol_sha256="c" * 64,
        mapping_validation_sha256="d" * 64,
    )


class ArrayBinRangeImportTests(unittest.TestCase):
    def test_valid_header_imports_all_160_ranges_without_hit_data(self):
        columns, canonical_ids, definitions, protocol, validation = reference_inputs()
        result = import_fixture(columns, canonical_ids, definitions, protocol, validation)

        self.assertEqual(result["mapping"]["total_array_bin_count"], 160)
        self.assertTrue(result["mapping"]["one_to_one_canonical_identity_mapping"])
        self.assertFalse(result["mapping"]["current_verilator_partition_verified"])
        self.assertFalse(result["source_evidence"]["historical_run_rows_read"])
        self.assertFalse(result["source_evidence"]["historical_hit_counts_imported"])
        self.assertEqual(sum(map(len, result["arrays"].values())), 160)

    def test_gap_in_reported_partition_is_rejected(self):
        columns, canonical_ids, definitions, protocol, validation = reference_inputs()
        index = next(i for i, value in enumerate(columns) if re.search(r"name:prescale\[128:", value))
        columns[index] = re.sub(r"name:prescale\[(\d+):", lambda match: f"name:prescale[{int(match.group(1)) + 1}:", columns[index])

        with self.assertRaisesRegex(ValueError, "gap or overlap"):
            import_fixture(columns, canonical_ids, definitions, protocol, validation)

    def test_missing_interval_label_is_rejected_even_with_column_count_preserved(self):
        columns, canonical_ids, definitions, protocol, validation = reference_inputs()
        index = next(i for i, value in enumerate(columns) if "name:wkup[" in value)
        columns[index] = "unmapped||column||placeholder||name:other||0"

        with self.assertRaisesRegex(ValueError, "expected 64 interval labels"):
            import_fixture(columns, canonical_ids, definitions, protocol, validation)

    def test_source_definition_index_and_domain_must_match_the_reference(self):
        columns, canonical_ids, definitions, protocol, validation = reference_inputs()
        array_definition = next(item for item in definitions["definitions"] if "array_bin" in item)
        array_definition["array_bin"]["declared_value_range"][0] = 0

        with self.assertRaisesRegex(ValueError, "disagrees with .* declaration"):
            import_fixture(columns, canonical_ids, definitions, protocol, validation)

    def test_header_reader_never_decodes_or_reads_run_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "vectors.csv"
            first_line = b'run,runtime,"bin,with,commas"\n'
            path.write_bytes(first_line + b"\xffhistorical run row without newline")

            header, digest = _read_header(path)

        self.assertEqual(header, ["run", "runtime", "bin,with,commas"])
        self.assertEqual(digest, hashlib.sha256(first_line).hexdigest())


if __name__ == "__main__":
    unittest.main()
