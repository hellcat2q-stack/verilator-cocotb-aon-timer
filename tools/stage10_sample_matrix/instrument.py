"""Build the v2 short matrix as a declared pinned-source reference variant."""
from __future__ import annotations
import argparse
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

SCOREBOARD = "hw/ip/aon_timer/dv/env/aon_timer_scoreboard.sv"
SEQUENCE = "hw/ip/aon_timer/dv/env/seq_lib/aon_timer_smoke_vseq.sv"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    fix_path = Path(__file__).with_name("sample_fix_base.py")
    fix = load_module("stage10_sample_fix_base", fix_path)
    argv = sys.argv
    sys.argv = [str(fix_path), "--source-root", str(args.source_root), "--output-dir", str(args.output_dir)]
    try:
        fix.main()
    finally:
        sys.argv = argv
    before = {SCOREBOARD: (args.source_root / SCOREBOARD).read_text(),
              SEQUENCE: (args.source_root / SEQUENCE).read_text()}

    scoreboard = before[SCOREBOARD]
    reset_body = '''  virtual function void reset(string kind = "HARD");
    super.reset(kind);
    wkup_en = 0;
    wkup_num_update_due = 0;
    wkup_count = 0;
    prescaler = 0;
    wkup_thold = 0;
    wdog_en = 0;
    wdog_regwen = 1;
    wdog_pause_in_sleep = 0;
    wdog_num_update_due = 0;
    wdog_count = 0;
    bark_thold = 0;
    bite_thold = 0;
    wkup_cause = 0;
    wkup_num = 0;
    wdog_bark_num = 0;
    wdog_bite_num = 0;
    foreach (intr_status_exp[i]) intr_status_exp[i] = 0;
    wdog_rst_req_exp = 0;
  endfunction'''
    original_reset = '''  virtual function void reset(string kind = "HARD");
    super.reset(kind);
    // reset local fifos queues and variables
  endfunction'''
    if scoreboard.count(original_reset) != 1:
        raise ValueError("Pinned scoreboard reset context changed")
    scoreboard = scoreboard.replace(original_reset, reset_body, 1)
    args.source_root.joinpath(SCOREBOARD).write_text(scoreboard)
    seq = Path(__file__).with_name("aon_timer_smoke_vseq.sv").read_text()
    args.source_root.joinpath(SEQUENCE).write_text(seq)

    manifest_path = args.output_dir / "instrumentation.json"
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["files"]:
        path = entry["path"]
        entry["after_sha256"] = hashlib.sha256((args.source_root / path).read_bytes()).hexdigest()
    manifest.update({"schema": "aon-timer-pinned-sample-matrix-instrumentation-v1",
        "reference_variant": "pinned-sampling-fixes-v2",
        "reference_logic_fixes": ["reset-fork-isolation", "wakeup-high-word-read", "named-event-wait", "reset-local-scoreboard-state"],
        "matrix_protocol_sha256": hashlib.sha256(Path(__file__).with_name("sample-matrix.json").read_bytes()).hexdigest(),
        "wakeup_low_word_double_read_preserved": False,
        "matrix_testcase_source_sha256": hashlib.sha256(args.source_root.joinpath(SEQUENCE).read_bytes()).hexdigest(),
        "matrix_instrument_tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "sample_fix_instrument_tool_sha256": hashlib.sha256(fix_path.read_bytes()).hexdigest()})
    full_patch = []
    for entry in manifest["files"]:
        path = entry["path"]
        original = subprocess.check_output(["git", "-C", str(args.source_root), "show", "HEAD:" + path]).decode()
        actual = args.source_root.joinpath(path).read_text()
        full_patch.extend(difflib.unified_diff(original.splitlines(True), actual.splitlines(True), fromfile="a/" + path, tofile="b/" + path))
    (args.output_dir / "instrumentation.patch").write_text("".join(full_patch))
    fixes = []
    for path, original in before.items():
        actual = args.source_root.joinpath(path).read_text()
        fixes.extend(difflib.unified_diff(original.splitlines(True), actual.splitlines(True), fromfile="before/" + path, tofile="matrix/" + path))
    (args.output_dir / "reference-fixes.patch").write_text("".join(fixes))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
