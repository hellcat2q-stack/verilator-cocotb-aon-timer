#!/usr/bin/env bash
# Run from the reference project's root with its compatibility environment exported.
# New workspace only. Never reuse simv, source, or experiment output directories.
set -euo pipefail
reference_root=$(realpath "${1:?reference project root}")
run_root=$(realpath "${2:?new workspace containing inputs/}")
revision=9f20940d494a223cc950a5b98f748fb28109d458
cd "$reference_root"
test ! -e "$run_root/source"
mkdir "$run_root/source"
git -C src/opentitan archive "$revision" | tar -x -C "$run_root/source"
git -C src/opentitan ls-tree -r "$revision" > "$run_root/git-tree.txt"
python3 - "$run_root" "$revision" <<'PY'
import hashlib, json, os, pathlib, sys
root = pathlib.Path(sys.argv[1])
tree = (root / 'git-tree.txt').read_bytes()
count = 0
for line in tree.decode().splitlines():
    entry, name = line.split('\t', 1)
    mode, kind, oid = entry.split()
    if kind != 'blob':
        raise RuntimeError('Non-blob entry requires explicit handling: ' + name)
    path = root / 'source' / name
    raw = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
    actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if actual != oid:
        raise RuntimeError('Export blob mismatch: ' + name)
    if mode == '100755' and not os.access(path, os.X_OK):
        raise RuntimeError('Executable mode lost: ' + name)
    count += 1
(root / 'source-attestation.json').write_text(json.dumps({
    'schema': 'aon-timer-pinned-export-attestation-v1',
    'revision': sys.argv[2], 'git_tree_sha256': hashlib.sha256(tree).hexdigest(),
    'verified_blobs': count, 'all_exported_git_blobs_match': True,
    'verification_before_instrumentation': True
}, indent=2) + '\n')
PY
# DVSIM queries Git metadata. Read the existing local object database through
# alternates (the server's old Git cannot fetch from a shallow repository).
# Source files and Git refs/index remain isolated; no reference objects are written.
git -C "$run_root/source" init -q
reference_git=$(git -C "$reference_root/src/opentitan" rev-parse --git-dir)
if [[ "$reference_git" != /* ]]; then reference_git="$reference_root/src/opentitan/$reference_git"; fi
realpath "$reference_git/objects" > "$run_root/source/.git/objects/info/alternates"
if test -f "$reference_git/shallow"; then cp "$reference_git/shallow" "$run_root/source/.git/shallow"; fi
git -C "$run_root/source" reset -q --mixed "$revision"
python3 "$run_root/inputs/instrument.py" --source-root "$run_root/source" --output-dir "$run_root/instrumentation"
export VCS2019_ARGV_LOG="$run_root/vcs-argv.private.log"
set +e
dvsim "$run_root/source/hw/ip/aon_timer/dv/aon_timer_sim_cfg.hjson" \
  --proj-root "$run_root/source" --scratch-root "$run_root/build" \
  --branch stage10-sample-parity --local --max-parallel 1 \
  --build-only --build-timeout-mins 30 --fixed-seed 1 -i aon_timer_smoke \
  --build-opts +define+DISABLE_PRIM_CDC_RAND_DELAY > "$run_root/build.private.log" 2>&1
build_exit=$?
set -e
printf '%s\n' "$build_exit" > "$run_root/build.exit"
test "$build_exit" = 0
simv="$run_root/build/stage10-sample-parity/aon_timer-sim-vcs/default/simv"
test -x "$simv"
sha256sum "$simv" | cut -d' ' -f1 > "$run_root/simv.sha256"
for parity_case in 0 1 2; do
  case_dir="$run_root/case-$parity_case"
  mkdir "$case_dir"
  (
    cd "$case_dir"
    set +e
    timeout 120 "$simv" +ntb_random_seed=1 +UVM_TESTNAME=aon_timer_base_test \
      +UVM_TEST_SEQ=aon_timer_smoke_vseq +UVM_VERBOSITY=UVM_HIGH +en_cov=1 \
      +cdc_instrumentation_enabled=0 +aon_parity_case="$parity_case" \
      > simulation.private.log 2>&1
    printf '%s\n' "$?" > process.exit
  )
done
