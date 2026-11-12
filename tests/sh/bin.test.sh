#!/usr/bin/env bash
# og as an installed command: setup.sh puts it in og's own environment and links it
# onto PATH as og and ogun (~/.local/bin, or OGUN_BIN).
#
# What this suite pins: setup's links, and that og runs from any folder, through any
# link, and with cron's bare PATH (Homebrew's folders put in front).

# shellcheck disable=SC2016  # the bash -c bodies expand in the child, on purpose
set -uo pipefail
# shellcheck source=/dev/null
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
og_python_or_skip   # og itself: installed by setup.sh

echo "og, installed"

OG="$("$OGUN/bin/venv")/bin/og"
FIX="$TEST_TMP/og-bin"
export FIX OG
mkdir -p "$FIX/bin" "$FIX/home" "$FIX/away"

# sbx stub: records and prints its argv — nothing here may touch a real sandbox
printf '#!/bin/sh\necho "sbx $*"\n' > "$FIX/bin/sbx"
chmod +x "$FIX/bin/sbx"
export PATH="$FIX/bin:$PATH"

# og ls with sbx's own arguments passes sbx's output through as is: the one
# command whose words show the call reached sbx
expect_cmd 0 "og runs from any folder (ls --all → sbx ls --all)" \
  bash -c 'cd "$FIX/away" && [ "$("$OG" ls --all)" = "sbx ls --all" ]'

ln -s "$OG" "$FIX/og-link"; ln -s "$FIX/og-link" "$FIX/bin/og"
expect_cmd 0 "…and through a chain of links, as a link on PATH is" \
  bash -c '[ "$(og ls --all)" = "sbx ls --all" ]'

# cron's bare PATH: og puts the Homebrew prefixes in front so sbx and op resolve (on a
# runner without Homebrew /usr/local/bin stands in). Where a real sbx is in one of them,
# it would answer ahead of the stub: the case doesn't run there, never reaching the
# Mac's sandboxes, and the rule itself is test_cli.py's (with_brew, and main using it)
mkdir -p "$FIX/pathbin"
printf '#!/bin/sh\necho "$PATH"\n' > "$FIX/pathbin/sbx"
chmod +x "$FIX/pathbin/sbx"
brew_sbx=""
for d in /opt/homebrew/bin /usr/local/bin; do [[ -x "$d/sbx" ]] && brew_sbx="$d/sbx"; done
if [[ -n "$brew_sbx" ]]; then
  echo "  skip  og puts the Homebrew prefixes ahead of a bare PATH: a real sbx is at $brew_sbx (test_cli.py covers the rule)"
else
  expect_cmd 0 "og puts the Homebrew prefixes ahead of a bare PATH" \
    bash -c 'OUT=$(env -i HOME="$FIX/home" PATH="$FIX/pathbin:/usr/bin:/bin" "$OG" ls --all)
             case "$OUT" in /usr/local/bin:*|/opt/homebrew/bin:*) exit 0 ;; *) echo "$OUT"; exit 1 ;; esac'
fi


# ── setup puts og on PATH: og and ogun, links to the venv's og, in OGUN_BIN ──
# the pinned uv and Pythons stay where setup keeps them (OGUN_TOOLS): nothing downloads again
export OGUN_TOOLS="${OGUN_TOOLS:-$HOME/.local/share/ogun}"
setup_links() { local b="$FIX/onpath" o; rm -rf "$b"
  o=$(OGUN_BIN="$b" bash "$OGUN/setup.sh" 2>&1) || { echo "$o"; return 1; }
  [ "$(readlink "$b/og")" = "$OG" ] && [ "$(readlink "$b/ogun")" = "$OG" ] \
    && [ "$(PATH="$b:$FIX/bin:$PATH" og ls --all)" = "sbx ls --all" ] && [ "$(PATH="$b:$FIX/bin:$PATH" ogun ls --all)" = "sbx ls --all" ]; }
expect_cmd 0 "setup links og and ogun in OGUN_BIN to the venv's og, and both run" setup_links
setup_again() { local b="$FIX/again" o; rm -rf "$b"; mkdir -p "$b"
  ln -s /nowhere/og "$b/og"; printf 'mine\n' > "$b/ogun"
  o=$(OGUN_BIN="$b" bash "$OGUN/setup.sh" 2>&1) || { echo "$o"; return 1; }
  [ "$(readlink "$b/og")" = "$OG" ] && [ "$(cat "$b/ogun")" = mine ] && grep -q "$b/ogun.*not a link" <<<"$o"; }
expect_cmd 0 "…an old link is replaced; a file of yours in the way is left, and said" setup_again
setup_nopath() { local o; o=$(OGUN_BIN="" HOME="$FIX/nohome" bash "$OGUN/setup.sh" 2>&1) || { echo "$o"; return 1; }
  [ ! -e "$FIX/nohome/.local/bin/og" ]; }
expect_cmd 0 "…and an empty OGUN_BIN links nothing (a sandbox building og only for its tests)" setup_nopath

summarize
