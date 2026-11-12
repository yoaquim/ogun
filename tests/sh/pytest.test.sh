#!/usr/bin/env bash
# og's own unit tests (tests, pytest) and its lint (ruff), run from og's venv, so
# og's runner fails when either does. A failing pytest test has to fail this file: checked
# first, against a scratch test that fails on purpose.

set -uo pipefail
# shellcheck source=/dev/null
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

echo "ogun pytest: og's unit tests and ruff"

VENV="$("$OGUN/bin/venv")"
# a venv built before the dev group had them has og's packages but not pytest or xdist: sync it once
if [[ -n "$OG_PY" ]] && ! "$OG_PY" -I -c 'import pytest, xdist' 2>/dev/null; then
  bash "$OGUN/setup.sh" >/dev/null 2>&1
fi
"$OG_PY" -I -c 'import pytest, xdist' 2>/dev/null || OG_PY=""
og_python_or_skip

og_pytest() { (cd "$OGUN" && "$VENV/bin/python" -m pytest -q -p no:cacheprovider "$@"); }

FIX="$TEST_TMP/og-pytest"; mkdir -p "$FIX"
printf 'def test_fails_on_purpose():\n    assert 1 == 2\n' > "$FIX/test_broken.py"
expect_cmd 1 "a failing pytest test fails the run" og_pytest "$FIX"
expect_cmd 0 "og's unit tests pass" og_pytest --basetemp "$TEST_TMP/basetemp"
expect_cmd 0 "…and leave no read-only folder behind, so the next run can clear them" \
  bash -c '[ -z "$(find "$1" -type d ! -perm -u+w 2>/dev/null | head -1)" ]' _ "$TEST_TMP/basetemp"
expect_cmd 0 "ruff is clean on all of og" "$VENV/bin/ruff" check --no-cache "$OGUN"

summarize
