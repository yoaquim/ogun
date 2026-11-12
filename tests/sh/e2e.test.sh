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

# teardown, sourced, on a stand-in sbx whose rm works (it drops the name) or doesn't
teardown_case() { local works="$1" w; w=$(mktemp -d)
  mkdir -p "$w/ex/boxes/og-e2e-x" "$w/ex/boxes/cub" "$w/scratch"
  printf 'og-e2e-x\n' > "$w/listed"
  cat > "$FAKE/sbx" <<SH
#!/bin/sh
case "\$1" in
  ls) echo "NAME AGENT STATUS"; while read -r n; do echo "\$n claude stopped"; done < "$w/listed" ;;
  rm) [ "$works" = yes ] && : > "$w/listed"; [ "$works" = yes ] ;;
esac
SH
  chmod +x "$FAKE/sbx"
  env -i HOME="$TEST_TMP/home" PATH="$FAKE:/usr/bin:/bin" OG_E2E_SOURCE=1 W="$w" \
    bash -c '. "$1"; OG=/bin/false; SCRATCH="$W/scratch"; exchange() { echo "$W/ex"; }; teardown' _ "$E2E" >/dev/null 2>&1
  local rc=$?
  if [ "$works" = yes ]; then [ $rc -eq 0 ] && [ ! -e "$w/ex/boxes/og-e2e-x" ] && [ -d "$w/ex/boxes/cub" ] && [ ! -e "$w/scratch" ]
  else [ $rc -ne 0 ] && [ -d "$w/ex/boxes/og-e2e-x" ] && [ -d "$w/scratch" ]; fi; }
expect_cmd 0 "teardown removes its sandbox, then only og-e2e- boxes and its scratch folder" teardown_case yes
expect_cmd 0 "…and a sandbox that won't go fails it, keeping its box and the scratch folder it mounts" teardown_case no
fake sbx 0 $'NAME AGENT STATUS\ncub claude running\nog-e2e-20260101000000-1 claude stopped\nmy-og-e2e-thing claude running\n'

# og's state is the scratch folder before any og command runs, leftover cleanup included
expect_cmd 0 "the scratch state is set up before leftovers are removed" \
  bash -c 'b=$(sed -n "/^main()/,/^}/p" "$E2E"); s=$(grep -n "setup_world" <<<"$b" | head -1 | cut -d: -f1)
           l=$(grep -n "remove_leftovers" <<<"$b" | head -1 | cut -d: -f1); [ -n "$s" ] && [ -n "$l" ] && [ "$s" -lt "$l" ]'

# it reads that a token item exists, by name; it never makes or rotates one
expect_cmd 0 "it never runs og token" bash -c '! grep -nE "\"\\\$OG\"[^#]*[[:space:]]token([[:space:]]|$)" "$E2E"'

expect_cmd 0 "test.sh never runs it: it isn't among the shell tests" bash -c '[ ! -e "$OGUN/tests/sh/run.sh" ] && ! grep -q "e2e" "$OGUN/test.sh"'

summarize
