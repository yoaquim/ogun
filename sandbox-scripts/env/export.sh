# shellcheck shell=bash
# shellcheck disable=SC2024  # the temp file is ours to read; only tee, writing the env, runs as root
# export.sh <VAR> <placeholder> [<file>] — runs inside a sandbox (bash -lc): its export of
# a placeholder, any earlier line for that variable replaced, so a re-pass never
# leaves a stale one. Read by src/ogun/secrets/secret.py and secrets/sandboxenv.py.
# <file>, as in expose.sh, is for the tests: an argument the host passes, never sandbox env.
v="$1"; p="$2"; f="${3:-/etc/sandbox-persistent.sh}"
t=$(mktemp) || exit 1
{ grep -v "^export $v=" "$f" 2>/dev/null; printf "export %s=%s\n" "$v" "$p"; } > "$t" \
    && { cat "$t" > "$f" 2>/dev/null || sudo -n tee "$f" < "$t" >/dev/null; } \
    && rm -f "$t"
