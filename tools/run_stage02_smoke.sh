#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
source_root="${SOURCE_ROOT:?Set SOURCE_ROOT to the extracted pinned OpenTitan source root}"
work_root="${WORK_ROOT:-$project_root/build/stage02}"
python_env="${PYTHON_ENV:-$work_root/python-env}"
fusesoc_root="$work_root/fusesoc-ot"
build_log="$work_root/fusesoc_setup.log"

mkdir -p "$work_root"
if [[ ! -x "$python_env/bin/fusesoc" || ! -x "$python_env/bin/cocotb-config" ]]; then
  echo "Stage 02 Python environment not found at $python_env" >&2
  echo "Run tools/setup_stage02_env.sh first." >&2
  exit 2
fi

export PATH="$python_env/bin:$PATH"
source "$python_env/bin/activate"
export RANDOM_SEED="${RANDOM_SEED:-1}"
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
[[ -f "$source_root/hw/ip/aon_timer/aon_timer.core" ]] || {
  echo "SOURCE_ROOT does not contain the pinned OpenTitan source tree: $source_root" >&2
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

# Cocotb supplies the executable top and its own --cc/--exe settings.
sed -E '/^--Mdir( |$)/d; /^--top-module( |$)/d; /^--(cc|exe|lint-only)$/d' \
  "${vc_files[0]}" > "$build_dir/aon_timer_sources.vc"

(
  cd "$build_dir"
  make -f "$project_root/tools/AonMakefile" sim
) 2>&1 | tee "$work_root/smoke.log"
