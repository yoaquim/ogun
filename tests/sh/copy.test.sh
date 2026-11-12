#!/usr/bin/env bash
# og's folder alone is og: copied to a folder with nothing beside it, it installs (setup.sh),
# its own tests pass (test.sh), and its core commands run with an empty config folder and
# a fake sbx. Anything in og that reaches outside its folder fails here, since outside
# the copy there is nothing to reach. The copy's own run skips this file (OG_COPY).
# shellcheck disable=SC2016  # the bash -c bodies expand in the child, on purpose
set -uo pipefail
# shellcheck source=/dev/null
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
echo "og, copied"

if [[ -n "${OG_COPY:-}" ]]; then
  echo "  skip  every case: this is the copy's own run"
  exit 0
fi
og_python_or_skip   # the copy's setup builds from the same pinned tools, kept where og's own setup keeps them

COPY="$TEST_TMP/elsewhere/og"   # nothing beside it: no repo, no config of anyone's
mkdir -p "$COPY" "$TEST_TMP/bin" "$TEST_TMP/onpath" "$TEST_TMP/home"
export TEST_TMP COPY OGUN_TOOLS="${OGUN_TOOLS:-$HOME/.local/share/ogun}"
# every file of og's, as a team would get it: not the venvs or caches this checkout built
tar -C "$OGUN" --exclude='./.venv*' --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.ruff_cache' -cf - . \
  | tar -C "$COPY" -xf -

copied() { [[ -x "$COPY/setup.sh" && -x "$COPY/test.sh" && -f "$COPY/completion.bash" && -d "$COPY/docs" ]] && ! compgen -G "$COPY/.venv*" >/dev/null; }
expect_cmd 0 "the copy is og's folder alone: setup, runner, completion and docs, no venv" copied

# the copy as a repo of its own: everything committed, so what setup and a test run leave
# behind shows as untracked unless og's own ignore file covers it
git -C "$COPY" init -q && git -C "$COPY" add -A \
  && git -C "$COPY" -c user.name=og -c user.email=og@example.com -c commit.gpgsign=false commit -qm copy

# setup in the copy: its own venv, og and ogun linked into a folder of this test's
if OUT=$(cd "$COPY" && OGUN_BIN="$TEST_TMP/onpath" bash ./setup.sh 2>&1); then SETUP=0; else SETUP=1; fi
export OUT SETUP
expect_cmd 0 "setup builds og in the copy and links og and ogun to the copy's og" \
  bash -c '[ "$SETUP" = 0 ] || { echo "$OUT"; exit 1; }
           og=$("$COPY/bin/venv")/bin/og; [[ "$og" == "$COPY"/* ]] \
             && [ "$(readlink "$TEST_TMP/onpath/og")" = "$og" ] && [ "$(readlink "$TEST_TMP/onpath/ogun")" = "$og" ]'

# og's own runner in the copy: its shell tests, pytest and ruff, every file passing
RUN=$(cd "$COPY" && OG_COPY=1 TEST_SKIPS="" bash ./test.sh 2>&1); RC=$?
export RUN RC
expect_cmd 0 "the copy's runner passes: every test file of og's, from the copy" \
  bash -c '[ "$RC" = 0 ] && grep -qE "^og: all [0-9]+ test file\(s\) (that ran )?passed" <<<"$RUN" || { grep -E "FAIL|^E  |^og:" <<<"$RUN" | head -20; exit 1; }'
expect_cmd 0 "…and only this file skipped there; nothing else said it couldn't run" \
  bash -c '! grep -q "skip  every case: og'"'"'s Python" <<<"$RUN"'
expect_cmd 0 "…and leave nothing untracked in it: og's ignore file covers its venv and caches" \
  bash -c 'left=$(git -C "$COPY" status --porcelain --untracked-files=all) || exit 1; [ -z "$left" ] || { head -10 <<<"$left"; exit 1; }'

# og's core commands from the copy's links: an empty config folder, a fake sbx
printf '#!/bin/sh\necho "$*" >> "%s/sbx.calls"\n[ "$1" = ls ] && printf "SANDBOX  AGENT  STATUS\\n"\nexit 0\n' "$TEST_TMP" > "$TEST_TMP/bin/sbx"; chmod +x "$TEST_TMP/bin/sbx"
# a controlled environment: nothing of the shell running the tests (a profile, a setting)
# but the scratch state; Homebrew's folders after the fake sbx, so og, which puts any it
# finds missing in front, never reaches the sbx on this Mac
core() { local out
  out=$(cd "$TEST_TMP/home" && env -i HOME="$TEST_TMP/home" XDG_CONFIG_HOME="$TEST_TMP/home/.config" TMPDIR="$TMPDIR" \
        SBX_OGUN_DIR="$SBX_OGUN_DIR" SBX_EXCHANGE="$SBX_EXCHANGE" \
        PATH="$TEST_TMP/onpath:$TEST_TMP/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin" og "$@" 2>&1) || { echo "$out"; return 1; }
  echo "$out"; ! grep -q Traceback <<<"$out"; }
export -f core
expect_cmd 0 "og help, og ls, og template ls, og tidy and og log run from the copy, with no config of yours" \
  bash -c 'core help && core ls --all && core template ls && core tidy && core log'
expect_cmd 0 "…and every sbx call they made reached the fake sbx, never one on this Mac" \
  bash -c 'grep -qx "ls --all" "$TEST_TMP/sbx.calls"'
expect_cmd 0 "…and help names og's own docs, in the copy" \
  bash -c 'core help | grep -q "Full reference: docs/README.md, in og'"'"'s folder"'

summarize
