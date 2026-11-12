#!/usr/bin/env bash
# og end to end: the real og against real Docker Sandboxes and 1Password, on a Mac. Never
# part of test.sh or CI: it creates and removes a real sandbox, so it runs only when you
# opt in, and needs an owner whose GitHub token item already exists in your vault.
#
#   OG_E2E=1 OG_E2E_OWNER=acme OG_TOKEN_NAME=home tests/e2e/run.sh
#
# It runs this copy's og from its own folder: set the copy up with `OG_BIN= ./setup.sh`,
# so the og on your PATH stays the one you use.
#
# It checks a sandbox's whole life, in order, stopping at the first that fails: create, its
# token, the network (a baseline host answers; example.com, outside it, is refused, which
# may leave a request for approval on your Mac until the sandbox goes), the file exchange
# (og give, og take, a program in out/ quarantined) and og rm, with nothing of it left.
#
# Everything it makes is named og-e2e-<run id>: the sandbox, its repo, its exchange box.
# Teardown runs on every exit (a pass, a failure, an interrupt) and removes only names with
# that prefix, an earlier run's leftovers included: sandboxes, their stored secrets, and
# their folders in the exchange (box, quarantine, shared). Nothing else of yours is touched.
# og's own records for the run, and what og take brings back, go to a scratch folder. It
# never mints or rotates a token.
#
# og runs with an empty config folder of its own, so the run checks og's defaults and reads
# nothing of yours (~/.config/ogun stays untouched). Name what finds the token item in the
# environment: OG_TOKEN_NAME, the ending of your items (github-pat-<owner>-<ending>), and
# OG_VAULT when they aren't in the vault "Sandbox". Exit: 0 every check passed, 1 a check failed, 2 it
# refused to start.
set -uo pipefail

OGUN="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PREFIX="og-e2e-"
VENV="$(PATH=/usr/bin:/bin "$OGUN/bin/venv")"   # og's venv for this system, found with the system's own tools
OG="$VENV/bin/og"
PY="$VENV/bin/python"
# og's config folder: none during preflight (og reads a missing one as every default), the
# scratch folder's after; set on og's own command line, so sbx, op and git keep theirs
CFG="${TMPDIR:-/tmp}/og-e2e-no-config-$$"

og_() { XDG_CONFIG_HOME="$CFG" "$OG" "$@"; }

# ── output ──

PASSED=0
FAILED=()

say() { printf '%s\n' "$*"; }
refuse() { say "og e2e: $*" >&2; exit 2; }

# check <what it proves> <command…>: one line, ok or FAIL, and its status
check() {
  local what="$1"; shift
  if "$@" >/dev/null 2>&1; then
    say "  ok    $what"; PASSED=$((PASSED + 1))
  else
    say "  FAIL  $what"; FAILED+=("$what"); return 1
  fi
}

