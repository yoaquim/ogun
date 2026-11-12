#!/usr/bin/env bash
# og's end-to-end harness (tests/e2e/run.sh), without a real sandbox: it refuses to start
# unless asked on a Mac with sbx and 1Password ready and an owner named, and refuses
# before it calls sbx for anything that changes a thing; what it would clean up is only ever
# its own og-e2e- names; and it never mints a token. Stand-ins for uname, sbx and op.
# shellcheck disable=SC2016  # the bash -c bodies expand in the child, on purpose
set -uo pipefail
# shellcheck source=/dev/null
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
echo "og's end-to-end harness"

E2E="$OGUN/tests/e2e/run.sh"
FAKE="$TEST_TMP/fake"
mkdir -p "$FAKE"
export E2E FAKE

# fake <name> <exit> [<stdout>]: a stand-in that logs its arguments and answers
fake() { printf '#!/bin/sh\necho "%s $*" >> "%s/calls"\nprintf "%%s" "%s"\nexit %s\n' "$1" "$FAKE" "${3:-}" "$2" > "$FAKE/$1"
  chmod +x "$FAKE/$1"; }
fake uname 0 'Darwin'
fake sbx 0 $'NAME AGENT STATUS\ncub claude running\nog-e2e-20260101000000-1 claude stopped\nmy-og-e2e-thing claude running\n'
fake op 0 ''

# run [VAR=value …]: the harness on the stand-ins, with only what's given set
run() { env -i HOME="$TEST_TMP/home" PATH="$FAKE:/usr/bin:/bin" "$@" bash "$E2E"; }
refuses() { local want="$1"; shift; rm -f "$FAKE/calls"
  local o; o=$(run "$@" 2>&1); local rc=$?
  [[ $rc -eq 2 ]] && grep -qF "$want" <<<"$o" && ! grep -qE '^sbx (rm|create|run|exec|policy|secret)' "$FAKE/calls" 2>/dev/null; }

expect_cmd 0 "without OG_E2E=1 it refuses, touching nothing" refuses "opt in with OG_E2E=1"
expect_cmd 0 "…and off a Mac" bash -c "$(declare -f run refuses fake); fake uname 0 Linux; refuses 'needs a Mac' OG_E2E=1"
fake uname 0 'Darwin'
expect_cmd 0 "…and with no sbx" bash -c "$(declare -f run refuses fake); rm -f \"\$FAKE/sbx\"; refuses 'no sbx on PATH' OG_E2E=1"
expect_cmd 0 "…and when sbx can't list (signed out)" bash -c "$(declare -f run refuses fake); fake sbx 1; refuses 'sbx login' OG_E2E=1"
fake sbx 0 $'NAME AGENT STATUS\ncub claude running\nog-e2e-20260101000000-1 claude stopped\nmy-og-e2e-thing claude running\n'
expect_cmd 0 "…and when 1Password isn't signed in" bash -c "$(declare -f run refuses fake); fake op 1; refuses 'op signin' OG_E2E=1"
fake op 0 ''
expect_cmd 0 "…and with no owner named" refuses "OG_E2E_OWNER names the owner" OG_E2E=1
expect_cmd 0 "…and with an owner that isn't a folder name" refuses "OG_E2E_OWNER names the owner" OG_E2E=1 OG_E2E_OWNER='Acme Corp'

# what teardown would remove: only the sandboxes named with the prefix, from sbx's own list
only_its_own() { local o; o=$(env -i HOME="$TEST_TMP/home" PATH="$FAKE:/usr/bin:/bin" OG_E2E_SOURCE=1 \
    bash -c '. "$1"; leftovers' _ "$E2E"); [[ "$o" == "og-e2e-20260101000000-1" ]]; }
expect_cmd 0 "what it cleans up is only og-e2e- sandboxes: never cub, nor a name with og-e2e inside it" only_its_own

# it reads that a token item exists, by name; it never makes or rotates one
expect_cmd 0 "it never runs og token" bash -c '! grep -nE "\"\\\$OG\"[^#]*[[:space:]]token([[:space:]]|$)" "$E2E"'

expect_cmd 0 "test.sh never runs it: it isn't among the shell tests" bash -c '[ ! -e "$OGUN/tests/sh/run.sh" ] && ! grep -q "e2e" "$OGUN/test.sh"'

summarize
