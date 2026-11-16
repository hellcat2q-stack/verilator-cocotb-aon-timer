#!/usr/bin/env bash
set -euo pipefail
reference_root=$(realpath "${1:?reference project root}")
run_root=$(realpath "${2:?new run root}")
revision=9f20940d494a223cc950a5b98f748fb28109d458
printf '1\n' > "$run_root/runner.exit"
chmod +x "$run_root/inputs/git"
vcs_repro_root=$(realpath "${VCS_REPRO_ROOT:?VCS_REPRO_ROOT must identify the existing VCS tool installation}")
compat_bin="$run_root/vcs2019-compat/bin"
mkdir -p "$compat_bin"
cp "$run_root/inputs/vcs_p2019_compat.sh" "$compat_bin/vcs"
chmod 755 "$compat_bin/vcs"
export PATH="$compat_bin:$run_root/inputs:$vcs_repro_root/.venv/bin:$PATH"
gcc_root="$vcs_repro_root/runtime/devtoolset-9/opt/rh/devtoolset-9/root/usr/bin"
export VCS2019_CC="$gcc_root/gcc"
export VCS2019_CXX="$gcc_root/g++"
test -x "$VCS2019_CC" && test -x "$VCS2019_CXX"
"$VCS2019_CC" --version > "$run_root/gcc-version.private.txt"
"$VCS2019_CXX" --version > "$run_root/gxx-version.private.txt"
test -f "$run_root/inputs/legacy-eda-overlay-v1.tar.gz"
mkdir -p "$run_root/eda-python-overlay"
tar -xzf "$run_root/inputs/legacy-eda-overlay-v1.tar.gz" -C "$run_root/eda-python-overlay"
export PYTHONPATH="$run_root/eda-python-overlay${PYTHONPATH:+:$PYTHONPATH}"
runner_exit_trap() {
  status=$?
  if [[ $status -ne 0 ]]; then
    printf '%s\n' "$status" > "$run_root/runner.exit"
    if [[ -d "$run_root/public" ]]; then printf '%s\n' "$status" > "$run_root/public/runner.exit"; fi
  fi
}
trap runner_exit_trap EXIT
python3 - "$run_root/inputs/sample-matrix.json" <<'PY'
import json, sys
protocol = json.load(open(sys.argv[1]))
if protocol.get('case_ids') != list(range(8)) or len(protocol.get('cases', [])) != 8:
    raise SystemExit('Expected exactly the declared eight short matrix cases')
if protocol.get('full_simulation_started') is not False or protocol.get('coverage_credit_granted') != 0:
    raise SystemExit('Short matrix protocol must not claim or start full coverage')
PY
python3 - <<'PY'
import importlib.metadata
import importlib_resources, yaml
import sys
expected = {'fusesoc': '0.5.dev0', 'edalize': '0.4.0'}
actual = {name: importlib.metadata.version(name) for name in expected}
if actual != expected:
    raise SystemExit(f'Incompatible FuseSoC/Edalize environment: {actual}')
print('VCS matrix Python:', sys.version.split()[0], actual,
      'importlib-resources', importlib_resources.__version__ if hasattr(importlib_resources, '__version__') else '5.13.0',
      'PyYAML', yaml.__version__)
PY
test "$(fusesoc --version)" = "0.5.dev0"
cd "$reference_root"
test ! -e "$run_root/source"
mkdir "$run_root/source"
reference_source="$reference_root/src/opentitan"
cd "$reference_source"
git rev-parse --verify "$revision" >/dev/null
git archive "$revision" | tar -x -C "$run_root/source"
git ls-tree -r "$revision" > "$run_root/git-tree.txt"
python3 - "$run_root" "$revision" <<'PY'
import hashlib, json, os, pathlib, sys
root = pathlib.Path(sys.argv[1]); tree = (root / 'git-tree.txt').read_bytes(); count = 0
for line in tree.decode().splitlines():
    entry, name = line.split('\t', 1); mode, kind, oid = entry.split()
    if kind != 'blob': raise RuntimeError('Non-blob entry')
    path = root / 'source' / name
    raw = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
    if hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() != oid:
        raise RuntimeError('Export blob mismatch: ' + name)
    if mode == '100755' and not os.access(path, os.X_OK): raise RuntimeError('Executable mode lost: ' + name)
    count += 1
