# shellcheck shell=bash
# shellcheck disable=SC2024  # the temp file is ours to read; only tee, writing the env, runs as root
# unexport.sh <VAR> <placeholder> [<file>] — runs inside a sandbox (bash -lc): drops its
# export of exactly that placeholder; a value passed again since is kept. <file>,
# as in expose.sh, is for the tests: an argument the host passes, never sandbox env.
v="$1"; p="$2"; f="${3:-/etc/sandbox-persistent.sh}"
grep -qx "export $v=$p" "$f" 2>/dev/null || exit 0
t=$(mktemp) || exit 1
grep -vx "export $v=$p" "$f" > "$t"; { cat "$t" > "$f" 2>/dev/null || sudo -n tee "$f" < "$t" >/dev/null; }; rc=$?
rm -f "$t"; exit "$rc"
