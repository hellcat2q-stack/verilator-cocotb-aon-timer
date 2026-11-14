#!/usr/bin/env python3
"""Audit whether the conditional CIP reset coverage is active for AON Timer.

The pinned AON Timer environment declares ``num_edn`` but does not assign it.
This audit records the relevant source hashes and searches the pinned DV tree
for an override.  It deliberately does not inspect generated simulator output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


REQUIRED_FILES = (
    "hw/dv/sv/cip_lib/cip_base_env_cfg.sv",
    "hw/ip/aon_timer/dv/env/aon_timer_env_cfg.sv",
    "hw/dv/sv/cip_lib/cip_base_env_cov.sv",
    "hw/dv/sv/cip_lib/cip_base_scoreboard.sv",
)
PINNED_REVISION = "9f20940d494a223cc950a5b98f748fb28109d458"
PINNED_HASHES = dict(zip(REQUIRED_FILES, (
    "e0782c3656a30ca21f403e0412dc51d63de11bf5a730c83cc8eaec99a75ecad0",
    "8820a5f9ce33b77a9c5285de5b7e7c74058ba7a66777e1251bd288a2bf12035f",
    "e542fde933e1c99e9ccb3a91484ab347b43e407a7058166cffb48a5f2c4c9f48",
    "e9b9e6736cb3f367bb1a411a848effba2106da22fa1838a7f966641484631939",
)))

DECLARATION_RE = re.compile(r"\buint\s+num_edn\s*;")
ASSIGNMENT_RE = re.compile(r"\bnum_edn\s*=")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_source_files(source_root: Path) -> list[Path]:
    roots = (
        source_root / "hw" / "ip" / "aon_timer" / "dv",
        source_root / "hw" / "dv" / "sv" / "cip_lib",
    )
    files: set[Path] = set()
    for root in roots:
        if root.exists():
            files.update(path for path in root.rglob("*.sv") if path.is_file())
    return sorted(files)


def audit_source_tree(source_root: Path, source_revision: str = "unknown") -> dict[str, Any]:
    source_root = source_root.resolve()
    try:
        actual_revision = subprocess.check_output(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True,
            stderr=subprocess.DEVNULL).strip()
        clean_checkout = not subprocess.check_output(
            ["git", "-C", str(source_root), "status", "--porcelain"], text=True,
            stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.SubprocessError):
        actual_revision, clean_checkout = None, False
    file_records: list[dict[str, Any]] = []
    missing: list[str] = []
    texts: dict[str, str] = {}
    for relative in REQUIRED_FILES:
        path = source_root / relative
        if not path.is_file():
            missing.append(relative)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        texts[relative] = text
        file_records.append({"path": relative, "sha256": sha256_file(path)})

    override_sites: list[dict[str, Any]] = []
    for path in _relative_source_files(source_root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if ASSIGNMENT_RE.search(line):
                override_sites.append(
                    {
                        "path": path.relative_to(source_root).as_posix(),
                        "line": line_number,
                        "text": line.strip(),
                    }
                )

    declaration_present = bool(DECLARATION_RE.search(texts.get(REQUIRED_FILES[0], "")))
    env_cfg_no_assignment = not bool(ASSIGNMENT_RE.search(texts.get(REQUIRED_FILES[1], "")))
    coverage_guard_present = "if (cfg.num_edn) resets_cg" in texts.get(REQUIRED_FILES[2], "")
    sampling_guard_present = "if (cfg.num_edn && cfg.en_cov)" in texts.get(REQUIRED_FILES[3], "")
    mismatched_hashes = [record["path"] for record in file_records
                         if record["sha256"] != PINNED_HASHES[record["path"]]]
    provenance_verified = (source_revision == actual_revision == PINNED_REVISION
                           and clean_checkout and not missing and not mismatched_hashes)
    applicable = (provenance_verified and declaration_present and env_cfg_no_assignment
                  and not override_sites and coverage_guard_present and sampling_guard_present)
    status = "NOT_APPLICABLE_NUM_EDN_ZERO" if applicable else "REQUIRES_RUNTIME_CONFIG_AUDIT"

    return {
        "schema": "aon-timer-conditional-reset-audit-v2",
        "source_revision": source_revision,
        "actual_source_revision": actual_revision,
        "clean_checkout": clean_checkout,
        "source_provenance_verified": provenance_verified,
        "mismatched_source_hashes": mismatched_hashes,
        "status": status,
        "conditional_reset_covergroup": "resets_cg",
        "num_edn": {
            "declaration": "uint num_edn;",
            "declaration_present": declaration_present,
            "aon_timer_env_assignment_present": not env_cfg_no_assignment,
            "override_sites": override_sites,
            "interpretation": (
                "The pinned AON Timer config leaves the 2-state uint at its default zero; "
                "no assignment was found in the AON Timer or CIP DV source trees."
            ),
        },
        "guards": {
            "covergroup_instantiation": "if (cfg.num_edn) resets_cg = new(\"dut_and_edn_rsts\");",
            "covergroup_instantiation_present": coverage_guard_present,
            "sample_task_guard": "if (cfg.num_edn && cfg.en_cov)",
            "sample_task_guard_present": sampling_guard_present,
        },
        "source_files": file_records,
        "missing_files": missing,
        "search_scope": [
            "hw/ip/aon_timer/dv/**/*.sv",
            "hw/dv/sv/cip_lib/**/*.sv",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-revision", default="unknown")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_source_tree(args.source_root, args.source_revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output)}, sort_keys=True))
    return 0 if result["status"] == "NOT_APPLICABLE_NUM_EDN_ZERO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
