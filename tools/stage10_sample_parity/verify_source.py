"""Verify all pinned source blobs after the build, allowing only the declared patch."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_root
    changes = json.loads((root / "instrumentation" / "instrumentation.json").read_text())["files"]
    allowed = {r["path"]: r["after_sha256"] for r in changes}
    count = 0
    for line in (root / "git-tree.txt").read_text().splitlines():
        metadata, name = line.split("\t", 1)
        mode, kind, oid = metadata.split()
        if kind != "blob":
            raise ValueError("Unexpected non-blob entry")
        path = root / "source" / name
        raw = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
        if name in allowed:
            actual = hashlib.sha256(raw).hexdigest()
            if actual != allowed[name]:
                raise ValueError("Declared file changed during build: " + name)
        elif hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() != oid:
            raise ValueError("Undeclared pinned source change: " + name)
        count += 1
    result = {"schema": "aon-timer-pinned-post-build-verification-v1",
        "verification_tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_blob_count": count, "all_source_blobs_match_except_declared_patch": True,
        "declared_changed_files": changes}
    (root / "public" / "post-build-source.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
