#!/bin/bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=backup-sync-lib.sh
source "$script_dir/backup-sync-lib.sh"

tmpdir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmpdir"
}
trap cleanup EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_eq() {
  local expected="$1"
  local actual="$2"
  local message="$3"
  if [[ "$actual" != "$expected" ]]; then
    printf 'FAIL: %s\nexpected: %q\nactual:   %q\n' "$message" "$expected" "$actual" >&2
    exit 1
  fi
}

cat >"$tmpdir/excludes" <<'EXCLUDES'
# comments and blank lines are ignored
/home/*/.cache/***
/var/cache/***
*.mp4
*.tar.gz
*.qcow2
relative/path/***
EXCLUDES

regex="$(backup_sync_extension_regex "$tmpdir/excludes")"
assert_eq '.*\.(mp4|tar\.gz|qcow2)' "$regex" 'extension regex is derived from *.ext patterns'

patterns="$(backup_sync_summary_patterns "$tmpdir/excludes")"
assert_eq $'/home/*/.cache\n/var/cache' "$patterns" 'summary patterns are derived from absolute /*** excludes only'

mkdir -p "$tmpdir/home/alice/.cache/pip" "$tmpdir/var/cache/apt" "$tmpdir/other"
printf x >"$tmpdir/home/alice/.cache/pip/a"
printf y >"$tmpdir/var/cache/apt/b"
cat >"$tmpdir/excludes-local" <<EXCLUDES
$tmpdir/home/*/.cache/***
$tmpdir/var/cache/***
*.mp4
EXCLUDES

backup_sync_write_static_summary "$tmpdir/excludes-local" "$tmpdir/summary"
grep -F "  $tmpdir/home/alice/.cache" "$tmpdir/summary" >/dev/null || fail 'home cache summary missing'
grep -F "  $tmpdir/var/cache" "$tmpdir/summary" >/dev/null || fail 'var cache summary missing'
grep -F 'files: 1' "$tmpdir/summary" >/dev/null || fail 'file count missing from summary'
grep -F 'top-level entries:' "$tmpdir/summary" >/dev/null || fail 'top-level entries missing from summary'

printf 'backup-sync parser tests passed\n'
