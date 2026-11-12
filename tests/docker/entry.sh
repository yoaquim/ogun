#!/usr/bin/env bash
# What og's test container runs: test.sh, with its arguments (a filter), exiting with its
# exit. Here a skip is a failure too: the container has every tool a test needs, so a test
# that says it couldn't run means the image is wrong. OG_TEST_ROOT is for og's own tests.
set -uo pipefail
root="${OG_TEST_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
log=$(mktemp "${TMPDIR:-/tmp}/og-container.XXXXXX")
trap 'rm -f "$log"' EXIT

"$root/test.sh" "$@" 2>&1 | tee "$log"
rc=${PIPESTATUS[0]}
(( rc == 0 )) || exit "$rc"
# a file skipped whole is in test.sh's summary; a case skipped, a line of its own.
# pytest's own skips never reach this log (the runner drops pytest's output):
# OG_NO_SKIPS=1, set in the Dockerfile, makes tests/conftest.py fail them instead
if grep -qE '^  skip  |test file\(s\) skipped|; [0-9]+ skipped$' "$log"; then
  echo "og's test container: a test was skipped, and here none may be (above)" >&2
  exit 1
fi