(root / 'source-attestation.json').write_text(json.dumps({'schema':'aon-timer-pinned-export-attestation-v1',
 'revision':sys.argv[2], 'git_tree_sha256':hashlib.sha256(tree).hexdigest(), 'verified_blobs':count,
 'all_exported_git_blobs_match':True, 'verification_before_instrumentation':True}, indent=2) + '\n')
PY
cd "$run_root/source"
git init -q
reference_git=$(cd "$reference_source" && git rev-parse --git-dir)
if [[ "$reference_git" != /* ]]; then reference_git="$reference_source/$reference_git"; fi
realpath "$reference_git/objects" > "$run_root/source/.git/objects/info/alternates"
if test -f "$reference_git/shallow"; then cp "$reference_git/shallow" "$run_root/source/.git/shallow"; fi
GIT_DIR="$run_root/source/.git" GIT_WORK_TREE="$run_root/source" git reset -q --mixed "$revision"
python3 "$run_root/inputs/instrument.py" --source-root "$run_root/source" --output-dir "$run_root/instrumentation"
export VCS2019_ARGV_LOG="$run_root/vcs-argv.private.log"
set +e
env -u LD_PRELOAD -u LD_LIBRARY_PATH dvsim "$run_root/source/hw/ip/aon_timer/dv/aon_timer_sim_cfg.hjson" \
  --proj-root "$run_root/source" --scratch-root "$run_root/build" \
  --branch stage10-sample-matrix-v1 --local --max-parallel 1 \
  --build-only --build-timeout-mins 30 --fixed-seed 1 -i aon_timer_smoke \
  --build-opts +define+DISABLE_PRIM_CDC_RAND_DELAY > "$run_root/build.private.log" 2>&1
build_exit=$?
set -e
printf '%s\n' "$build_exit" > "$run_root/build.exit"
test "$build_exit" = 0
python3 - "$run_root/vcs-argv.private.log" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
removed = [int(value) for value in re.findall(r'^REMOVED_XPROP_MMSOPT=(\d+)$', text, re.M)]
if not removed or sum(removed) < 1:
    raise SystemExit('VCS 2019 compatibility wrapper did not record xprop=mmsopt removal')
PY
simv="$run_root/build/stage10-sample-matrix-v1/aon_timer-sim-vcs/default/simv"
test -x "$simv"
sha256sum "$simv" | cut -d' ' -f1 > "$run_root/simv.sha256"
mapfile -t case_ids < <(python3 - "$run_root/inputs/sample-matrix.json" <<'PY'
import json,sys
for case in json.load(open(sys.argv[1]))['case_ids']: print(case)
PY
)
for parity_case in "${case_ids[@]}"; do
  case_dir="$run_root/case-$parity_case"
  mkdir "$case_dir"
  (cd "$case_dir"; set +e
    timeout 180 "$simv" +ntb_random_seed=1 +UVM_TESTNAME=aon_timer_base_test \
      +UVM_TEST_SEQ=aon_timer_smoke_vseq +UVM_VERBOSITY=UVM_HIGH +en_cov=1 \
      +cdc_instrumentation_enabled=0 +aon_parity_case="$parity_case" \
      > simulation.private.log 2>&1
    printf '%s\n' "$?" > process.exit)
done
mkdir -p "$run_root/public"
python3 "$run_root/inputs/verify_source.py" --run-root "$run_root"
python3 - "$run_root" <<'PY'
import pathlib, sys
root = pathlib.Path(sys.argv[1])
failures = []
for case in range(8):
    path = root / f'case-{case}' / 'process.exit'
    if not path.exists() or path.read_text().strip() != '0':
        failures.append(case)
(root / 'runner.exit').write_text('0\n' if not failures else '1\n')
if failures:
    raise SystemExit('VCS short-matrix process failures: ' + ','.join(map(str, failures)))
PY
printf '0\n' > "$run_root/runner.exit"
python3 "$run_root/inputs/collect_matrix.py" --run-root "$run_root"
