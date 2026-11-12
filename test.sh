#!/usr/bin/env bash
# og's tests: every shell test in tests/sh, among them pytest.test.sh, which runs og's
# pytest suite and ruff. Each file is run on its own; a file that can't run here (og's
# Python not built) is a skip, said at the end, never a pass.
#
#   test.sh           # everything
#   test.sh python    # only files whose name contains "python"

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/tests/sh" || exit 1

FILTER="${1:-}"
FAILED=0
RAN=0
# a caller's own skip list (another runner calling this one) is added to, not replaced
OWN_SKIPS=0
if [[ -z "${TEST_SKIPS:-}" ]]; then
  TEST_SKIPS=$(mktemp "${TMPDIR:-/tmp}/og-test-skips.XXXXXX")
  OWN_SKIPS=1
  trap 'rm -f "$TEST_SKIPS"' EXIT
fi
export TEST_SKIPS
before=$(wc -l < "$TEST_SKIPS" | tr -d ' ')

for t in *.test.sh; do
  [[ -e "$t" ]] || continue
  [[ -n "$FILTER" && "$t" != *"$FILTER"* ]] && continue
  RAN=$((RAN + 1))
  bash "$t" || FAILED=$((FAILED + 1))
  echo
done

if (( RAN == 0 )); then
  echo "No og test files matched${FILTER:+ \"$FILTER\"}."
  exit 1
fi

SKIPPED=$(( $(wc -l < "$TEST_SKIPS" | tr -d ' ') - before ))
if (( SKIPPED > 0 && OWN_SKIPS )); then
  echo "$SKIPPED og test file(s) skipped, og's Python isn't built here (run: $(cd ../.. && pwd)/setup.sh): $(tail -n "$SKIPPED" "$TEST_SKIPS" | paste -sd' ' -)"
fi
if (( FAILED > 0 )); then
  echo "og: $FAILED of $RAN test file(s) FAILED"
  exit 1
fi
if (( SKIPPED > 0 )); then
  echo "og: all $((RAN - SKIPPED)) test file(s) that ran passed; $SKIPPED skipped"
else
  echo "og: all $RAN test file(s) passed"
fi
