"""Convert validated explicit-bin raw trace hits into sparse Stage 06 vectors.

Only source-confirmed named-bin hits are emitted. Every omitted canonical
identity remains unknown; this tool never infers misses from incomplete traces.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from stage06_matrix import (
        PINNED_REVISION,
        VECTOR_SCHEMA,
        load_canonical_ids,
        sha256_file,
    )
except ModuleNotFoundError:  # Support importing this file as tools.raw_trace_to_vectors.
    from tools.stage06_matrix import (
        PINNED_REVISION,
        VECTOR_SCHEMA,
        load_canonical_ids,
        sha256_file,
    )

try:
    from coverage_model import SUPPORTED_COVERAGE_SCHEMA_IDS
except ModuleNotFoundError:  # Support importing as tools.raw_trace_to_vectors.
    from tools.coverage_model import SUPPORTED_COVERAGE_SCHEMA_IDS


def convert_corpus(
    corpus_path: Path,
    trace_dir: Path,
    output_dir: Path,
    *,
    catalog_path: Path,
    ids_path: Path,
) -> dict[str, Any]:
    corpus_path = Path(corpus_path).resolve()
    trace_dir = Path(trace_dir).resolve()
    output_dir = Path(output_dir).resolve()
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    catalog, canonical_ids = load_canonical_ids(catalog_path, ids_path)
    canonical_set = set(canonical_ids)

    if corpus.get("schema") != "aon-timer-stage05-corpus-manifest-v1":
        raise ValueError("unsupported Stage 05 corpus manifest schema")
    if corpus.get("source_revision") != PINNED_REVISION:
        raise ValueError("corpus source revision does not match pinned RTL")
    if corpus.get("coverage_schema_id") not in SUPPORTED_COVERAGE_SCHEMA_IDS:
        raise ValueError("unsupported coverage schema")
    if not corpus.get("pool_id") or not corpus.get("pool_sha256"):
        raise ValueError("corpus manifest is missing frozen pool identity")
    attempts = corpus.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != corpus.get("attempt_count"):
        raise ValueError("corpus attempt list/count mismatch")

    output_dir.mkdir(parents=True, exist_ok=True)
    generated: dict[str, Any] = {}
    for attempt in attempts:
        if attempt.get("result") != "PASS":
            continue
        run_id = attempt.get("run_id")
        seed = attempt.get("seed")
        trace_summary = attempt.get("coverage_trace")
        if not isinstance(run_id, str) or not run_id or not isinstance(seed, int):
            raise ValueError("passing attempt has invalid run ID or seed")
        if not isinstance(trace_summary, dict) or trace_summary.get("validated") is not True:
            raise ValueError(f"{run_id}: partial raw trace is not validated")
        if (
            trace_summary.get("status") != "PARTIAL_SOURCE_SAMPLE_TRACE"
            or trace_summary.get("canonical_vector_generated") is not False
        ):
            raise ValueError(f"{run_id}: expected a partial trace without a canonical vector")
        trace_files = trace_summary.get("files")
        if not isinstance(trace_files, dict) or not trace_files:
            raise ValueError(f"{run_id}: no raw trace files are declared")

        occurrence_counts: Counter[str] = Counter()
        covergroup_totals: Counter[str] = Counter()
        sample_count = 0
        covered_testcases: set[str] = set()
        file_records: dict[str, Any] = {}
        for filename, declared in sorted(trace_files.items()):
            if (
                not isinstance(filename, str)
                or Path(filename).name != filename
                or "/" in filename
                or "\\" in filename
                or not isinstance(declared, dict)
            ):
                raise ValueError(f"{run_id}: invalid trace filename or declaration")
            path = trace_dir / filename
            if not path.is_file():
                raise ValueError(f"{run_id}: missing raw trace file {filename}")
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest != declared.get("sha256"):
                raise ValueError(f"{run_id}: raw trace hash mismatch for {filename}")
            trace = json.loads(raw.decode("utf-8"))
            samples = trace.get("samples")
            if not isinstance(samples, list) or len(samples) != declared.get("sample_count"):
                raise ValueError(f"{run_id}: raw trace sample count mismatch for {filename}")
            if trace.get("sample_count") != len(samples):
                raise ValueError(f"{run_id}: raw trace internal sample count mismatch for {filename}")
            if trace.get("run_id") != run_id or trace.get("seed") != seed:
                raise ValueError(f"{run_id}: raw trace run ID or seed mismatch for {filename}")
            if trace.get("source_revision") != corpus["source_revision"]:
                raise ValueError(f"{run_id}: raw trace source revision mismatch for {filename}")
            if trace.get("schema_id") != corpus["coverage_schema_id"]:
                raise ValueError(f"{run_id}: raw trace coverage schema mismatch for {filename}")
            if trace.get("canonical_bin_vector") is not None:
                raise ValueError(f"{run_id}: raw trace unexpectedly contains a vector")
            if trace.get("coverage_status") != declared.get("coverage_status"):
                raise ValueError(f"{run_id}: raw trace coverage status mismatch for {filename}")
            actual_group_counts = Counter()
            local_hit_counts: Counter[str] = Counter()
            for sample in samples:
                if not isinstance(sample, dict) or not isinstance(sample.get("covergroup"), str):
                    raise ValueError(f"{run_id}: malformed sample in {filename}")
                actual_group_counts[sample["covergroup"]] += 1
                hits = sample.get("resolved_canonical_bin_identity_hits", [])
                if not isinstance(hits, list):
                    raise ValueError(f"{run_id}: malformed identity-hit list in {filename}")
                for identity in hits:
                    if identity not in canonical_set:
                        raise ValueError(f"{run_id}: raw trace references an unknown canonical identity")
                    local_hit_counts[identity] += 1
            if dict(sorted(actual_group_counts.items())) != dict(
                sorted(declared.get("sample_counts_by_covergroup", {}).items())
            ):
                raise ValueError(f"{run_id}: covergroup sample counts mismatch for {filename}")
            if dict(sorted(actual_group_counts.items())) != dict(
                sorted(trace.get("sample_counts_by_covergroup", {}).items())
            ):
                raise ValueError(f"{run_id}: raw trace internal covergroup counts mismatch for {filename}")
            if dict(sorted(local_hit_counts.items())) != dict(
                sorted(trace.get("resolved_canonical_bin_identity_hit_counts", {}).items())
            ):
                raise ValueError(f"{run_id}: identity hits disagree with raw sample records in {filename}")
            if not isinstance(trace.get("testcase"), str) or trace["testcase"] in covered_testcases:
                raise ValueError(f"{run_id}: missing or duplicate testcase trace")
            covered_testcases.add(trace["testcase"])
            occurrence_counts.update(local_hit_counts)
            covergroup_totals.update(actual_group_counts)
            sample_count += len(samples)
            file_records[filename] = {
                "sha256": digest,
                "sample_count": len(samples),
                "resolved_explicit_identity_count": len(local_hit_counts),
                "testcase": trace["testcase"],
            }

        if sample_count != trace_summary.get("total_sample_count"):
            raise ValueError(f"{run_id}: total trace sample count mismatch")
        if len(file_records) != trace_summary.get("file_count"):
            raise ValueError(f"{run_id}: trace file count mismatch")
        if dict(sorted(covergroup_totals.items())) != dict(
            sorted(trace_summary.get("sample_counts_by_covergroup", {}).items())
        ):
            raise ValueError(f"{run_id}: corpus covergroup totals disagree with raw trace files")
        expected_testcases = {
            testcase.get("name")
            for testcase in attempt.get("testcases", [])
            if isinstance(testcase, dict)
        }
        if covered_testcases != expected_testcases:
            raise ValueError(f"{run_id}: raw trace testcase set does not match passing corpus")
        if dict(sorted(occurrence_counts.items())) != dict(
            sorted(trace_summary.get("resolved_canonical_bin_identity_hit_counts", {}).items())
        ):
            raise ValueError(f"{run_id}: corpus hit summary disagrees with raw trace files")
        if not occurrence_counts:
            raise ValueError(f"{run_id}: no validated explicit canonical-bin hits were observed")

        vector = {
            "schema": VECTOR_SCHEMA,
            "run_id": run_id,
            "source_revision": corpus["source_revision"],
            "coverage_schema_id": corpus["coverage_schema_id"],
            "pool_id": corpus["pool_id"],
            "pool_sha256": corpus["pool_sha256"],
            "seed": seed,
            "canonical_bin_count": len(canonical_ids),
            "canonical_bin_ids_sha256": catalog["canonical_bin_ids_sha256"],
            "vector_status": "PARTIAL",
            "mapping_status": "PARTIAL_VALIDATED",
            "bins": {identity: 1 for identity in sorted(occurrence_counts)},
            "bin_hit_occurrence_counts": dict(sorted(occurrence_counts.items())),
            "evidence": {
                "method": "source-confirmed named explicit-bin memberships in validated raw samples",
                "raw_sample_count": sample_count,
                "raw_trace_files": file_records,
                "unknown_policy": "all omitted identities remain unknown; no misses are inferred",
                "coverage_vector_complete": False,
            },
        }
        vector_path = output_dir / f"{run_id}.json"
        vector_path.write_text(json.dumps(vector, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        generated[run_id] = {
            "path": vector_path.name,
            "sha256": sha256_file(vector_path),
            "known_hit_count": len(occurrence_counts),
            "known_hit_occurrences": sum(occurrence_counts.values()),
            "unknown_count": len(canonical_ids) - len(occurrence_counts),
            "mapping_status": vector["mapping_status"],
        }

    if not generated:
        raise ValueError("corpus contains no passing attempts with validated raw trace hits")
    summary = {
        "schema": "aon-timer-stage06-raw-trace-conversion-v1",
        "corpus_manifest_sha256": sha256_file(corpus_path),
        "canonical_bin_count": len(canonical_ids),
        "canonical_bin_ids_sha256": catalog["canonical_bin_ids_sha256"],
        "vector_count": len(generated),
        "vectors": generated,
        "zero_misses_inferred": False,
        "coverage_vector_complete": False,
        "limitations": [
            "Only source-confirmed named explicit-bin hits are converted.",
            "Array/auto-bin partitions and unobserved sample sites are not attributed.",
            "All omitted identities remain unknown; this output is not a complete coverage vector.",
        ],
    }
    report_dir = output_dir / "reports"
    report_dir.mkdir(exist_ok=True)
    (report_dir / "conversion_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-manifest", type=Path, required=True)
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path(__file__).resolve().parents[1] / "references" / "canonical_bin_catalog.json")
    parser.add_argument("--bin-ids", type=Path, default=Path(__file__).resolve().parents[1] / "references" / "canonical_bin_ids.txt")
    args = parser.parse_args()
    try:
        result = convert_corpus(
            args.corpus_manifest,
            args.trace_dir,
            args.output_dir,
            catalog_path=args.catalog,
            ids_path=args.bin_ids,
        )
        print(json.dumps(result, indent=2))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