summary() {
  say ""
  if (( ${#FAILED[@]} )); then
    say "og e2e: ${#FAILED[@]} of $(( PASSED + ${#FAILED[@]} )) check(s) FAILED:"
    printf '  - %s\n' "${FAILED[@]}"
    return 1
  fi
  say "og e2e: all $PASSED check(s) passed"
}

# ── before anything: refuse rather than half-run ──

preflight() {
  [[ "${OG_E2E:-}" == 1 ]] || refuse "runs only when you opt in with OG_E2E=1: it creates and removes a real sandbox"
  [[ "$(uname -s)" == Darwin ]] || refuse "needs a Mac: Docker Sandboxes mounts the Mac's own paths"
  command -v sbx >/dev/null || refuse "no sbx on PATH: install Docker Sandboxes"
  sbx ls >/dev/null 2>&1 || refuse "sbx can't list sandboxes; signed in? run: sbx login"
  command -v op >/dev/null || refuse "no op on PATH: install the 1Password CLI"
  # an account added, not a session open: with the 1Password app, the token read below
  # unlocks it (Touch ID), the way og's own reads do; op whoami says "not signed in" until then
  [[ -n "$(op account list 2>/dev/null)" ]] || refuse "1Password has no account here; run: op signin"
  OWNER="${OG_E2E_OWNER:-}"
  [[ "$OWNER" =~ ^[a-z0-9][a-z0-9-]*$ ]] \
    || refuse "OG_E2E_OWNER names the owner whose GitHub token item the test sandbox gets (lowercase, as its folder)"
  [[ "${OG_TOKEN_NAME:-}" =~ ^[a-z0-9][a-z0-9-]*$ ]] \
    || refuse "OG_TOKEN_NAME names the ending of your token items, github-pat-<owner>-<ending> (og reads none of your config)"
  [[ -x "$OG" ]] || refuse "og isn't built in this checkout; run: OG_BIN= $OGUN/setup.sh"
  token_item_exists || refuse "no item github-pat-$OWNER-$OG_TOKEN_NAME in vault '${OG_VAULT:-Sandbox}' (set OG_VAULT for another), or 1Password stayed locked; make one with: og token $OWNER (this test never does)"
}

# whether one of the items og would hand this owner's sandbox is in the vault (named, never read)
token_item_exists() {
  local found vault it
  found=$(XDG_CONFIG_HOME="$CFG" "$PY" -I -c 'import sys; sys.path.insert(0, sys.argv[1])
from ogun.secrets import github
print(github.vault()); print(*github.items(sys.argv[2]), sep="\n")' "$OGUN/src" "$OWNER" 2>/dev/null) || return 1
  vault=$(head -n1 <<<"$found")
  while read -r it; do
    [[ -n "$it" ]] && op item get "$it" --vault "$vault" --format json >/dev/null 2>&1 && return 0
  done < <(tail -n +2 <<<"$found")
  return 1
}

# ── names and the scratch world ──

# the sandboxes sbx lists whose names start with the prefix, and nothing else; a list sbx
# couldn't give fails, never reads as none left
leftovers() { local all; all=$(sbx ls 2>/dev/null) || return 1
  awk -v p="$PREFIX" 'NR > 1 && index($1, p) == 1 { print $1 }' <<<"$all"; }

exchange() { og_ internal paths 2>/dev/null | awk -F'\t' '$1 == "EXCHANGE" { print $2 }'; }

setup_world() {
  RUN="$(date +%Y%m%d%H%M%S)-$$"
  NAME="$PREFIX$RUN"
  SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/og-e2e.XXXXXX")"
  SCRATCH="$(cd -P "$SCRATCH" && pwd)"   # og compares physical paths: /tmp is a link on a Mac
  CFG="$SCRATCH/config"
  export XDG_STATE_HOME="$SCRATCH/state"
  export OG_TAKE_DEST="$SCRATCH/taken"   # og take delivers here, never to your Downloads
  # one project folder, every repo in it the owner's
  export OG_PROJECTS="$SCRATCH/projects=$OWNER"
  REPO="$SCRATCH/projects/$NAME"
  mkdir -p "$REPO" "$XDG_STATE_HOME" "$OG_TAKE_DEST" "$CFG"
  git -C "$REPO" init -q
  printf '# %s\n\nA throwaway repo for og end to end.\n' "$NAME" > "$REPO/README.md"
  git -C "$REPO" add README.md
  git -C "$REPO" -c user.name=og-e2e -c user.email=og-e2e@example.com -c commit.gpgsign=false commit -qm "og e2e"
}

# every og-e2e sandbox, this run's and any earlier run's, then their stored secrets and
# folders in the exchange. A sandbox that won't go keeps its box (it's mounted there) and
# fails this, naming it: never a quiet pass
remove_leftovers() {
  local n ex names stuck=()
  if ! names=$(leftovers); then
    say "og e2e: sbx couldn't list its sandboxes, so every og-e2e box and the scratch folder are kept" >&2
    return 1
  fi
  while read -r n; do
    [[ -n "$n" ]] || continue
    og_ rm "$n" --force >/dev/null 2>&1 || sbx rm "$n" --force >/dev/null 2>&1
  done <<<"$names"
  if ! names=$(leftovers); then   # what sbx still lists
    say "og e2e: sbx couldn't list its sandboxes after removing them, so every og-e2e box and the scratch folder are kept" >&2
    return 1
  fi
  while read -r n; do [[ -n "$n" ]] && stuck+=("$n"); done <<<"$names"
  if (( ${#stuck[@]} )); then
    say "og e2e: couldn't remove ${stuck[*]}; its box and the scratch folder are kept. By hand:" >&2
    printf '  sbx rm %s --force\n' "${stuck[@]}" >&2
    return 1
  fi
  remove_secrets
  ex="$(exchange)"
  if [[ -n "$ex" ]]; then
    for d in boxes .quarantine shared; do
      [[ -d "$ex/$d" ]] && find "$ex/$d" -mindepth 1 -maxdepth 1 -name "${PREFIX}*" -exec rm -rf {} + 2>/dev/null
    done
  fi
  return 0
}

# the secrets sbx still stores for og-e2e sandboxes, which are gone by now
remove_secrets() {
  local sb kind
  while read -r sb kind; do
    sbx secret rm "$kind" --sandbox "$sb" -f </dev/null >/dev/null 2>&1
  done < <(sbx secret ls 2>/dev/null | awk -v p="$PREFIX" 'index($1, p) == 1 && $2 == "service" { print $1, $3 }')
}

# the scratch world, once nothing mounts it any more
remove_scratch() { [[ -n "${SCRATCH:-}" && -d "$SCRATCH" ]] && rm -rf "$SCRATCH"; return 0; }

# the EXIT trap: a teardown that fails fails the run, whatever the checks said
teardown() { remove_leftovers && remove_scratch; }

# ── the checks, one helper each ──

inside() { og_ sh "$NAME" "$@" </dev/null; }
box() { local ex; ex="$(exchange)"; [[ -n "$ex" ]] && printf '%s/boxes/%s' "$ex" "$NAME"; }
listed() { sbx ls 2>/dev/null | awk -v n="$NAME" 'NR > 1 && $1 == n { print $3; f = 1 } END { exit !f }'; }

create() { (cd "$REPO" && og_ --no-attach </dev/null) && [[ "$(listed)" == running ]]; }

# sbx stores a github secret scoped to it, and og recorded the owner that filled it
has_token() {
  sbx secret ls --sandbox "$NAME" 2>/dev/null \
    | awk -v n="$NAME" '$1 == n && $2 == "service" && $3 == "github" { f = 1 } END { exit !f }' || return 1
  [[ "$(cat "$XDG_STATE_HOME/ogun/tokens/$NAME.owner" 2>/dev/null)" == "$OWNER" ]]
}

# "<http code> <CONNECT code>" as curl reads it from inside; refused is the proxy's 403
answer() { inside curl -sS -o /dev/null --max-time 20 -w '%{http_code} %{http_connect}' "https://$1/" 2>/dev/null; }
answered() { [[ "${1%% *}" =~ ^[23][0-9][0-9]$ ]]; }
refused_403() { [[ " $1 " == *" 403 "* ]]; }
reaches() { answered "$(answer "$1")"; }
refused() { refused_403 "$(answer "$1")"; }

given() {
  local f="$SCRATCH/given-$RUN.txt"
  printf 'given %s\n' "$RUN" > "$f"
  (cd "$SCRATCH" && og_ give "$NAME" "$f" </dev/null) || return 1
  [[ "$(inside cat "$(box)/in/given-$RUN.txt")" == "given $RUN" ]]
}

taken() {
  # shellcheck disable=SC2016  # expands in the sandbox's sh
  inside sh -c 'printf "%s\n" "$2" > "$1/report.txt"' _ "$(box)/out" "taken $RUN" || return 1
  og_ take "$NAME" report.txt </dev/null || return 1
  [[ "$(cat "$OG_TAKE_DEST/report.txt" 2>/dev/null)" == "taken $RUN" && ! -e "$(box)/out/report.txt" ]]
}

quarantined() {
  # shellcheck disable=SC2016  # expands in the sandbox's sh
  inside sh -c 'printf "#!/bin/sh\necho hi\n" > "$1/tool.sh" && chmod +x "$1/tool.sh"' _ "$(box)/out" || return 1
  og_ take "$NAME" tool.sh </dev/null
  local q; q="$(exchange)/.quarantine/$NAME"
  [[ ! -e "$OG_TAKE_DEST/tool.sh" && ! -e "$(box)/out/tool.sh" && -d "$q" ]] && [[ -n "$(ls -A "$q")" ]]
}

removed() { og_ rm "$NAME" --force </dev/null && sbx ls >/dev/null 2>&1 && ! listed; }

# nothing of it left: no box, no stored secret (sbx must list them), and og tidy says nothing of it
nothing_left() {
  local b s t
  b=$(box) || return 1   # an exchange og can't name isn't one with nothing left
  [[ ! -e "$b" ]] || return 1
  s=$(sbx secret ls 2>/dev/null) || return 1
  ! awk -v n="$NAME" '$1 == n { f = 1 } END { exit !f }' <<<"$s" || return 1
  t=$(og_ tidy </dev/null 2>&1) || return 1
  ! grep -qF "$NAME" <<<"$t"
}

# in order; the first that fails stops the rest (each depends on the one before)
checks() {
  check "og --no-attach creates the sandbox, and sbx lists it running" create || return
  check "it holds its own GitHub token, for $OWNER" has_token || return
  check "a baseline host answers from inside (api.github.com)" reaches api.github.com || return
  check "a host outside the baseline is refused (example.com)" refused example.com || return
  check "a file given with og give reads inside" given || return
  check "a file left in out/ comes back with og take" taken || return
  check "a program left in out/ is quarantined, never delivered" quarantined || return
  check "og rm removes it" removed || return
  check "nothing of it is left: no box, no stored secret, nothing for og tidy" nothing_left
}

# ── the run ──

main() {
  preflight
  say "og e2e: owner $OWNER"
  trap 'teardown || exit 1' EXIT
  trap 'exit 130' INT TERM
  setup_world        # og's state is the scratch folder from here on, cleanup included
  remove_leftovers || exit 1   # an earlier run that crashed left these behind
  say "og e2e: $NAME"
  checks
  summary
}

# OG_E2E_SOURCE=1: define the functions and return (og's own tests read them)
[[ "${OG_E2E_SOURCE:-}" == 1 ]] && return 0 2>/dev/null
main "$@"
