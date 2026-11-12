#!/usr/bin/env bash
# og's test container (tests/docker): what it is built from and how it runs, read from its
# files. Building and running it is tests/docker/run.sh's job, never this suite's: the suite
# runs inside that container too.
set -uo pipefail
# shellcheck source=/dev/null
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
echo "og's test container"

D="$OGUN/tests/docker"
export D

# every FROM names its image by digest: a tag can move under a build, a digest can't
pinned() { grep -qE '^FROM ' "$D/Dockerfile" && ! grep -E '^FROM ' "$D/Dockerfile" | grep -vqE '^FROM [^ ]+@sha256:[0-9a-f]{64}( |$)'; }
expect_cmd 0 "its base image is pinned by digest" pinned

# the last USER is a named one, never root: the suite runs unprivileged, as on a Mac
non_root() { local u; u=$(grep -E '^USER ' "$D/Dockerfile" | tail -n1 | awk '{print $2}'); [[ -n "$u" && "$u" != root && "$u" != 0 ]]; }
expect_cmd 0 "it runs as a user of its own, never root" non_root

# the build context is the repo: what a run builds on the host, and the issues, stay out
ignored() { local f="$OGUN/.dockerignore"; [[ -f "$f" ]] || return 1
  for p in '.venv*' '**/__pycache__' '.pytest_cache' '.ruff_cache' '.issues' '.git'; do grep -qxF "$p" "$f" || { echo "missing $p"; return 1; }; done; }
expect_cmd 0 "the build leaves out the host's venvs, caches, git and issues" ignored

# one command builds and runs it, and its exit is the suite's
expect_cmd 0 "run.sh is there and executable" test -x "$D/run.sh"
expect_cmd 0 "…and so is the script the container runs" test -x "$D/entry.sh"

# inside, a skip is no pass: the container has every tool a test needs, so any skip fails it
skip_fails() { local t; t=$(mktemp -d)
  printf '#!/usr/bin/env bash\necho "  skip  a case: no tool"\necho "og: all 1 test file(s) passed"\n' > "$t/test.sh"; chmod +x "$t/test.sh"
  OG_TEST_ROOT="$t" bash "$D/entry.sh" >/dev/null 2>&1; local rc=$?; rm -rf "$t"; [[ $rc -ne 0 ]]; }
expect_cmd 0 "entry.sh fails a run that skipped anything, even when every file passed" skip_fails

passes() { local t; t=$(mktemp -d)
  printf '#!/usr/bin/env bash\necho "  ok    a case"\necho "og: all 1 test file(s) passed"\n' > "$t/test.sh"; chmod +x "$t/test.sh"
  OG_TEST_ROOT="$t" bash "$D/entry.sh" >/dev/null 2>&1; local rc=$?; rm -rf "$t"; [[ $rc -eq 0 ]]; }
expect_cmd 0 "…and passes a clean run" passes

fails() { local t; t=$(mktemp -d)
  printf '#!/usr/bin/env bash\necho "og: 1 of 1 test file(s) FAILED"\nexit 1\n' > "$t/test.sh"; chmod +x "$t/test.sh"
  OG_TEST_ROOT="$t" bash "$D/entry.sh" >/dev/null 2>&1; local rc=$?; rm -rf "$t"; [[ $rc -ne 0 ]]; }
expect_cmd 0 "…and fails a run whose suite failed" fails

# pytest's own skips never reach entry.sh's log (the runner drops pytest's output), so in
# the container OG_NO_SKIPS=1 makes og's conftest fail a skipped test instead
expect_cmd 0 "the image sets OG_NO_SKIPS" grep -qxE 'ENV OG_NO_SKIPS=1' "$D/Dockerfile"
if [[ -n "$OG_PY" ]]; then
  skipping() { local t; t=$(mktemp -d)
    printf 'import pytest\n\ndef test_skips():\n    pytest.skip("no tool")\n' > "$t/test_skip.py"
    (cd "$t" && PYTHONPATH="$OGUN/tests:$OGUN/src" "$OG_PY" -m pytest -q -n0 -p no:cacheprovider -p conftest \
       -o addopts="" --rootdir "$t" "$t/test_skip.py" >/dev/null 2>&1); local rc=$?; rm -rf "$t"; return "$rc"; }
  expect_cmd 0 "without OG_NO_SKIPS a skipped pytest test is a skip" env -u OG_NO_SKIPS bash -c "$(declare -f skipping); skipping"
  expect_cmd 1 "…with OG_NO_SKIPS=1 it fails the run" env OG_NO_SKIPS=1 bash -c "$(declare -f skipping); skipping"
fi

summarize
