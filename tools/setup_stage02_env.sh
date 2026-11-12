#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
work_root="${WORK_ROOT:-$project_root/build/stage02}"
python_env="${PYTHON_ENV:-$work_root/python-env}"

command -v python3 >/dev/null || { echo "Missing required tool: python3" >&2; exit 2; }
python3 -m venv "$python_env"
"$python_env/bin/python" -m pip install --timeout 90 --retries 5 \
  -r "$project_root/configs/stage02-requirements.txt"
"$python_env/bin/fusesoc" --version
"$python_env/bin/cocotb-config" --version
