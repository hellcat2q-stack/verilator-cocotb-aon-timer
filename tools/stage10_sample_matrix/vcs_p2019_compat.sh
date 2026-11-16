#!/usr/bin/env bash
# VCS P-2019.06-SP1 compatibility: unsupported newer flags and optional isolated GCC.
set -euo pipefail
VCS_BIN=/SM01/eda/synopsys/vcs/P-2019.06-SP1/bin/vcs
args=()
removed=0
removed_common_hier=0
rewritten_hier=0
merged_hier_path=
input=("$@")
i=0
while [ "$i" -lt "${#input[@]}" ]; do
  arg="${input[$i]}"
  if [ "$arg" = "-xprop=mmsopt" ]; then
    removed=$((removed + 1))
  elif [ "$arg" = "-cm_common_hier" ]; then
    removed_common_hier=$((removed_common_hier + 1))
  elif [ "$arg" = "-cm_hier" ] && [ "$((i + 1))" -lt "${#input[@]}" ] && [[ "${input[$((i + 1))]}" == *+* ]]; then
    IFS='+' read -r -a hier_files <<< "${input[$((i + 1))]}"
    if [ -n "${VCS2019_CM_HIER_MERGED:-}" ]; then
      merged_hier_path="$VCS2019_CM_HIER_MERGED"
    elif [ -n "${VCS2019_ARGV_LOG:-}" ]; then
      merged_hier_path="$(dirname "$VCS2019_ARGV_LOG")/cm_hier_merged.cfg"
    else
      merged_hier_path="${TMPDIR:-/tmp}/vcs2019_cm_hier_$$.cfg"
    fi
    merged_nonmetric_path="${merged_hier_path}.nonmetric"
    merged_metric_path="${merged_hier_path}.metric"
    : > "$merged_nonmetric_path"
    : > "$merged_metric_path"
    for hier_file in "${hier_files[@]}"; do
      test -r "$hier_file"
      awk -v nonmetric="$merged_nonmetric_path" -v metric="$merged_metric_path" '
        /^[[:space:]]*begin([[:space:]]|$)/ { in_metric = 1 }
        {
          if (in_metric) print $0 >> metric
          else print $0 >> nonmetric
        }
        /^[[:space:]]*end[[:space:]]*$/ { if (in_metric) in_metric = 0 }
      ' "$hier_file"
      printf '\n' >> "$merged_nonmetric_path"
      printf '\n' >> "$merged_metric_path"
    done
    cat "$merged_nonmetric_path" "$merged_metric_path" > "$merged_hier_path"
    args+=("-cm_hier" "$merged_hier_path")
    rewritten_hier=$((rewritten_hier + 1))
    i=$((i + 1))
  else
    args+=("$arg")
  fi
  i=$((i + 1))
done
if [ -n "${VCS2019_CC:-}" ] || [ -n "${VCS2019_CXX:-}" ]; then
  test -x "${VCS2019_CC:-}"
  test -x "${VCS2019_CXX:-}"
  args+=("-cc" "$VCS2019_CC" "-cpp" "$VCS2019_CXX")
fi
if [ -n "${VCS2019_ARGV_LOG:-}" ]; then
  {
    printf 'REMOVED_XPROP_MMSOPT=%s\n' "$removed"
    printf 'REMOVED_CM_COMMON_HIER=%s\n' "$removed_common_hier"
    printf 'REWRITTEN_CM_HIER_PLUS_LIST=%s\n' "$rewritten_hier"
    printf 'MERGED_CM_HIER_CFG=%s\n' "$merged_hier_path"
    printf 'EXEC='
    printf '%q ' "$VCS_BIN" "${args[@]}"
    printf '\n'
  } >> "$VCS2019_ARGV_LOG"
fi
if [ "$removed" -gt 0 ]; then
  printf 'VCS2019_COMPAT: omitted -xprop=mmsopt; retained xprop configuration.\n' >&2
fi
if [ "$removed_common_hier" -gt 0 ]; then
  printf 'VCS2019_COMPAT: omitted unsupported -cm_common_hier; retained explicit -cm_hier files.\n' >&2
fi
if [ "$rewritten_hier" -gt 0 ]; then
  printf 'VCS2019_COMPAT: merged +-joined -cm_hier files in order into one temporary config.\n' >&2
fi
exec "$VCS_BIN" "${args[@]}"
