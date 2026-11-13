#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
source_root="${SOURCE_ROOT:?Set SOURCE_ROOT to the independent pinned OpenTitan source copy}"
work_root="${WORK_ROOT:-$project_root/build/stage04}"
python_env="${PYTHON_ENV:-$project_root/build/stage02/python-env}"
fusesoc_root="$work_root/fusesoc-ot"
build_log="$work_root/fusesoc_setup.log"
run_id="${RUN_ID:-stage04-$(date -u +%Y%m%dT%H%M%SZ)-seed${RANDOM_SEED:-1}}"
seed="${RANDOM_SEED:-1}"
exit_code=99
result="NOT_RUN"
tests_run=0
tests_passed=0
tests_failed=0
simulation_time_ns=0.0
failed_testcases="[]"
results_xml=""
coverage_trace_dir="${COVERAGE_TRACE_DIR:-$work_root/coverage-traces}"

mkdir -p "$work_root"
mkdir -p "$coverage_trace_dir"
export COVERAGE_TRACE_DIR="$coverage_trace_dir"
export RUN_ID="$run_id"

write_manifest() {
  local shell_status="$1"
  if [[ "$exit_code" == "99" ]]; then
    exit_code="$shell_status"
    result="FAILED"
  fi
  python3 - "$work_root/run_manifest.json" "$run_id" "$seed" "$exit_code" "$result" \
    "$source_root" "$results_xml" "$coverage_trace_dir" <<'PY'
import json
import hashlib
import pathlib
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
import xml.etree.ElementTree as ET

target, run_id, seed, exit_code, result, source_root, report_path, trace_dir = sys.argv[1:]
tests = []
simulation_time_ns = 0.0
if report_path and pathlib.Path(report_path).is_file():
    root = ET.parse(report_path).getroot()
    tests = root.findall(".//testcase")
    simulation_time_ns = sum(float(test.get("sim_time_ns", "0")) for test in tests)
failed_tests = [test.get("name", "unknown") for test in tests if test.find("failure") is not None or test.find("error") is not None]
tests_run = len(tests)
tests_failed = len(failed_tests)
tests_passed = tests_run - tests_failed
trace_files = {}
for trace_path in sorted(pathlib.Path(trace_dir).glob("*.json")):
    trace_bytes = trace_path.read_bytes()
    trace = json.loads(trace_bytes.decode("utf-8"))
    trace_files[trace_path.name] = {
        "sha256": hashlib.sha256(trace_bytes).hexdigest(),
        "sample_count": trace.get("sample_count"),
        "sample_counts_by_covergroup": trace.get("sample_counts_by_covergroup", {}),
        "coverage_status": trace.get("coverage_status"),
    }
try:
    actual_revision = subprocess.check_output(
        ["git", "-C", source_root, "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
    ).strip()
except (OSError, subprocess.CalledProcessError):
    actual_revision = None
def tool_version(command, fallback):
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return fallback
def package_version(name):
    try:
        return version(name)
    except PackageNotFoundError:
        return None
verilator_output = tool_version(["verilator", "--version"], "")
verilator_version = next((part for part in verilator_output.split() if part[0:1].isdigit()), None)
manifest = {
    "schema": "aon-timer-stage04-run-v1",
    "run_id": run_id,
    "source_revision": actual_revision,
    "expected_source_revision": "9f20940d494a223cc950a5b98f748fb28109d458",
    "coverage_schema_id": "aon_timer_uvm_source_trace_v2",
    "test_module": "test_sequences",
    "testcases": [
        "aon_timer_smoke_sequence",
        "aon_timer_jump_sequence",
        "aon_timer_prescaler_sequence",
        "aon_timer_intr_test_sequence",
    ],
    "seed": int(seed),
    "randomized_stimulus": False,
    "exit_code": int(exit_code),
    "result": "PASS" if exit_code == "0" and tests_run > 0 and tests_failed == 0 else "FAIL",
    "tests_run": tests_run,
    "tests_passed": tests_passed,
    "tests_failed": tests_failed,
    "failed_testcases": failed_tests,
    "simulation_time_ns": round(simulation_time_ns, 3),
    "toolchain": {
        "python": sys.version.split()[0],
        "cocotb": tool_version(["cocotb-config", "--version"], None),
        "verilator": verilator_version,
        "fusesoc": package_version("fusesoc"),
        "edalize": package_version("edalize"),
    },
    "coverage_vector": None,
    "coverage_trace": {
        "status": "PARTIAL_SOURCE_SAMPLE_TRACE" if trace_files else "UNAVAILABLE",
        "canonical_vector_generated": False,
        "files": trace_files,
    },
    "note": "This run validates functional checks and captures a partial raw sample trace; no 4,507-bin vector is produced.",
}
pathlib.Path(target).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PY
}
trap 'write_manifest "$?"' EXIT

if [[ ! -x "$python_env/bin/fusesoc" || ! -x "$python_env/bin/cocotb-config" ]]; then
  echo "Stage 04 Python environment not found at $python_env" >&2
  echo "Run tools/setup_stage02_env.sh first or set PYTHON_ENV." >&2
  exit 2
fi
if [[ ! -f "$source_root/hw/ip/aon_timer/aon_timer.core" ]]; then
  echo "SOURCE_ROOT does not contain the pinned OpenTitan source tree" >&2
  exit 2
fi
source_revision="$(git -C "$source_root" rev-parse HEAD 2>/dev/null || true)"
if [[ "$source_revision" != "9f20940d494a223cc950a5b98f748fb28109d458" ]]; then
  echo "SOURCE_ROOT must be the isolated pinned revision 9f20940d494a223cc950a5b98f748fb28109d458" >&2
  exit 2
fi

export PATH="$python_env/bin:$PATH"
source "$python_env/bin/activate"
export RANDOM_SEED="$seed"
for tool in fusesoc verilator cocotb-config make; do
  command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 2; }
