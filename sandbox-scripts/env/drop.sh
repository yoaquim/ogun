# shellcheck shell=bash
# shellcheck disable=SC2024  # the temp file is ours to read; only tee, writing the env, runs as root
# drop.sh <VAR> [<file>] — runs inside a sandbox (bash -lc): removes every export of that
# variable from its persistent env, a placeholder's or a real value's (og pass
# --rm). Exit 3 when there was none. <VAR> is checked by og pass first; <file>,
# as in expose.sh, is for the tests: an argument the host passes, never sandbox env.
v="$1"; f="${2:-/etc/sandbox-persistent.sh}"
grep -q "^export $v=" "$f" 2>/dev/null || exit 3
t=$(mktemp) || exit 1; chmod 600 "$t"
grep -v "^export $v=" "$f" > "$t"; { cat "$t" > "$f" 2>/dev/null || sudo -n tee "$f" < "$t" >/dev/null; }; rc=$?
rm -f "$t"; exit "$rc"
