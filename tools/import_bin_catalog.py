"""Extract the frozen canonical bin identities from the Stage 06 CSV header."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IDS = ROOT / "references" / "canonical_bin_ids.txt"
DEFAULT_CATALOG = ROOT / "references" / "canonical_bin_catalog.json"
BIN_HEADER_OFFSET = 14  # 13 run fields followed by report_id.


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_bin_ids(csv_path: Path, manifest_path: Path) -> tuple[list[str], dict[str, Any]]:
    csv_path = Path(csv_path)
    manifest_path = Path(manifest_path)
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    csv_hash = sha256_file(csv_path)

    if manifest.get("schema") != "aon-timer-stage06-bin-manifest-v1":
        raise ValueError("unsupported Stage 06 manifest schema")
    if csv_hash != manifest.get("csv_sha256"):
        raise ValueError("coverage CSV SHA-256 does not match the Stage 06 manifest")

    with csv_path.open(encoding="utf-8", newline="") as stream:
        header = next(csv.reader(stream), None)
    if header is None or len(header) <= BIN_HEADER_OFFSET:
        raise ValueError("coverage CSV has no canonical-bin columns")
    if header[BIN_HEADER_OFFSET - 1] != "report_id":
        raise ValueError("coverage CSV metadata layout differs from the frozen format")

    bin_ids = header[BIN_HEADER_OFFSET:]
    expected_count = manifest.get("bin_count")
    if len(bin_ids) != expected_count:
        raise ValueError(f"expected {expected_count} bins, found {len(bin_ids)}")
    if any(not item for item in bin_ids):
        raise ValueError("canonical bin identity cannot be empty")
    if len(set(bin_ids)) != len(bin_ids):
        raise ValueError("canonical bin identities are not unique")

    return bin_ids, {
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "csv_sha256": csv_hash,
        "manifest": manifest,
    }


def write_catalog(
    bin_ids: list[str], source: dict[str, Any], ids_path: Path, catalog_path: Path
) -> dict[str, Any]:
    ids_path = Path(ids_path)
    catalog_path = Path(catalog_path)
    ids_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    ids_path.write_text("\n".join(bin_ids) + "\n", encoding="utf-8", newline="\n")

    manifest = source["manifest"]
    scope_counts = Counter(item.split("::", 1)[0] for item in bin_ids)
    aon_count = sum(count for scope, count in scope_counts.items() if scope == "aon_timer_env_pkg")
    catalog = {
        "schema": "aon-timer-canonical-bin-catalog-v1",
        "status": "IDENTITIES_ENUMERATED_VALUE_PARTITIONS_UNMAPPED",
        "canonical_bin_count": len(bin_ids),
        "identity_format": "<scope>||<variable_or_cross>||<item>||<bin_name>||<instance_index>",
        "manifest_bin_key_format": manifest["bin_key_format"],
        "identity_order": "original coverage_bin_by_run.csv header order",
        "canonical_bin_ids_file": ids_path.name,
        "canonical_bin_ids_sha256": sha256_file(ids_path),
        "source": {
            "repository": "https://github.com/hellcat2q-stack/opentitan-aon-timer-paper-method-repro",
            "manifest_path": "06_覆盖数据转换/evidence/bin_manifest.json",
            "manifest_sha256": source["manifest_sha256"],
            "matrix_header_path": "06_覆盖数据转换/evidence/coverage_bin_by_run.csv",
            "matrix_csv_sha256": source["csv_sha256"],
            "note": "Only the canonical identity header was imported; historical run data was not copied.",
        },
        "scope_counts": dict(sorted(scope_counts.items())),
        "aon_timer_scope_bin_count": aon_count,
        "shared_or_other_scope_bin_count": len(bin_ids) - aon_count,
        "value_partition_boundaries_available": False,
        "value_partition_note": "The source catalog freezes bin labels/identities but does not include the value ranges for bins[] or auto_bin_max partitions.",
    }
    catalog_path.write_text(
        json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path, help="Stage 06 coverage_bin_by_run.csv")
    parser.add_argument("--manifest", required=True, type=Path, help="Stage 06 bin_manifest.json")
    parser.add_argument("--ids-output", type=Path, default=DEFAULT_IDS)
    parser.add_argument("--catalog-output", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args()

    bin_ids, source = extract_bin_ids(args.csv, args.manifest)
    catalog = write_catalog(bin_ids, source, args.ids_output, args.catalog_output)
    print(
        f"catalogued {catalog['canonical_bin_count']} unique identities; "
        f"AON Timer scope={catalog['aon_timer_scope_bin_count']}; "
        f"other scopes={catalog['shared_or_other_scope_bin_count']}"
    )
    print(f"identity list SHA-256: {catalog['canonical_bin_ids_sha256']}")


if __name__ == "__main__":
    main()
