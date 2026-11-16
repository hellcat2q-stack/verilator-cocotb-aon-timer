"""Collect execution provenance for one declared fix attempt without private paths."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_root
    out = root / "public"
    cases = [json.loads((out / f"vcs-case-{i}.json").read_text()) for i in range(3)]
    first_log = (root / "case-0" / "simulation.private.log").read_text()
    versions = re.findall(r"(Compiler|Runtime) version\s+([A-Za-z0-9_.-]+)", first_log)
    metadata = {"schema": "aon-timer-fixed-reference-execution-v1",
        "reference_variant": "pinned-sampling-fixes-v1", "seed": 1,
        "testcase": "aon_timer_smoke_vseq", "process_exit_code": int((root / "runner.exit").read_text()),
        "build_exit_code": int((root / "build.exit").read_text()),
        "inputs_sha256": {p.name: sha(p) for p in sorted((root / "inputs").iterdir()) if p.is_file()},
        "collector_tool_sha256": sha(Path(__file__)),
        "private_logs_sha256": {p.name: sha(p) for p in sorted(root.glob("*.private.log"))},
        "native_versions_from_log": dict(versions),
        "cdc_disable_define_in_actual_compile_argv": "+define+DISABLE_PRIM_CDC_RAND_DELAY" in (root / "vcs-argv.private.log").read_text(),
        "cases": [{k: c[k] for k in ("case", "testcase", "seed", "process_exit_code", "run_status", "sample_invocations", "full_log_sha256")} for c in cases],
        "full_simulation_started": False, "coverage_credit_granted": 0}
    (out / "execution.json").write_text(json.dumps(metadata, indent=2) + "\n")
    probe = root / "event-probe"
    text = (probe / "simulation.private.log").read_text()
    match = re.search(r"^EVENT_WAIT_PROBE (\{.*\})$", text, re.M)
    if match is None:
        raise ValueError("Missing native event probe result")
    result = json.loads(match[1])
    result.update({"schema": "aon-timer-native-event-control-probe-v1",
        "build_exit_code": int((probe / "build.exit").read_text()),
        "process_exit_code": int((probe / "process.exit").read_text()),
        "source_sha256": sha(root / "inputs" / "event_wait_probe.sv"),
        "simv_sha256": sha(probe / "simv"),
        "build_log_sha256": sha(probe / "build.private.log"),
        "simulation_log_sha256": sha(probe / "simulation.private.log"),
        "coverage_credit_granted": 0})
    (out / "event-probe.json").write_text(json.dumps(result, indent=2) + "\n")
    fork = root / "fork-probe"
    match = re.search(r"^FORK_CLEANUP_PROBE (\{.*\})$", (fork / "simulation.private.log").read_text(), re.M)
    if match is None:
        raise ValueError("Missing fork-cleanup probe result")
    result = json.loads(match[1])
    result.update({"schema": "aon-timer-native-fork-cleanup-probe-v1",
        "build_exit_code": int((fork / "build.exit").read_text()),
        "process_exit_code": int((fork / "process.exit").read_text()),
        "source_sha256": sha(root / "inputs" / "fork_cleanup_probe.sv"),
        "simv_sha256": sha(fork / "simv"),
        "build_log_sha256": sha(fork / "build.private.log"),
        "simulation_log_sha256": sha(fork / "simulation.private.log"),
        "coverage_credit_granted": 0})
    (out / "fork-probe.json").write_text(json.dumps(result, indent=2) + "\n")
    shutil.copyfile(root / "instrumentation" / "reference-fixes.patch", out / "reference-fixes.patch")


if __name__ == "__main__":
    main()
