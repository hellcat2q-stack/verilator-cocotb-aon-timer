# Stage 10: bounded UVM/Cocotb sampling matrix

This stage extends the measured fixed-reference comparison from three cases to
eight short, deterministic cases: wakeup, bark, bite, `INTR_TEST`, prescaler,
live threshold/count update followed by restart, reset/restart, and watchdog sleep/pause with a bounded restart after wake. It uses the pinned
OpenTitan revision and the declared repaired scoreboard variant. It is a
diagnostic only: original-reference and full-matrix parity remain unverified,
and no canonical coverage credit is awarded.

The VCS runner exports and attests the pinned tree into a new scratch directory,
instruments the isolated copy, builds the eight short cases, verifies the tree
after build, and writes path-free case records into `public/`. `git` in the
inputs directory is a small compatibility shim for the school server's older
Git client. It forwards commands unchanged except for translating an initial
`git -C DIR` form. It is scoped to the runner's `PATH`. Failed attempts stay in
their original scratch directories; each retry uses a new directory.

Stage these files in a new `$RUN_ROOT/inputs/` directory: `instrument.py`,
`sample_fix_base.py`, `instrument_base.py`, `run_vcs.sh`, `git`,
`verify_source.py`, `collect_vcs.py`, `collect_matrix.py`,
`aon_timer_smoke_vseq.sv`, `event_wait_probe.sv`, `fork_cleanup_probe.sv`,
`sample-matrix.json`, `stage10-paired-short-v1.json`,
`stage10-sample-fix-v1.json`, `legacy-eda-overlay-v1.tar.gz`, and
`vcs_p2019_compat.sh`. The Git shim and runner must be executable. The overlay contains only the pinned pure-Python
FuseSoC/Edalize packages plus OpenTitan's pinned `importlib-resources` helper;
it is hash-checked in the execution record and used only through that run's
`PYTHONPATH`. The existing server Python supplies YAML, HJSON, and other EDA
dependencies. The requirements file records the source package pins.

The server's outbound DNS may be unavailable, so the checked-in overlay avoids
installing packages during a run. The runner takes `VCS_REPRO_ROOT` pointing to
the existing school-server VCS tool installation; it selects that installation's
VCS P-2019 wrapper and GCC 9.3.1 toolchain, then records their effective
versions and hashes. No shared environment is modified. For manual environment
creation when package access is available:

```bash
"$PYTHON3" -m venv "$RUN_ROOT/python-env"
"$RUN_ROOT/python-env/bin/pip" install -r "$RUN_ROOT/inputs/vcs-python-requirements.txt"
```

Use the server Python environment that already contains the OpenTitan Python
dependencies, set `VCS_REPRO_ROOT`, and run:

```bash
bash "$RUN_ROOT/inputs/run_vcs.sh" "$REFERENCE_ROOT" "$RUN_ROOT"
```

After a successful run, the script collects compact VCS results itself. Never
reuse a run directory. Preserve all exit codes and logs after failures.
The collector treats UVM error/fatal counts and the testcase pass marker as
part of each case's success condition; a zero simulator process exit alone is
not sufficient.

On WSL Ubuntu-24.04, use a clean pinned checkout and the compatible Python
environment already used by the project:

```bash
SOURCE_ROOT=/path/to/clean-pinned-opentitan \
PYTHON_ENV=/path/to/compatible-venv \
WORK_ROOT=/path/to/new-linux-run \
bash tools/stage10_sample_matrix/run_cocotb.sh /path/to/public

python3 tools/stage10_sample_parity/export_cocotb.py \
  --run-root "$WORK_ROOT" --output-dir /path/to/public

python3 -m tools.stage10_sample_matrix.audit \
  --evidence-dir /path/to/public --output /path/to/public/audit.json
```

The audit compares accepted TL inputs/responses, each captured AON edge, RTL
counters/output pins, sample tuples/times/order, required groups, and duplicate
producer events. The Cocotb timer adapter models the DUT's two-AON-edge sleep
synchronizer; the sleep case disables the first watchdog scorekeeper before
waking, then restarts from a known count. The eight cases do not resolve the 228 shared definitions, the
exact 4,507-bin identity mapping, the Stage 06 exact run matrix, or the Stage 07
paper scheduler. Passing this stage therefore does not authorize or claim the
full simulation.
