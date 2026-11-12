#!/usr/bin/env bash
# Helpers for og's shell tests (tests/sh), sourced by each *.test.sh: a case is a
# command and the exit it should end with.

PASS=0
FAIL=0
FAILED_NAMES=()

# og's own folder, the repo's root: everything a test runs or reads is in it
OGUN="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export OGUN

# Each test file gets its own TMPDIR, and og's own state (create records, its record of
# changes) and exchange inside it: a test that removes a sandbox would otherwise delete a
# real record and write a fake change into the real og log, and an attach would make
# folders in the real exchange. A test that needs its own sets it after.
TEST_TMP=$(mktemp -d "${TMPDIR:-/tmp}/og-tests.XXXXXX")
export TMPDIR="$TEST_TMP"
export XDG_STATE_HOME="$TEST_TMP/state" OG_EXCHANGE="$TEST_TMP/exchange"
# a test that runs setup.sh never puts og on the real PATH (~/.local/bin): one that
# checks setup's links names its own OG_BIN
export OG_BIN=""
# nor runs under the profile the shell running the tests names: one og's config there
# doesn't have stops og
unset OG_PROFILE

# The EXIT trap also summarizes when the test file forgot to: a file that ends without
# calling `summarize` would otherwise exit 0 regardless of failures, and the runner would
# report a green suite over red cases.
SUMMARIZED=0
_lib_finish() {
  local rc=$?
  # a test may leave a read-only folder (a skills store, a pytest home): writable again first
  chmod -R u+w "$TEST_TMP" 2>/dev/null
  rm -rf "$TEST_TMP"
  if (( ! SUMMARIZED )); then summarize; fi
  exit "$rc"
}
trap '_lib_finish' EXIT

# og's Python: the venv bin/venv names (.venv on a Mac, .venv-linux in a sandbox). OG_PY is
# its python, or empty where it isn't built; a file that needs it calls og_python_or_skip first.
OG_PY="$("$OGUN/bin/venv")/bin/python"
"$OGUN/bin/venv" --ready || OG_PY=""   # a half-built venv (its packages never came) isn't og's Python
export OG_PY
# og_python_or_skip — return when og's Python is built; otherwise end this file with one
# skip line that says how to build it, which the runner counts as a skip, never a pass
og_python_or_skip() {
  [[ -n "$OG_PY" ]] && return 0
  echo "  skip  every case: og's Python isn't built here — run: $OGUN/setup.sh"
  [[ -n "${TEST_SKIPS:-}" ]] && printf '%s\n' "$(basename "$0")" >> "$TEST_SKIPS"
  SUMMARIZED=1
  exit 0
}

# expect_cmd <want-exit> <name> <cmd...>
expect_cmd() {
  local want="$1" name="$2"; shift 2
  local got
  "$@" >/dev/null 2>&1; got=$?
  if [[ "$got" == "$want" ]]; then
    PASS=$((PASS + 1))
    printf '  ok    %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    FAILED_NAMES+=("$name")
    printf '  FAIL  %s (exit %s, want %s)\n' "$name" "$got" "$want"
  fi
}

summarize() {
  SUMMARIZED=1
  echo
  if (( FAIL == 0 )); then
    echo "$PASS passed, 0 failed"
    exit 0
  fi
  echo "$PASS passed, $FAIL FAILED:"
  printf '  - %s\n' "${FAILED_NAMES[@]}"
  exit 1
}