done
[[ "$(fusesoc --version)" == "0.5.dev0" ]] || {
  echo "Expected OpenTitan-compatible FuseSoC 0.5.dev0; got $(fusesoc --version)" >&2
  exit 2
}
[[ "$(cocotb-config --version)" == "1.9.2" ]] || {
  echo "Expected Cocotb 1.9.2; got $(cocotb-config --version)" >&2
  exit 2
}
[[ "$(verilator --version)" == "Verilator 5.020"* ]] || {
  echo "Expected Verilator 5.020; got $(verilator --version)" >&2
  exit 2
}

mkdir -p "$fusesoc_root"
if ! fusesoc --cores-root="$source_root" --cores-root="$project_root/tools" \
  run --target=default --tool=verilator --setup --build-root="$fusesoc_root" \
  lowrisc:ip:aon_timer >"$build_log" 2>&1; then
  cat "$build_log"
  exit 1
fi

mapfile -t vc_files < <(find "$fusesoc_root" -type f -name 'lowrisc_ip_aon_timer_0.1.vc' -print)
if [[ "${#vc_files[@]}" -ne 1 ]]; then
  echo "Expected one FuseSoC Verilator file list under $fusesoc_root; found ${#vc_files[@]}" >&2
  exit 3
fi
build_dir="$(dirname "${vc_files[0]}")"
results_xml="$work_root/results.xml"
sed -E '/^--Mdir( |$)/d; /^--top-module( |$)/d; /^--(cc|exe|lint-only)$/d' \
  "${vc_files[0]}" > "$build_dir/aon_timer_sources.vc"

set +e
(
  cd "$build_dir"
  make -f "$project_root/tools/AonMakefile" MODULE=test_sequences sim
) 2>&1 | tee "$work_root/stage04.log"
exit_code="${PIPESTATUS[0]}"
if [[ -f "$build_dir/results.xml" ]]; then
  cp "$build_dir/results.xml" "$results_xml"
fi
set -e
if [[ "$exit_code" == "0" && -f "$results_xml" ]] && \
  python3 - "$results_xml" <<'PY'
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
tests = root.findall(".//testcase")
raise SystemExit(0 if tests and all(t.find("failure") is None and t.find("error") is None for t in tests) else 1)
PY
then
  result="PASS"
else
  if [[ "$exit_code" == "0" ]]; then exit_code=1; fi
  result="FAIL"
fi
exit "$exit_code"
