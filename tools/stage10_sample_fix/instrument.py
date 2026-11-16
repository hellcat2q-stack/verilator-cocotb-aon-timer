"""Create a declared minimal reference fix variant after frozen baseline instrumentation."""
from __future__ import annotations
import argparse
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError("Reference patch context is not unique")
    return text.replace(old, new, 1)


def fix_scoreboard(text: str) -> str:
    start = text.index("  virtual task check_interrupt();")
    end = text.index("  endtask : check_interrupt", start) + len("  endtask : check_interrupt")
    replacement = '''  virtual task check_interrupt();
    forever begin
      wait (!under_reset);
      fork
        begin : isolation_fork
          fork
            wait (under_reset);
            run_wkup_timer();
            run_wdog_bark_timer();
            run_wdog_bite_timer();
          join_any
          // Only this child's timer descendants are killed on reset.
          disable fork;
        end
      join
    end
  endtask : check_interrupt'''
    text = text[:start] + replacement + text[end:]
    text = replace_once(text,
        "csr_rd(.ptr(ral.wkup_count_lo), .value(rtl_count[63:32]), .backdoor(1));",
        "csr_rd(.ptr(ral.wkup_count_hi), .value(rtl_count[63:32]), .backdoor(1));")
    if text.count("@(sample_coverage.triggered);") != 3:
        raise ValueError("Expected three original event-property waits")
    text = text.replace("@(sample_coverage.triggered);", "@(sample_coverage);")
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    # When staged on the server, the frozen base is adjacent under this name.
    base_path = Path(__file__).with_name("instrument_base.py")
    if not base_path.exists():
        base_path = Path(__file__).parents[1] / "stage10_sample_parity" / "instrument.py"
    spec = importlib.util.spec_from_file_location("frozen_instrument", base_path)
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    original_argv = sys.argv
    sys.argv = [str(base_path), "--source-root", str(args.source_root), "--output-dir", str(args.output_dir)]
    try:
        base.main()
    finally:
        sys.argv = original_argv
    scoreboard = args.source_root / base.SCOREBOARD
    before_fix = scoreboard.read_text()
    updated = fix_scoreboard(before_fix)
    scoreboard.write_text(updated)
    manifest_path = args.output_dir / "instrumentation.json"
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["files"]:
        if entry["path"] == base.SCOREBOARD:
            entry["after_sha256"] = hashlib.sha256(scoreboard.read_bytes()).hexdigest()
    manifest["schema"] = "aon-timer-pinned-sample-fix-instrumentation-v1"
    manifest["reference_variant"] = "pinned-sampling-fixes-v1"
    manifest["reference_logic_fixes"] = ["reset-fork-isolation", "wakeup-high-word-read", "named-event-wait"]
    manifest["wakeup_low_word_double_read_preserved"] = False
    manifest["base_instrument_tool_sha256"] = hashlib.sha256(base_path.read_bytes()).hexdigest()
    manifest["fix_instrument_tool_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    patch = []
    for entry in manifest["files"]:
        path = entry["path"]
        baseline = subprocess.check_output(["git", "-C", str(args.source_root), "show", "HEAD:" + path]).decode()
        contents = (args.source_root / path).read_text()
        patch.extend(difflib.unified_diff(baseline.splitlines(True), contents.splitlines(True), fromfile="a/" + path, tofile="b/" + path))
    (args.output_dir / "instrumentation.patch").write_text("".join(patch))
    (args.output_dir / "reference-fixes.patch").write_text("".join(difflib.unified_diff(
        before_fix.splitlines(True), updated.splitlines(True), fromfile="instrumented-original/scoreboard.sv", tofile="fixed/scoreboard.sv")))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
