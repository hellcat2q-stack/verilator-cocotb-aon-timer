#!/usr/bin/env bash
# Replay each compact UVM record against an independent pinned Verilator build.
set -euo pipefail
project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
source_root=${SOURCE_ROOT:?clean pinned OpenTitan checkout}
python_env=${PYTHON_ENV:?compatible Cocotb/FuseSoC environment}
work_root=${WORK_ROOT:?new run directory on Linux filesystem}
input_root=$(realpath "${1:?directory containing vcs-case-0/1/2.json}")
test ! -e "$work_root"
test "$(git -C "$source_root" rev-parse HEAD)" = 9f20940d494a223cc950a5b98f748fb28109d458
git -C "$source_root" diff --quiet HEAD
source "$python_env/bin/activate"
export PATH="$python_env/bin:$PATH"
test "$(fusesoc --version)" = 0.5.dev0
test "$(cocotb-config --version)" = 1.9.2
[[ "$(verilator --version)" == 'Verilator 5.020'* ]]
mkdir -p "$work_root/fusesoc"
fusesoc --cores-root="$source_root" --cores-root="$project_root/tools" \
  run --target=default --tool=verilator --setup --build-root="$work_root/fusesoc" \
  lowrisc:ip:aon_timer > "$work_root/fusesoc.log" 2>&1
mapfile -t lists < <(find "$work_root/fusesoc" -name lowrisc_ip_aon_timer_0.1.vc)
test "${#lists[@]}" = 1
build_dir=$(dirname "${lists[0]}")
sed -E '/^--Mdir( |$)/d; /^--top-module( |$)/d; /^--(cc|exe|lint-only)$/d' \
  "${lists[0]}" > "$build_dir/aon_timer_sources.vc"
export RANDOM_SEED=1
export TESTCASE=replay_uvm_accepted_stimulus
for parity_case in 0 1 2; do
  case_root="$work_root/case-$parity_case"
  mkdir -p "$case_root/traces"
  export RUN_ID="stage10-sample-fix-v1-case-$parity_case"
  export COVERAGE_TRACE_DIR="$case_root/traces"
  export UVM_REPLAY_INPUT="$input_root/vcs-case-$parity_case.json"
  export UVM_REPLAY_OUTPUT="$case_root/replay.json"
  set +e
  (cd "$build_dir"; make -f "$project_root/tools/AonMakefile" MODULE=test_uvm_sample_fix_replay sim) > "$case_root/simulation.log" 2>&1
  exit_code=$?
  set -e
  printf '%s\n' "$exit_code" > "$case_root/process.exit"
  if test -f "$build_dir/results.xml"; then cp "$build_dir/results.xml" "$case_root/results.xml"; fi
done
python - "$work_root" "$project_root" "$source_root" <<'PY'
import hashlib, importlib.metadata, json, pathlib, subprocess, sys, xml.etree.ElementTree as ET
root, project, source = map(pathlib.Path, sys.argv[1:])
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
tools = {name: sha(project / name) for name in (
    'tools/test_uvm_sample_fix_replay.py', 'tools/pinned_sampling_fixed_adapter.py',
    'tools/test_uvm_sample_replay.py', 'configs/stage10-sample-fix-v1.json', 'tools/cocotb_coverage_adapter.py', 'tools/coverage_model.py',
    'tools/aon_timer_tb.sv', 'tools/AonMakefile', 'configs/stage10-paired-short-v1.json')}
source_files = ['hw/ip/aon_timer/rtl/aon_timer.sv', 'hw/ip/aon_timer/rtl/aon_timer_core.sv',
                'hw/ip/aon_timer/dv/env/aon_timer_scoreboard.sv']
manifest = {'schema': 'aon-timer-paired-fixed-cocotb-run-v1', 'source_revision': subprocess.check_output(
    ['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip(),
    'source_clean': True, 'reference_variant': 'pinned-sampling-fixes-v1', 'source_hashes': {name: sha(source / name) for name in source_files},
    'tools_sha256': tools, 'seed': 1, 'coverage_vector': None, 'coverage_credit_granted': 0,
    'full_simulation_started': False, 'cases': [], 'toolchain': {
    'python': sys.version.split()[0], 'cocotb': importlib.metadata.version('cocotb'),
    'fusesoc': importlib.metadata.version('fusesoc'), 'edalize': importlib.metadata.version('edalize'),
    'verilator': subprocess.check_output(['verilator', '--version'], text=True).strip()}}
for case in range(3):
    folder = root / f'case-{case}'
    xml = folder / 'results.xml'
    tests = ET.parse(xml).findall('.//testcase') if xml.exists() else []
    code = int((folder / 'process.exit').read_text())
    passed = len(tests) == 1 and all(t.find('failure') is None and t.find('error') is None for t in tests)
    files = [p for p in folder.rglob('*') if p.is_file()]
    manifest['cases'].append({'case': case, 'testcase': 'replay_uvm_accepted_stimulus', 'seed': 1,
        'process_exit_code': code, 'tests_run': len(tests), 'xml_passed': passed,
        'run_status': 'PASS' if code == 0 and passed else 'FAIL',
        'files_sha256': {str(p.relative_to(folder)): sha(p) for p in files}})
(root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
PY
