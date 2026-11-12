#!/usr/bin/env bash
# og end to end: the real og against real Docker Sandboxes and 1Password, on a Mac. Never
# part of test.sh or CI: it creates and removes a real sandbox, so it runs only when you
# opt in, and needs an owner whose GitHub token item already exists in your vault.
#
#   OG_E2E=1 OG_E2E_OWNER=acme tests/e2e/run.sh
#
# Everything it makes is named og-e2e-<run id>: the sandbox, its repo, its exchange box.
# Teardown runs on every exit (a pass, a failure, an interrupt) and removes only names with
# that prefix, an earlier run's leftovers included; nothing else of yours is touched.
# og's own records for the run go to a scratch state folder. It never mints or rotates a
# token. Exit: 0 every check passed, 1 a check failed, 2 it refused to start.
set -uo pipefail

OGUN="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PREFIX="og-e2e-"
VENV="$(PATH=/usr/bin:/bin "$OGUN/bin/venv")"   # og's venv for this system, found with the system's own tools
OG="$VENV/bin/og"
PY="$VENV/bin/python"

# ── output ──

PASSED=0
FAILED=()

say() { printf '%s\n' "$*"; }
refuse() { say "og e2e: $*" >&2; exit 2; }

# check <what it proves> <command…>: one line, ok or FAIL
check() {
  local what="$1"; shift
  if "$@" >/dev/null 2>&1; then
    say "  ok    $what"; PASSED=$((PASSED + 1))
  else
    say "  FAIL  $what"; FAILED+=("$what")
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
  op whoami >/dev/null 2>&1 || refuse "1Password isn't signed in; run: op signin"
  [[ -x "$OG" ]] || refuse "og isn't built in this checkout; run: $OGUN/setup.sh"
  OWNER="${OG_E2E_OWNER:-}"
  [[ "$OWNER" =~ ^[a-z0-9][a-z0-9-]*$ ]] \
    || refuse "OG_E2E_OWNER names the owner whose GitHub token item the test sandbox gets (lowercase, as its folder)"
  token_item_exists || refuse "no GitHub token item for $OWNER in your vault; make one with: og token $OWNER (this test never does)"
}

# whether one of the items og would hand this owner's sandbox is in the vault (named, never read)
token_item_exists() {
  local found vault it
  found=$("$PY" -I -c 'import sys; sys.path.insert(0, sys.argv[1])
from ogun.secrets import github
print(github.vault()); print(*github.items(sys.argv[2]), sep="\n")' "$OGUN/src" "$OWNER") || return 1
  vault=$(head -n1 <<<"$found")
  while read -r it; do
    [[ -n "$it" ]] && op item get "$it" --vault "$vault" --format json >/dev/null 2>&1 && return 0
  done < <(tail -n +2 <<<"$found")
  return 1
}

# ── names and the scratch world ──

# the sandboxes sbx lists whose names start with the prefix, and nothing else
leftovers() { sbx ls 2>/dev/null | awk -v p="$PREFIX" 'NR > 1 && index($1, p) == 1 { print $1 }'; }

exchange() { "$OG" internal paths 2>/dev/null | awk -F'\t' '$1 == "EXCHANGE" { print $2 }'; }

setup_world() {
  RUN="$(date +%Y%m%d%H%M%S)-$$"
  NAME="$PREFIX$RUN"
  SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/og-e2e.XXXXXX")"
  SCRATCH="$(cd -P "$SCRATCH" && pwd)"   # og compares physical paths: /tmp is a link on a Mac
  export XDG_STATE_HOME="$SCRATCH/state"
  # one project folder, every repo in it the owner's
  export OG_PROJECTS="$SCRATCH/projects=$OWNER"
  REPO="$SCRATCH/projects/$NAME"
  mkdir -p "$REPO" "$XDG_STATE_HOME"
  git -C "$REPO" init -q
  printf '# %s\n\nA throwaway repo for og end to end.\n' "$NAME" > "$REPO/README.md"
  git -C "$REPO" add README.md
  git -C "$REPO" -c user.name=og-e2e -c user.email=og-e2e@example.com -c commit.gpgsign=false commit -qm "og e2e"
}

# every og-e2e sandbox and its box, this run's and any earlier run's; then the scratch world
teardown() {
  local n ex
  while read -r n; do
    [[ -n "$n" ]] || continue
    "$OG" rm "$n" --force >/dev/null 2>&1 || sbx rm "$n" --force >/dev/null 2>&1
  done < <(leftovers)
  ex="$(exchange)"
  if [[ -n "$ex" && -d "$ex/boxes" ]]; then
    find "$ex/boxes" -mindepth 1 -maxdepth 1 -type d -name "${PREFIX}*" -exec rm -rf {} + 2>/dev/null
  fi
  [[ -n "${SCRATCH:-}" && -d "$SCRATCH" ]] && rm -rf "$SCRATCH"
  return 0
}

# ── the run ──

create() { (cd "$REPO" && "$OG" --no-attach </dev/null); }

main() {
  preflight
  say "og e2e: owner $OWNER"
  trap 'teardown' EXIT
  trap 'exit 130' INT TERM
  teardown   # an earlier run that crashed left these behind
  setup_world
  say "og e2e: $NAME"
  check "og --no-attach creates the sandbox" create
  summary
}

# OG_E2E_SOURCE=1: define the functions and return (og's own tests read them)
[[ "${OG_E2E_SOURCE:-}" == 1 ]] && return 0 2>/dev/null
main "$@"
