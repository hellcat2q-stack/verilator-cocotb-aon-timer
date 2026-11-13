"""Audit positive timer_cfg array-bin observations using VCS reference ranges.

This emits an observation audit, never a canonical coverage vector. Unobserved
bins remain unknown and Verilator partition equivalence remains unverified.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from stage08_preflight import validate_array_range_catalog
except ModuleNotFoundError:  # Support importing as tools.audit_array_bin_observations.
    from tools.stage08_preflight import validate_array_range_catalog

try:
    from coverage_model import SUPPORTED_COVERAGE_SCHEMA_IDS
except ModuleNotFoundError:  # Support importing as tools.audit_array_bin_observations.
    from tools.coverage_model import SUPPORTED_COVERAGE_SCHEMA_IDS


ROOT = Path(__file__).resolve().parents[1]
PINNED_REVISION = "9f20940d494a223cc950a5b98f748fb28109d458"
DEFAULT_CORPUS = ROOT / "evidence" / "stage05_initial_corpus.json"
DEFAULT_TRACE_DIR = ROOT / "evidence" / "stage03_raw_trace" / "coverage-traces"
DEFAULT_RANGE_CATALOG = ROOT / "references" / "array_bin_ranges.v1.json"
DEFAULT_DEFINITIONS = ROOT / "references" / "bin_definitions.v1.json"
DEFAULT_CANONICAL_CATALOG = ROOT / "references" / "canonical_bin_catalog.json"
DEFAULT_BIN_IDS = ROOT / "references" / "canonical_bin_ids.txt"
DEFAULT_COVERAGE_SCHEMA = ROOT / "configs" / "coverage_schema.json"
ARRAY_FIELDS = {
    "prescale": "prescale",
    "bark": "bark_thold",
    "bite": "bite_thold",
    "wkup": "wkup_thold",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def locate_array_bin(name: str, value: int, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the uniquely matching reference range record, if value is in-domain."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("array-bin sample values must be integers")
    ordered = sorted(records, key=lambda record: record["value_range"][0])
    starts = [record["value_range"][0] for record in ordered]
    index = bisect.bisect_right(starts, value) - 1
    if index < 0:
        return None
    record = ordered[index]
    if value <= record["value_range"][1]:
        if record["ordinal"] != index:
            raise ValueError(f"{name}: range ordinal is not ordered")
        return record
    return None


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    raw = Path(path).read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value, raw


def audit_observations(
    corpus_path: Path,
    trace_dir: Path,
    *,
    range_catalog_path: Path = DEFAULT_RANGE_CATALOG,
    definitions_path: Path = DEFAULT_DEFINITIONS,
    canonical_catalog_path: Path = DEFAULT_CANONICAL_CATALOG,
    bin_ids_path: Path = DEFAULT_BIN_IDS,
    coverage_schema_path: Path = DEFAULT_COVERAGE_SCHEMA,
) -> dict[str, Any]:
    corpus_path = Path(corpus_path).resolve()
    trace_dir = Path(trace_dir).resolve()
    range_catalog_path = Path(range_catalog_path).resolve()
    definitions_path = Path(definitions_path).resolve()
    canonical_catalog_path = Path(canonical_catalog_path).resolve()
    bin_ids_path = Path(bin_ids_path).resolve()
    coverage_schema_path = Path(coverage_schema_path).resolve()

    corpus, corpus_bytes = _load_json(corpus_path, "Stage 05 corpus manifest")
    range_catalog, range_bytes = _load_json(range_catalog_path, "array-bin range catalog")
    definitions, definitions_bytes = _load_json(definitions_path, "bin-definition catalog")
    canonical_catalog, canonical_catalog_bytes = _load_json(canonical_catalog_path, "canonical identity catalog")
    coverage_schema, coverage_schema_bytes = _load_json(coverage_schema_path, "coverage schema")
    ids_bytes = bin_ids_path.read_bytes()
    canonical_ids = ids_bytes.decode("utf-8").splitlines()

    sidecar_path = range_catalog_path.with_suffix(range_catalog_path.suffix + ".sha256")
    sidecar = sidecar_path.read_text(encoding="ascii").strip()
    sidecar_match = re.fullmatch(r"([0-9a-f]{64})  (.+)", sidecar)
    range_digest = sha256_bytes(range_bytes)
    if not sidecar_match or sidecar_match.group(1) != range_digest or sidecar_match.group(2) != range_catalog_path.name:
        raise ValueError("array-bin range catalog SHA-256 sidecar does not match the catalog")
    if sha256_bytes(ids_bytes) != canonical_catalog.get("canonical_bin_ids_sha256"):
        raise ValueError("canonical identity list does not match its catalog hash")
    if len(canonical_ids) != canonical_catalog.get("canonical_bin_count") or len(set(canonical_ids)) != len(canonical_ids):
        raise ValueError("canonical identity list count or uniqueness check failed")
    unresolved, equivalent = validate_array_range_catalog(
        definitions, canonical_ids, range_catalog, coverage_schema
    )
    if unresolved != 0 or equivalent:
        raise ValueError("array-bin reference catalog did not pass its expected reference-only validation")
    if corpus.get("schema") != "aon-timer-stage05-corpus-manifest-v1":
        raise ValueError("unsupported Stage 05 corpus manifest schema")
    if corpus.get("source_revision") != PINNED_REVISION:
        raise ValueError("corpus source revision does not match pinned RTL")
    if corpus.get("coverage_schema_id") not in SUPPORTED_COVERAGE_SCHEMA_IDS:
        raise ValueError("corpus and coverage schema IDs disagree")
    timer_cfg_group = next(
        (group for group in coverage_schema.get("groups", []) if group.get("name") == "timer_cfg_cg"),
        None,
    )
    if not isinstance(timer_cfg_group, dict):
        raise ValueError("coverage schema has no timer_cfg_cg definition")
    field_widths = {
        field: spec.get("width") for field, spec in timer_cfg_group.get("fields", {}).items()
        if isinstance(spec, dict)
    }
    attempts = corpus.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != corpus.get("attempt_count"):
        raise ValueError("corpus attempt list/count mismatch")

    canonical_set = set(canonical_ids)
    observations: list[dict[str, Any]] = []
    trace_evidence: dict[str, Any] = {}
    observed_bins: dict[str, set[str]] = {name: set() for name in ARRAY_FIELDS}
    occurrence_counts: Counter[str] = Counter()
    tested_sample_count = 0
    traced_sample_count = 0
    passed_attempt_count = 0

    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise ValueError("corpus attempt entry must be a JSON object")
        if attempt.get("result") != "PASS":
            continue
        passed_attempt_count += 1
        run_id = attempt.get("run_id")
        seed = attempt.get("seed")
        trace_summary = attempt.get("coverage_trace")
        if not isinstance(run_id, str) or not isinstance(seed, int) or isinstance(seed, bool):
            raise ValueError("passing attempt has an invalid run ID or seed")
        if (
            not isinstance(trace_summary, dict)
            or trace_summary.get("validated") is not True
            or trace_summary.get("status") != "PARTIAL_SOURCE_SAMPLE_TRACE"
            or trace_summary.get("canonical_vector_generated") is not False
        ):
            raise ValueError(f"{run_id}: expected a validated partial trace without a vector")
        trace_files = trace_summary.get("files")
        if not isinstance(trace_files, dict) or not trace_files:
            raise ValueError(f"{run_id}: no raw trace files are declared")
        testcase_names: set[str] = set()
        run_trace_count = 0
        run_sample_count = 0
        run_groups: Counter[str] = Counter()
        file_evidence: dict[str, Any] = {}

        for filename, declared in sorted(trace_files.items()):
            if not isinstance(filename, str) or Path(filename).name != filename or not isinstance(declared, dict):
                raise ValueError(f"{run_id}: invalid raw trace filename or declaration")
            path = trace_dir / filename
            raw = path.read_bytes()
            digest = sha256_bytes(raw)
            if digest != declared.get("sha256"):
                raise ValueError(f"{run_id}: raw trace hash mismatch for {filename}")
            trace = json.loads(raw.decode("utf-8"))
            if not isinstance(trace, dict):
                raise ValueError(f"{run_id}: raw trace must contain a JSON object")
            samples = trace.get("samples")
            if not isinstance(samples, list) or len(samples) != declared.get("sample_count"):
                raise ValueError(f"{run_id}: raw trace sample count mismatch for {filename}")
            if (
                trace.get("sample_count") != len(samples)
                or trace.get("run_id") != run_id
                or trace.get("seed") != seed
                or trace.get("source_revision") != PINNED_REVISION
                or trace.get("schema_id") != corpus.get("coverage_schema_id")
                or trace.get("canonical_bin_vector") is not None
                or trace.get("coverage_status") != declared.get("coverage_status")
            ):
                raise ValueError(f"{run_id}: raw trace metadata mismatch for {filename}")
            testcase = trace.get("testcase")
            if not isinstance(testcase, str) or testcase in testcase_names:
                raise ValueError(f"{run_id}: missing or duplicate testcase trace")
            testcase_names.add(testcase)
            groups: Counter[str] = Counter()
            for sample in samples:
                if not isinstance(sample, dict) or not isinstance(sample.get("covergroup"), str):
                    raise ValueError(f"{run_id}: malformed sample in {filename}")
                group = sample["covergroup"]
                groups[group] += 1
                if group != "timer_cfg_cg":
                    continue
                fields = sample.get("fields")
                if not isinstance(fields, dict):
                    raise ValueError(f"{run_id}: timer_cfg sample lacks its field values")
                tested_sample_count += 1
                sample_index = sample.get("sample_index")
                if not isinstance(sample_index, int) or isinstance(sample_index, bool):
                    raise ValueError(f"{run_id}: timer_cfg sample lacks a global sample index")
                for array_name, field_name in ARRAY_FIELDS.items():
                    if field_name not in fields:
                        raise ValueError(f"{run_id}: timer_cfg sample lacks {field_name}")
                    value = fields[field_name]
                    width = field_widths.get(field_name)
                    if (
                        not isinstance(value, int) or isinstance(value, bool)
                        or not isinstance(width, int) or not 0 <= value < (1 << width)
                    ):
                        raise ValueError(f"{run_id}: timer_cfg.{field_name} is outside its source field width")
                    record = locate_array_bin(array_name, value, range_catalog["arrays"][array_name])
                    if record is None:
                        continue
                    identity = record["canonical_identity"]
                    if identity not in canonical_set:
                        raise ValueError(f"{run_id}: reference range contains a non-canonical identity")
                    observations.append({
                        "run_id": run_id,
                        "seed": seed,
                        "testcase": testcase,
                        "trace_file": filename,
                        "trace_sha256": digest,
                        "sample_index": sample_index,
                        "array": array_name,
                        "source_field": field_name,
                        "sample_value": value,
                        "array_ordinal": record["ordinal"],
                        "source_interval_label": record["source_interval_label"],
                        "canonical_identity": identity,
                    })
                    observed_bins[array_name].add(identity)
                    occurrence_counts[identity] += 1

            if dict(sorted(groups.items())) != dict(sorted(declared.get("sample_counts_by_covergroup", {}).items())):
                raise ValueError(f"{run_id}: raw trace covergroup counts disagree for {filename}")
            if dict(sorted(groups.items())) != dict(sorted(trace.get("sample_counts_by_covergroup", {}).items())):
                raise ValueError(f"{run_id}: raw trace internal covergroup counts disagree for {filename}")
            run_groups.update(groups)
            run_trace_count += 1
            run_sample_count += len(samples)
            file_evidence[filename] = {"sha256": digest, "sample_count": len(samples), "testcase": testcase}

        expected_testcases = {
            item.get("name") for item in attempt.get("testcases", [])
            if isinstance(item, dict) and item.get("result") == "PASS"
        }
        if testcase_names != expected_testcases:
            raise ValueError(f"{run_id}: raw traces do not match the passing testcase set")
        if (
            run_trace_count != trace_summary.get("file_count")
            or run_sample_count != trace_summary.get("total_sample_count")
            or dict(sorted(run_groups.items())) != dict(sorted(trace_summary.get("sample_counts_by_covergroup", {}).items()))
        ):
            raise ValueError(f"{run_id}: corpus raw trace summary disagrees with trace files")
        trace_evidence[run_id] = {
            "seed": seed,
            "total_sample_count": run_sample_count,
            "timer_cfg_sample_count": run_groups.get("timer_cfg_cg", 0),
            "files": file_evidence,
        }
        traced_sample_count += run_sample_count

    if passed_attempt_count == 0:
        raise ValueError("corpus contains no passing attempts with validated raw traces")
    counts_by_array = {
        name: {
            "observed_bin_count": len(observed_bins[name]),
            "observed_identities": sorted(observed_bins[name]),
            "positive_observation_count": sum(
                record["array"] == name for record in observations
            ),
        }
        for name in ARRAY_FIELDS
    }
    return {
        "schema": "aon-timer-array-bin-observation-audit-v1",
        "status": "VCS_REFERENCE_PARTITION_OBSERVATIONS_AUDITED_NOT_CANONICAL_VECTOR",
        "source_revision": PINNED_REVISION,
        "coverage_schema_id": corpus["coverage_schema_id"],
        "corpus_manifest_sha256": sha256_bytes(corpus_bytes),
        "array_range_catalog_sha256": range_digest,
        "input_sha256": {
            "bin_definition_catalog": sha256_bytes(definitions_bytes),
            "canonical_identity_catalog": sha256_bytes(canonical_catalog_bytes),
            "canonical_identity_list": sha256_bytes(ids_bytes),
            "coverage_schema": sha256_bytes(coverage_schema_bytes),
        },
        "historical_vcs_run_rows_read": False,
        "historical_hit_counts_imported": False,
        "verilator_partition_equivalence_verified": False,
        "canonical_vector_generated": False,
        "unknown_bins_inferred_as_misses": False,
        "trace_run_count": len(trace_evidence),
        "traced_sample_count": traced_sample_count,
        "timer_cfg_samples_audited": tested_sample_count,
        "observed_reference_array_bin_count": sum(len(value) for value in observed_bins.values()),
        "positive_observation_count": len(observations),
        "observations_by_array": counts_by_array,
        "trace_evidence": trace_evidence,
        "positive_observations": observations,
        "limitations": [
            "Observed Cocotb raw sample values are attributed using the imported VCS reference intervals.",
            "The audit does not assert Verilator/SystemVerilog coverage equivalence and does not create a Stage 06 vector.",
            "Unobserved array bins and all other canonical identities remain unknown; no misses are inferred.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-manifest", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE_DIR)
    parser.add_argument("--range-catalog", type=Path, default=DEFAULT_RANGE_CATALOG)
    parser.add_argument("--definitions", type=Path, default=DEFAULT_DEFINITIONS)
    parser.add_argument("--canonical-catalog", type=Path, default=DEFAULT_CANONICAL_CATALOG)
    parser.add_argument("--bin-ids", type=Path, default=DEFAULT_BIN_IDS)
    parser.add_argument("--coverage-schema", type=Path, default=DEFAULT_COVERAGE_SCHEMA)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit_observations(
            args.corpus_manifest,
            args.trace_dir,
            range_catalog_path=args.range_catalog,
            definitions_path=args.definitions,
            canonical_catalog_path=args.canonical_catalog,
            bin_ids_path=args.bin_ids,
            coverage_schema_path=args.coverage_schema,
        )
        output = args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        with output.open("xb") as stream:
            stream.write(raw)
        output.with_suffix(output.suffix + ".sha256").write_text(
            f"{sha256_bytes(raw)}  {output.name}\n", encoding="ascii"
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": result["status"],
        "timer_cfg_samples_audited": result["timer_cfg_samples_audited"],
        "observed_reference_array_bin_count": result["observed_reference_array_bin_count"],
        "positive_observation_count": result["positive_observation_count"],
        "canonical_vector_generated": result["canonical_vector_generated"],
        "verilator_partition_equivalence_verified": result["verilator_partition_equivalence_verified"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
