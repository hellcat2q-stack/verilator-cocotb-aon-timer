#!/usr/bin/env bash
# Preserve the old server Git while supporting the modern `git -C` call sites.
set -euo pipefail
if [[ ${1-} == "-C" ]]; then
  directory=${2:?missing directory after -C}
  shift 2
  cd "$directory"
fi
exec /bin/git "$@"
