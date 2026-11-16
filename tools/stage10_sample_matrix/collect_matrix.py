"""Collect eight v2 matrix runs into compact path-free evidence."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_root
    out = root / "public"
    out.mkdir(exist_ok=True)
    for name in ("source-attestation.json", "simv.sha256", "build.exit", "runner.exit"):
        if (root / name).exists(): (out / name).write_bytes((root / name).read_bytes())
    for name in ("instrumentation.json", "instrumentation.patch", "reference-fixes.patch"):
        path = root / "instrumentation" / name
        if path.exists(): (out / name).write_bytes(path.read_bytes())
    post_build = root / "post-build-source.json"
    if post_build.exists():
        (out / "post-build-source.json").write_bytes(post_build.read_bytes())
    cases = []
    for case in range(8):
        path = root / f"case-{case}" / "simulation.private.log"
        raw = path.read_bytes()
        text = raw.decode(errors="replace")
        records, controls, invalid = [], [], []
        for line in text.splitlines():
            if line.startswith("AON_PARITY "):
                marker = re.sub(r":([xXzZ]+)(?=[,}])", ":null", line[len("AON_PARITY "):])
                try: records.append(json.loads(marker))
                except ValueError: invalid.append(marker)
            match = re.search(r"UVM_INFO\s+@\s+(\d+)\s+ps:.*?(WKUP|WDOG Bark|WDOG Bite) Timer (count:\s*(\d+)|expired check for interrupts)", line)
            if match:
                row = {"time_ps":int(match[1]),"label":match[2],"kind":"count" if match[4] else "expiry"}
                if match[4]: row["count"] = int(match[4])
                controls.append(row)
        err = re.findall(r"^\s*UVM_ERROR\s*:\s*(\d+)\s*$", text, re.M)
        fatal = re.findall(r"^\s*UVM_FATAL\s*:\s*(\d+)\s*$", text, re.M)
        result = {"schema":"aon-timer-vcs-actual-samples-v1","case":case,
            "testcase":"aon_timer_smoke_vseq","seed":1,
            "process_exit_code":int((path.parent/"process.exit").read_text()),
            "uvm_error_count":int(err[-1]) if err else None,"uvm_fatal_count":int(fatal[-1]) if fatal else None,
            "test_passed_checks":"TEST PASSED CHECKS" in text,"records":records,
            "control_events":controls,"invalid_markers":invalid,
            "sample_invocations":sum(r["kind"]=="sample" for r in records),
            "coverage_vector":None,"coverage_credit_granted":0,"full_log_sha256":sha(path)}
        result["run_status"]="PASS" if result["process_exit_code"]==0 and result["uvm_error_count"]==0 and result["uvm_fatal_count"]==0 and result["test_passed_checks"] and not invalid else "FAIL"
        (out/f"vcs-case-{case}.json").write_text(json.dumps(result,indent=2)+"\n")
        cases.append({k:result[k] for k in ("case","testcase","seed","process_exit_code","run_status","sample_invocations","full_log_sha256")})
    failed = [case["case"] for case in cases if case["run_status"] != "PASS"]
    if failed:
        raise SystemExit("VCS UVM/check failures in short-matrix cases: " + ",".join(map(str, failed)))
    first=(root/"case-0"/"simulation.private.log").read_text()
    versions=dict(re.findall(r"(Compiler|Runtime) version\s+([A-Za-z0-9_.-]+)",first))
    import subprocess, sys
    argv_log=root/"vcs-argv.private.log"
    compat_text=argv_log.read_text()
    removed_xprop=[int(x) for x in re.findall(r"^REMOVED_XPROP_MMSOPT=(\d+)$",compat_text,re.M)]
    if not removed_xprop or sum(removed_xprop)<1:
        raise ValueError("VCS compatibility wrapper did not record the xprop adjustment")
    compat_execs=re.findall(r"^EXEC=(.*)$",compat_text,re.M)
    execution={"schema":"aon-timer-sample-matrix-execution-v1","reference_variant":"pinned-sampling-fixes-v2",
        "seed":1,"build_exit_code":int((root/"build.exit").read_text()),
        "runner_exit_code":int((root/"runner.exit").read_text()),
        "eda_overlay_archive_sha256":sha(root/"inputs"/"legacy-eda-overlay-v1.tar.gz"),
        "vcs_compatibility":{"wrapper_sha256":sha(root/"inputs"/"vcs_p2019_compat.sh"),
            "logged_invocation_count":len(compat_execs),"xprop_mmsopt_flags_removed":sum(removed_xprop),
            "gcc_version":(root/"gcc-version.private.txt").read_text().splitlines()[0],
            "gxx_version":(root/"gxx-version.private.txt").read_text().splitlines()[0]},
        "eda_python_toolchain":{"python":sys.version.split()[0],
            "fusesoc":importlib.metadata.version("fusesoc"),
            "edalize":importlib.metadata.version("edalize"),
            "fusesoc_cli":subprocess.check_output(["fusesoc","--version"],text=True).strip()},
        "toolchain_versions":versions,"cases":cases,
        "inputs_sha256":{p.name:sha(p) for p in sorted((root/"inputs").iterdir()) if p.is_file()},
        "private_logs_sha256":{p.name:sha(p) for p in sorted(root.glob("*.private.log"))},
        "full_simulation_started":False,"coverage_credit_granted":0}
    (out/"execution.json").write_text(json.dumps(execution,indent=2)+"\n")


if __name__ == "__main__": main()
