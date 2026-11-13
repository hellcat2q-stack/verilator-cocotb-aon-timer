#!/usr/bin/env python3
"""Audit timer_cfg array-bin partitions against the pinned SV declarations.

This checks the source declaration, the imported VCS interval catalog, and the
Python/Cocotb endpoint classifier.  It does not claim that Verilator executes
SystemVerilog covergroups; native simulator coverage equivalence remains a
separate question.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

try:
    from audit_array_bin_observations import locate_array_bin
except ModuleNotFoundError:  # Support importing as tools.audit_array_bin_partition.
    from tools.audit_array_bin_observations import locate_array_bin


PINNED_REVISION = "9f20940d494a223cc950a5b98f748fb28109d458"
EXPECTED_SOURCE_SHA256 = "c0ec937d68c335e2d05760268ce161eca1a40e7f8e50546156c0589882ed9b45"
ARRAYS = {
    "prescale": {"count": 32, "domain": [1, 4095]},
    "bark": {"count": 32, "domain": [1, (1 << 32) - 1]},
    "bite": {"count": 32, "domain": [1, (1 << 32) - 1]},
    "wkup": {"count": 64, "domain": [1, (1 << 64) - 1]},
}
DECLARATION_RE = re.compile(r"bins\s+(prescale|bark|bite|wkup)\[(\d+)\]\s*=\s*\{\[1:\$\]\};")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_partition(low: int, high: int, count: int) -> list[list[int]]:
    if count <= 0 or low > high:
        raise ValueError("invalid partition arguments")
    quotient, remainder = divmod(high - low + 1, count)
    ranges: list[list[int]] = []
    cursor = low
    for ordinal in range(count):
        size = quotient if ordinal < count - 1 else quotient + remainder
        ranges.append([cursor, cursor + size - 1])
        cursor += size
    return ranges


def _source_declarations(source_text: str) -> dict[str, int]:
    declarations = {name: int(count) for name, count in DECLARATION_RE.findall(source_text)}
    if declarations != {name: spec["count"] for name, spec in ARRAYS.items()}:
        raise ValueError(f"unexpected timer_cfg array declarations: {declarations}")
    return declarations


def audit_partition(source_file: Path, range_catalog: dict[str, Any]) -> dict[str, Any]:
    source_file = Path(source_file).resolve()
    source_hash = sha256_file(source_file)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise ValueError("coverage source hash does not match the pinned revision")
    declarations = _source_declarations(source_file.read_text(encoding="utf-8"))
    if range_catalog.get("source_revision") != PINNED_REVISION:
        raise ValueError("array range catalog does not match the pinned revision")

    array_results: dict[str, dict[str, Any]] = {}
    for name, spec in ARRAYS.items():
        expected = expected_partition(spec["domain"][0], spec["domain"][1], spec["count"])
        actual_records = range_catalog.get("arrays", {}).get(name)
        if not isinstance(actual_records, list):
            raise ValueError(f"missing array range records for {name}")
        actual = [record.get("value_range") for record in sorted(actual_records, key=lambda r: r.get("ordinal", -1))]
        if actual != expected:
            raise ValueError(f"{name}: VCS reference ranges differ from the even partition model")

        probes: list[tuple[int, int | None]] = []
        for ordinal, bounds in enumerate(expected):
            for value in (bounds[0], bounds[1]):
                record = locate_array_bin(name, value, actual_records)
                probes.append((value, record["ordinal"] if record else None))
                if (record["ordinal"] if record else None) != ordinal:
                    raise ValueError(f"{name}[{ordinal}]: endpoint classifier mismatch at {value}")
            for value in (bounds[0] - 1, bounds[1] + 1):
                record = locate_array_bin(name, value, actual_records)
                expected_ordinal = ordinal - 1 if value == bounds[0] - 1 and ordinal else None
                if value == bounds[1] + 1 and ordinal + 1 < len(expected):
                    expected_ordinal = ordinal + 1
                probes.append((value, record["ordinal"] if record else None))
                if (record["ordinal"] if record else None) != expected_ordinal:
                    raise ValueError(f"{name}[{ordinal}]: endpoint classifier mismatch at {value}")
        array_results[name] = {
            "source_bin_count": declarations[name],
            "domain": spec["domain"],
            "partition_rule": "equal contiguous bins; remainder is assigned to the final bin",
            "partition_matches_reference": True,
            "endpoint_probe_count": len(probes),
            "endpoint_probes_passed": len(probes),
        }

    return {
        "schema": "aon-timer-array-bin-partition-audit-v1",
        "status": "SOURCE_PARTITION_AND_PYTHON_CLASSIFIER_VERIFIED",
        "source_revision": PINNED_REVISION,
        "source_file": "hw/ip/aon_timer/dv/env/aon_timer_env_cov.sv",
        "source_file_sha256": source_hash,
        "array_range_catalog_sha256": hashlib.sha256(
            json.dumps(range_catalog, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "arrays": array_results,
        "python_classifier_partition_verified": True,
        "native_verilator_systemverilog_coverage_verified": False,
        "limitations": [
            "The audit verifies source-declared equal partitions and the Python/Cocotb endpoint classifier.",
            "Verilator does not execute the original SystemVerilog covergroups here; native VCS/Verilator coverage equivalence is not claimed.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-file", type=Path, required=True)
    parser.add_argument("--range-catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    range_catalog = json.loads(Path(args.range_catalog).read_text(encoding="utf-8"))
    result = audit_partition(args.source_file, range_catalog)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
