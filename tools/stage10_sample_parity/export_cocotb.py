"""Publish compact replay evidence and normalize only XML source-file paths."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.run_root, args.output_dir
    out.mkdir(exist_ok=True, parents=True)
    shutil.copyfile(root / "manifest.json", out / "cocotb-manifest.json")
    exports = {"schema": "aon-timer-paired-cocotb-export-v1", "cases": []}
    for case in range(3):
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


if __name__ == "__main__":
    main()
