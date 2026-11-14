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
# a folder completes with a slash in every bash: per word with compopt where there is one,
# for the whole command in bash 3.2, which has none
filenames() { "$1" -c '. "$OGUN/completion.bash"; complete -p og' | grep -q -- "$2"; }
expect_cmd 1 "in a bash with compopt, og's completion asks for -o filenames per word, not for all" filenames bash "-o filenames"
if [[ -n "$B32" ]]; then
  expect_cmd 0 "every completion case passes under bash 3.2 ($("$B32" -c 'echo "$BASH_VERSION"'))" under OG_COMP_SHELL="$B32"
  expect_cmd 0 "…where, with no compopt, og's completion is registered with -o filenames" filenames "$B32" "-o filenames"
  # og take's names there are left for readline to quote, as -o filenames does: quoted by og
  # too, `with space.txt` would arrive as with\\\ space.txt
  plain() { mkdir -p "$TEST_TMP/ex32/boxes/cub/out" && touch "$TEST_TMP/ex32/boxes/cub/out/with space.txt"
    "$B32" -c '. "$OGUN/completion.bash"; _OG_DIRS_READ=1 _OG_D_EXCHANGE="$1"
      COMP_WORDS=(og take cub with); COMP_CWORD=3; _og_complete; printf "%s\n" "${COMPREPLY[@]}"' _ "$TEST_TMP/ex32" \
      | grep -qxF "with space.txt"; }
  expect_cmd 0 "…so og take's names go to readline unquoted, which quotes them once" plain
else
  skip "every completion case under bash 3.2: no bash3.2 here (the test container has one)"
fi

# zsh's own `bash` is bash 3.2 when it's here: what a stock Mac's zsh finds
BIN32="$TEST_TMP/bash32"
if [[ -n "$B32" ]]; then mkdir -p "$BIN32" && ln -s "$B32" "$BIN32/bash"; fi
if command -v zsh >/dev/null; then
  expect_cmd 0 "every completion case passes under zsh${B32:+, bash 3.2 answering}" \
    under OG_COMP_SHELL=zsh OG_COMP_PATH="${B32:+$BIN32:}"

  # completion.zsh found beside the file sourced, whatever zsh sets $0 to, never in the
  # folder the shell is in
  argzero() { mkdir -p "$TEST_TMP/elsewhere" && printf 'print planted\n' > "$TEST_TMP/elsewhere/completion.zsh"
    local o; o=$(cd "$TEST_TMP/elsewhere" && zsh -fc 'setopt posix_argzero; source "$OGUN/completion.bash"; (( $+functions[_og_zsh] ))') \
      && [[ "$o" != *planted* ]]; }
  expect_cmd 0 "with POSIX_ARGZERO set, zsh still loads og's own completion.zsh, not one in the current folder" argzero
  # a real Tab: an interactive zsh in a pseudo-terminal, its profile <zshrc>, <keys> typed
  # (a Tab among them), then the line printed back as the Tab left it: <want>
  tab() { local z; z=$(mktemp -d "$TEST_TMP/zdot.XXXX"); printf '%s\n' "$1" > "$z/.zshrc"
    ( cd "$TEST_TMP/tab-cwd" && timeout 60 zsh -fc '
      zmodload zsh/zpty || exit 2
      zpty t env HOME="$1" ZDOTDIR="$2" PATH="$3" TERM=dumb OGUN="$OGUN" zsh -i
      sleep 2
      zpty -w -n t "$4"
      sleep 3
      zpty -w -n t $'"'"'\x01print -r -- TABBED: \n'"'"'
      out=""; for i in {1..80}; do zpty -r -t t line && out+=$line || sleep 0.1; [[ $out == *"TABBED: $5"* ]] && break; done
      zpty -d t
      [[ $out == *"TABBED: $5"* ]]' _ "$TEST_TMP/tab-home" "$z" "${B32:+$BIN32:}$PATH" "$2" "$3" ); }
  mkdir -p "$TEST_TMP/tab-home" "$TEST_TMP/tab-cwd" && touch "$TEST_TMP/tab-cwd/with space.txt"
  rc='bindkey -e; PS1="> "'
  expect_cmd 0 "a real Tab in zsh: og tak<Tab> becomes og take" \
    tab "$rc"$'\nsource "$OGUN/completion.bash"' $'og tak\t' "og take"
  expect_cmd 0 "…with a profile that runs its own compinit after sourcing og's file (oh-my-zsh's order)" \
    tab "$rc"$'\nsource "$OGUN/completion.bash"\nautoload -Uz compinit && compinit -i' $'og tak\t' "og take"
  expect_cmd 0 "…and a file name with a space: og give cub with\\ s<Tab> becomes og give cub with\\ space.txt" \
    tab "$rc"$'\nsource "$OGUN/completion.bash"' $'og give cub with\\ s\t' "og give cub with space.txt"
else
  skip "every completion case under zsh, and a real Tab: no zsh here (the test container has it)"
fi

summarize
