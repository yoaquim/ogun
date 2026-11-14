#!/usr/bin/env bash
# og's tab completion in the shells a Mac has: every case of completion.test.sh again
# under bash 3.2 (macOS's /bin/bash) and under zsh (the Mac's default shell, through
# completion.zsh, with bash 3.2 answering when it's here), and one real Tab in zsh.
# A shell that isn't here is a skip; the test container has both (bash 3.2 built
# from GNU's source as bash3.2), so CI runs every case.
# shellcheck disable=SC2016  # the bash -c bodies expand in the child, on purpose
set -uo pipefail
# shellcheck source=/dev/null
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
echo "og completion, in a Mac's shells"

skip() { echo "  skip  $1"; [[ -n "${TEST_SKIPS:-}" ]] && printf '%s\n' "$(basename "$0")" >> "$TEST_SKIPS"; }

# nothing newer than bash 3.2 in the file itself, whichever shells are here
bash4() { ! grep -vE '^[[:space:]]*#' "$OGUN/completion.bash" \
    | grep -nE 'mapfile|readarray|(declare|local|typeset) -[aA]*[An]|\$\{[A-Za-z_][A-Za-z_0-9]*(,,?|\^\^?)\}|;;&|[^;];&|\|&|\[-1\]|coproc|EPOCH'; }
expect_cmd 0 "completion.bash uses nothing bash 3.2 lacks (mapfile, associative arrays, case changes, ;&, |&)" bash4

# every case of completion.test.sh, under <shell>: its own lines shown when one fails
under() { local o; o=$(env "$@" bash "$OGUN/tests/sh/completion.test.sh" 2>&1) && return 0
  grep -E 'FAIL|failed' <<<"$o" | head -n 10; return 1; }

B32="$(command -v bash3.2 || true)"
if [[ -n "$B32" ]]; then
  expect_cmd 0 "every completion case passes under bash 3.2 ($("$B32" -c 'echo "$BASH_VERSION"'))" under OG_COMP_SHELL="$B32"
else
  skip "every completion case under bash 3.2: no bash3.2 here (the test container has one)"
fi

# zsh's own `bash` is bash 3.2 when it's here: what a stock Mac's zsh finds
BIN32="$TEST_TMP/bash32"
if [[ -n "$B32" ]]; then mkdir -p "$BIN32" && ln -s "$B32" "$BIN32/bash"; fi
if command -v zsh >/dev/null; then
  expect_cmd 0 "every completion case passes under zsh${B32:+, bash 3.2 answering}" \
    under OG_COMP_SHELL=zsh OG_COMP_PATH="${B32:+$BIN32:}"

  # one real Tab: an interactive zsh in a pseudo-terminal, `og tak` and Tab typed, then
  # the line echoed back, as the Tab left it
  real_tab() { timeout 60 zsh -fc '
      zmodload zsh/zpty || exit 2
      zpty t env HOME="$1" PATH="$2" TERM=dumb zsh -f -i
      zpty -w t "bindkey -e; PS1=\"> \"; source \"\$OGUN/completion.bash\""
      sleep 2
      zpty -w -n t $'"'"'og tak\t'"'"'
      sleep 2
      zpty -w -n t $'"'"'\x01print -r -- TABBED: \n'"'"'
      out=""; for i in {1..50}; do zpty -r -t t line && out+=$line || sleep 0.1; [[ $out == *"TABBED: og take"* ]] && break; done
      zpty -d t
      [[ $out == *"TABBED: og take"* ]]' _ "$TEST_TMP/tab-home" "${B32:+$BIN32:}$PATH"; }
  mkdir -p "$TEST_TMP/tab-home"
  expect_cmd 0 "a real Tab in zsh: og tak<Tab> becomes og take" real_tab
else
  skip "every completion case under zsh, and a real Tab: no zsh here (the test container has it)"
fi

summarize
