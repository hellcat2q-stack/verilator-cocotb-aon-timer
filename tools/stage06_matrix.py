"""Build an auditable tri-state canonical-bin-by-run matrix.

Cells are 1 (observed hit), 0 (observed miss), or ? (unknown/not collected).
Missing coverage data is never silently converted to an uncovered bin, and
failed runs never contribute coverage credit.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "references" / "canonical_bin_catalog.json"
BIN_IDS_PATH = ROOT / "references" / "canonical_bin_ids.txt"
MATRIX_SCHEMA = "aon-timer-stage06-matrix-v1"
VECTOR_SCHEMA = "aon-timer-stage06-run-vector-v1"
PINNED_REVISION = "9f20940d494a223cc950a5b98f748fb28109d458"
METADATA_COLUMNS = [
    "run_id",
    "source_revision",
    "pool_id",
    "pool_sha256",
    "seed",
    "exit_code",
    "result",
    "simulation_time_ns",
    "vector_status",
    "known_hit_count",
    "known_miss_count",
    "unknown_count",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_canonical_ids(
    catalog_path: Path = CATALOG_PATH, ids_path: Path = BIN_IDS_PATH
) -> tuple[dict[str, Any], list[str]]:
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    ids_bytes = Path(ids_path).read_bytes()
    ids = ids_bytes.decode("utf-8").splitlines()
    actual_hash = hashlib.sha256(ids_bytes).hexdigest()
    if catalog.get("schema") != "aon-timer-canonical-bin-catalog-v1":
        raise ValueError("unsupported canonical bin catalog schema")
    if actual_hash != catalog.get("canonical_bin_ids_sha256"):
        raise ValueError("canonical identity list SHA-256 differs from its catalog")
    if len(ids) != catalog.get("canonical_bin_count"):
        raise ValueError("canonical identity count differs from its catalog")
    if len(ids) != len(set(ids)):
        raise ValueError("canonical identity list contains duplicates")
    return catalog, ids


def load_run_vector(
    path: Path,
    *,
    run_id: str,
    source_revision: str,
    coverage_schema_id: str,
    pool_id: str,
    pool_sha256: str,
    seed: int,
    canonical_ids: list[str],
    identity_sha256: str,
) -> tuple[dict[str, str], str, str | None]:
    vector = json.loads(Path(path).read_text(encoding="utf-8"))
    if vector.get("schema") != VECTOR_SCHEMA:
        raise ValueError(f"{path}: unsupported run-vector schema")
    if vector.get("run_id") != run_id:
        raise ValueError(f"{path}: vector run_id does not match corpus attempt")
    if vector.get("source_revision") != source_revision:
        raise ValueError(f"{path}: vector source revision does not match run")
    if vector.get("coverage_schema_id") != coverage_schema_id:
        raise ValueError(f"{path}: vector coverage schema does not match corpus")
    if vector.get("pool_id") != pool_id or vector.get("pool_sha256") != pool_sha256:
        raise ValueError(f"{path}: vector frozen pool identity does not match corpus")
    if vector.get("seed") != seed:
        raise ValueError(f"{path}: vector seed does not match corpus attempt")
    if vector.get("canonical_bin_count") != len(canonical_ids):
        raise ValueError(f"{path}: vector canonical bin count does not match catalog")
    if vector.get("canonical_bin_ids_sha256") != identity_sha256:
        raise ValueError(f"{path}: vector identity-list SHA-256 does not match catalog")
    mapping_status = vector.get("mapping_status")
    if mapping_status not in {"PARTIAL_VALIDATED", "EXACT_VALIDATED"}:
        raise ValueError(f"{path}: mapping_status must explicitly state validated mapping")
    if mapping_status == "EXACT_VALIDATED" and vector.get("vector_status") != "COMPLETE":
        raise ValueError(f"{path}: exact mapping must have vector_status=COMPLETE")

    raw_bins = vector.get("bins")
    if not isinstance(raw_bins, dict):
        raise ValueError(f"{path}: bins must be a mapping from canonical IDs to 0/1")
    canonical_set = set(canonical_ids)
    extra = set(raw_bins) - canonical_set
    if extra:
        raise ValueError(f"{path}: unknown canonical identity: {sorted(extra)[0]}")
    if vector.get("vector_status") == "COMPLETE" and set(raw_bins) != canonical_set:
        raise ValueError(f"{path}: complete vector must include every canonical identity")
    if vector.get("vector_status") not in {"PARTIAL", "COMPLETE"}:
        raise ValueError(f"{path}: vector_status must be PARTIAL or COMPLETE")
    if not raw_bins:
        raise ValueError(f"{path}: a vector must include at least one known bin")

    bins: dict[str, str] = {}
    for identity, value in raw_bins.items():
        if value not in (0, 1) or isinstance(value, bool):
            raise ValueError(f"{path}: bin values must be integer 0 or 1")
        bins[identity] = str(value)

    return bins, vector["vector_status"], mapping_status


def build_matrix(
    corpus_path: Path,
    *,
    vector_dir: Path | None = None,
    catalog_path: Path = CATALOG_PATH,
    ids_path: Path = BIN_IDS_PATH,
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    corpus_path = Path(corpus_path).resolve()
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    catalog, canonical_ids = load_canonical_ids(catalog_path, ids_path)
    if corpus.get("schema") != "aon-timer-stage05-corpus-manifest-v1":
        raise ValueError("unsupported corpus manifest schema")
    if corpus.get("source_revision") != PINNED_REVISION:
        raise ValueError("corpus manifest source revision does not match pinned RTL")
    if corpus.get("coverage_schema_id") != "aon_timer_uvm_source_trace_v1":
        raise ValueError("corpus manifest references an unsupported coverage schema")
    if not corpus.get("pool_id") or not corpus.get("pool_sha256"):
        raise ValueError("corpus manifest is missing frozen pool identity")
    attempts = corpus.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != corpus.get("attempt_count"):
        raise ValueError("corpus attempt list/count mismatch")

    identity_sha256 = catalog["canonical_bin_ids_sha256"]
    vector_dir = Path(vector_dir).resolve() if vector_dir else None
    matrix_rows: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    for attempt in attempts:
        run_id = attempt.get("run_id")
        if not isinstance(run_id, str) or not run_id or run_id in seen_run_ids:
            raise ValueError("corpus run IDs must be non-empty and unique")
        seen_run_ids.add(run_id)
        result = attempt.get("result")
        if result not in {"PASS", "FAIL"}:
            raise ValueError(f"{run_id}: result must be PASS or FAIL")
        if not isinstance(attempt.get("seed"), int) or attempt["seed"] < 0:
            raise ValueError(f"{run_id}: invalid seed")
        if result == "PASS" and attempt.get("shell_exit_code") != 0:
            raise ValueError(f"{run_id}: PASS result requires shell_exit_code=0")
        if result == "PASS" and (
            attempt.get("tests_run", 0) <= 0
            or attempt.get("tests_passed") != attempt.get("tests_run")
            or attempt.get("tests_failed") != 0
        ):
            raise ValueError(f"{run_id}: PASS result requires all testcase outcomes to pass")

        observed: dict[str, str] = {}
        vector_status = "UNAVAILABLE"
        mapping_status = None
        vector_path = vector_dir / f"{run_id}.json" if vector_dir else None
        if vector_path and vector_path.is_file():
            observed, vector_status, mapping_status = load_run_vector(
                vector_path,
                run_id=run_id,
                source_revision=corpus["source_revision"],
                coverage_schema_id=corpus["coverage_schema_id"],
                pool_id=corpus["pool_id"],
                pool_sha256=corpus["pool_sha256"],
                seed=attempt["seed"],
                canonical_ids=canonical_ids,
                identity_sha256=identity_sha256,
            )
        elif vector_path:
            vector_status = "MISSING"

        # No reward for failed runs: preserve their attempt row, but mask all bins.
        if result != "PASS":
            observed = {}
            vector_status = "FAILED_RUN_EXCLUDED"
            mapping_status = None

        cells = {identity: observed.get(identity, "?") for identity in canonical_ids}
        counts = Counter(cells.values())
        matrix_rows.append({
            "metadata": {
                "run_id": run_id,
                "source_revision": corpus["source_revision"],
                "pool_id": corpus["pool_id"],
                "pool_sha256": corpus["pool_sha256"],
                "seed": attempt["seed"],
                "exit_code": attempt.get("shell_exit_code"),
                "result": result,
                "simulation_time_ns": round(float(attempt.get("simulation_time_ns", 0.0)), 3),
                "vector_status": vector_status,
                "known_hit_count": counts["1"],
                "known_miss_count": counts["0"],
                "unknown_count": counts["?"],
            },
            "cells": cells,
            "vector_path": str(vector_path) if vector_path and vector_path.is_file() else None,
            "vector_sha256": sha256_file(vector_path) if vector_path and vector_path.is_file() else None,
            "mapping_status": mapping_status,
        })

    if vector_dir is not None and vector_dir.is_dir():
        orphaned_vectors = {path.stem for path in vector_dir.glob("*.json")} - seen_run_ids
        if orphaned_vectors:
            raise ValueError(f"vector directory contains unknown run_id: {sorted(orphaned_vectors)[0]}")

    # Union is known only where at least one hit was observed. Missing cells never count as misses.
    union_hits = {
        identity
        for identity in canonical_ids
        if any(row["cells"][identity] == "1" for row in matrix_rows)
    }
    successful_rows = [row for row in matrix_rows if row["metadata"]["result"] == "PASS"]
    union_unknown = {
        identity
        for identity in canonical_ids
        if identity not in union_hits
        and (
            not successful_rows
            or any(row["cells"][identity] == "?" for row in successful_rows)
        )
    }
    union_known_uncovered = set(canonical_ids) - union_hits - union_unknown
    all_known = all(row["metadata"]["unknown_count"] == 0 for row in matrix_rows)
    matrix_status = "COMPLETE" if matrix_rows and all_known else (
        "EMPTY" if not matrix_rows else "PARTIAL_OR_UNAVAILABLE"
    )
    if matrix_status == "COMPLETE" and any(
        row["mapping_status"] != "EXACT_VALIDATED" for row in matrix_rows if row["metadata"]["result"] == "PASS"
    ):
        matrix_status = "PARTIAL_OR_UNAVAILABLE"

    audit = {
        "schema": "aon-timer-stage06-matrix-audit-v1",
        "matrix_generator_sha256": sha256_file(Path(__file__)),
        "matrix_status": matrix_status,
        "canonical_bin_count_expected": 4507,
        "canonical_bin_count_observed": len(canonical_ids),
        "canonical_bin_ids_sha256": identity_sha256,
        "corpus_manifest_sha256": sha256_file(corpus_path),
        "pool_id": corpus["pool_id"],
        "pool_sha256": corpus["pool_sha256"],
        "source_revision": corpus["source_revision"],
        "run_count": len(matrix_rows),
        "pass_run_count": sum(row["metadata"]["result"] == "PASS" for row in matrix_rows),
        "failed_run_count": sum(row["metadata"]["result"] == "FAIL" for row in matrix_rows),
        "run_ids_unique": len(seen_run_ids) == len(matrix_rows),
        "rows_have_4507_cells": all(len(row["cells"]) == 4507 for row in matrix_rows),
        "cell_domain_valid": all(value in {"0", "1", "?"} for row in matrix_rows for value in row["cells"].values()),
        "failed_run_coverage_credit": 0,
        "rows": [row["metadata"] | {
            "vector_sha256": row["vector_sha256"],
            "mapping_status": row["mapping_status"],
        } for row in matrix_rows],
        "union": {
            "covered_bin_count": len(union_hits),
            "known_uncovered_bin_count": len(union_known_uncovered),
            "unknown_bin_count": len(union_unknown),
            "covered_bin_ids": [identity for identity in canonical_ids if identity in union_hits],
        },
        "limitations": [
            "Unknown cells are not treated as uncovered.",
            "Failed runs remain in the matrix but receive no coverage credit.",
            "A full matrix requires a validated vector for every successful run and exact mapping_status.",
        ],
    }
    return canonical_ids, matrix_rows, audit


def write_outputs(
    canonical_ids: list[str], rows: list[dict[str, Any]], audit: dict[str, Any], out_dir: Path
) -> dict[str, str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix_path = out_dir / "coverage_bin_by_run.csv"
    audit_path = out_dir / "coverage_matrix_audit.json"
    with matrix_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=METADATA_COLUMNS + canonical_ids)
        writer.writeheader()
        for row in rows:
            writer.writerow(row["metadata"] | row["cells"])
    audit["matrix_csv_sha256"] = sha256_file(matrix_path)
    audit["matrix_header_column_count"] = len(METADATA_COLUMNS) + len(canonical_ids)
    audit["matrix_identity_column_count"] = len(canonical_ids)
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"matrix_csv": str(matrix_path), "audit_json": str(audit_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-manifest", type=Path, required=True)
    parser.add_argument("--vector-dir", type=Path, help="Optional directory containing <run_id>.json run vectors")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        ids, rows, audit = build_matrix(args.corpus_manifest, vector_dir=args.vector_dir)
        paths = write_outputs(ids, rows, audit, args.out_dir)
        report = {
            "matrix_status": audit["matrix_status"],
            "runs": audit["run_count"],
            "canonical_columns": audit["canonical_bin_count_observed"],
            "union_covered_bins": audit["union"]["covered_bin_count"],
            "union_unknown_bins": audit["union"]["unknown_bin_count"],
            **paths,
        }
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if audit["rows_have_4507_cells"] and audit["cell_domain_valid"] else 1)
    except (OSError, ValueError, json.JSONDecodeError, KeyError, csv.Error) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
