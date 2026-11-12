# shellcheck shell=bash
# shellcheck disable=SC2024  # the temp file is ours to read; only tee, writing the env, runs as root
# expose.sh <VAR> [<file>] — runs inside a sandbox (bash -lc): the real value, on
# stdin, into its persistent env. <file> is for og's tests (tests/test_secret.py), run against a
# scratch file: an argument the HOST passes, never sandbox env, since bash -l
# sources the sandbox's profile, which must not be able to redirect a delivery.
v="$1"; f="${2:-/etc/sandbox-persistent.sh}"
s=$(cat; printf x) || exit 1; s=${s%x}   # sentinel: $() must not eat trailing newlines
[ -n "$s" ] || exit 1
t=$(mktemp) || exit 1; chmod 600 "$t"
{ grep -v "^export $v=" "$f" 2>/dev/null; printf "export %s=%q\n" "$v" "$s"; } > "$t" \
    && { cat "$t" > "$f" 2>/dev/null || sudo -n tee "$f" < "$t" >/dev/null; }; rc=$?
rm -f "$t"; exit "$rc"
