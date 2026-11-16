"""Export compact, path-free actual-call evidence; full logs remain on server."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def parse_log(text: str) -> dict:
    records, controls, invalid = [], [], []
    for line in text.splitlines():
        if line.startswith("AON_PARITY "):
            raw = line[len("AON_PARITY "):]
            # Four-state reset values remain unknown, never become zero.
            normalized = re.sub(r":([xXzZ]+)(?=[,}])", ":null", raw)
            try:
                records.append(json.loads(normalized))
            except ValueError:
                invalid.append(raw)
        match = re.search(r"UVM_INFO\s+@\s+(\d+)\s+ps:.*?(WKUP|WDOG Bark|WDOG Bite) Timer (count:\s*(\d+)|expired check for interrupts)", line)
        if match:
            record = {"time_ps": int(match[1]), "label": match[2], "kind": "count" if match[4] else "expiry"}
            if match[4]:
                record["count"] = int(match[4])
            controls.append(record)
    errors = re.findall(r"^\s*UVM_ERROR\s*:\s*(\d+)\s*$", text, re.M)
    fatals = re.findall(r"^\s*UVM_FATAL\s*:\s*(\d+)\s*$", text, re.M)
    return {"schema": "aon-timer-vcs-actual-samples-v1", "records": records,
            "control_events": controls, "invalid_markers": invalid,
            "uvm_error_count": int(errors[-1]) if errors else None,
            "uvm_fatal_count": int(fatals[-1]) if fatals else None,
            "test_passed_checks": "TEST PASSED CHECKS" in text,
            "sample_invocations": sum(r["kind"] == "sample" for r in records)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_root
    out = root / "public"
    out.mkdir(exist_ok=False)
    for name in ("source-attestation.json", "simv.sha256", "build.exit", "runner.exit"):
        path = root / name
        if path.exists():
            (out / name).write_bytes(path.read_bytes())
    for name in ("instrumentation.json", "instrumentation.patch"):
        path = root / "instrumentation" / name
        if path.exists():
            (out / name).write_bytes(path.read_bytes())
    for case in range(3):
        log = root / f"case-{case}" / "simulation.private.log"
        if not log.exists():
            continue
        raw = log.read_bytes()
        payload = parse_log(raw.decode(errors="replace"))
        payload.update({"case": case, "seed": 1, "testcase": "aon_timer_smoke_vseq",
                        "process_exit_code": int(log.with_name("process.exit").read_text()),
                        "full_log_sha256": hashlib.sha256(raw).hexdigest(),
                        "coverage_vector": None, "coverage_credit_granted": 0})
        payload["run_status"] = "PASS" if (payload["process_exit_code"] == 0 and
            payload["uvm_error_count"] == 0 and payload["uvm_fatal_count"] == 0 and
            payload["test_passed_checks"] and not payload["invalid_markers"] and
            payload["sample_invocations"] > 0) else "FAIL"
        (out / f"vcs-case-{case}.json").write_text(json.dumps(payload, indent=2) + "\n")
    build_log = root / "build.private.log"
    argv_log = root / "vcs-argv.private.log"
    tool_info = {"vcs": "P-2019.06-SP1", "build_log_sha256": hashlib.sha256(build_log.read_bytes()).hexdigest() if build_log.exists() else None,
                 "compatibility_argv_log_sha256": hashlib.sha256(argv_log.read_bytes()).hexdigest() if argv_log.exists() else None,
                 "compatibility": "Existing wrapper removes unsupported xprop=mmsopt/cm_common_hier; no scoring fixes",
                 "requested_build_option": "+define+DISABLE_PRIM_CDC_RAND_DELAY",
                 "private_paths_exported": False}
    (out / "toolchain.json").write_text(json.dumps(tool_info, indent=2) + "\n")


if __name__ == "__main__":
    main()
