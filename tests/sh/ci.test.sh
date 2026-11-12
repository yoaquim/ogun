#!/usr/bin/env bash
# og's CI (.github/workflows/test.yml), read from its file: it runs the test container
# (tests/docker/run.sh) on every push to main and every pull request, with a token that can
# only read, and every action it uses pinned to a full commit, never a tag that can move.
# shellcheck disable=SC2016  # the bash -c bodies expand in the child, on purpose
set -uo pipefail
# shellcheck source=/dev/null
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
echo "og's CI"

W="$OGUN/.github/workflows/test.yml"
export W

expect_cmd 0 "the workflow is there" test -f "$W"

pinned() { local uses; uses=$(grep -E '^[[:space:]]*(-[[:space:]]*)?uses:' "$W") || return 1
  ! grep -vqE 'uses:[[:space:]]*[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}([[:space:]]|$)' <<<"$uses"; }
expect_cmd 0 "every action it uses is pinned to a full commit SHA" pinned

read_only() { grep -qE '^permissions:' "$W" && grep -A3 -E '^permissions:' "$W" | grep -qE '^[[:space:]]+contents:[[:space:]]*read' \
  && ! grep -qE ':[[:space:]]*write' "$W"; }
expect_cmd 0 "its token only reads: contents: read, nothing written" read_only

expect_cmd 0 "it runs on pull requests and on pushes to main" \
  bash -c 'grep -qE "^[[:space:]]+pull_request:" "$W" && grep -A3 -E "^[[:space:]]+push:" "$W" | grep -qE "main"'
expect_cmd 0 "…and runs the test container, the same as a local run" grep -qE 'tests/docker/run\.sh' "$W"
expect_cmd 0 "…and no secret reaches it" bash -c '! grep -q "secrets\." "$W"'

summarize
