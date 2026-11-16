"""Publish compact replay evidence and normalize only XML source-file paths."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


def export_run(root: Path, out: Path) -> dict:
    out.mkdir(exist_ok=True, parents=True)
    manifest = json.loads((root / "manifest.json").read_text())
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Cocotb manifest must contain at least one case")
    case_ids = [case.get("case") for case in cases]
    if case_ids != list(range(len(cases))):
        raise ValueError("Cocotb case IDs must be contiguous and zero-based")
    if any(case.get("run_status") != "PASS" or case.get("process_exit_code") != 0
           or not case.get("xml_passed") for case in cases):
        raise ValueError("Cannot export failed Cocotb cases as successful paired evidence")
    shutil.copyfile(root / "manifest.json", out / "cocotb-manifest.json")
    exports = {"schema": "aon-timer-paired-cocotb-export-v1", "cases": []}
    for case in case_ids:
        source = root / f"case-{case}"
        target = out / f"cocotb-case-{case}"
        target.mkdir(exist_ok=False)
        for path in (source / "traces").glob("*.json"):
            shutil.copyfile(path, target / path.name)
        for name in ("replay.json", "process.exit"):
            shutil.copyfile(source / name, target / name)
        xml = ET.parse(source / "results.xml")
        for test in xml.findall(".//testcase"):
            if "file" in test.attrib:
                test.set("file", "tools/" + Path(test.get("file")).name)
        xml.write(target / "results.xml", encoding="utf-8", xml_declaration=True)
        exports["cases"].append({"case": case, "xml_transform": "Source file attribute normalized to repo-relative tools path; all result fields retained",
            "original_xml_sha256": hashlib.sha256((source / "results.xml").read_bytes()).hexdigest(),
            "public_xml_sha256": hashlib.sha256((target / "results.xml").read_bytes()).hexdigest()})
    (out / "cocotb-export.json").write_text(json.dumps(exports, indent=2) + "\n")
    return exports


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.run_root, args.output_dir
    out.mkdir(exist_ok=True, parents=True)
    export_run(root, out)


if __name__ == "__main__":
    main()
