#!/usr/bin/env bash
# _og_complete — tab completion for `og give`, `og take` and `og allow` arguments.
#   og give <TAB>          sandbox names AND files (a file there goes to inbox/)
#   og give <name> <TAB>…  files only, with -o filenames so a directory completes
#                          with a slash and no space
#   og take <TAB>          sandbox names
#   og take <name> <TAB>…  the files in that sandbox's out/, read from the host
#                          side of the exchange (never from inside the sandbox)
#   og allow <TAB>         sandbox names and --all
# Every other command completes what its table entry takes, in its place (names,
# then its subcommands and flags), and `og <name> …` offers the create flags,
# with --org completing owner folders. `sbx` is stubbed; `compopt` is stubbed to
# record what was asked of readline, since it only works inside real completion.
# shellcheck disable=SC2016  # the bash -c bodies expand in the child, on purpose
set -uo pipefail
# shellcheck source=/dev/null
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
echo "og completion"

FIX="$TEST_TMP/completion"
mkdir -p "$FIX/projects/umbrella" "$FIX/projects/hooli" "$FIX/bin" "$FIX/cwd/subdir" "$FIX/home/Downloads" "$FIX/ex/boxes/cub/out" "$FIX/ex/boxes/empty/out"
touch "$FIX/cwd/report.pdf" "$FIX/cwd/notes.md" "$FIX/ex/boxes/cub/out/summary.pdf" "$FIX/ex/boxes/cub/out/with space.txt"
printf '#!/bin/sh\necho "$*" >> "%s/sbx.log"\n[ "$1" = ls ] && printf "SANDBOX  AGENT  STATUS\\ncub  claude  running\\nfern  claude  stopped\\n"\nexit 0\n' "$FIX" > "$FIX/bin/sbx"
chmod +x "$FIX/bin/sbx"
export FIX
# og's templates folder holds the recipes: og's test ones
mkdir -p "$FIX/home/.config/ogun" && ln -s "$OGUN/tests/fixtures/templates" "$FIX/home/.config/ogun/templates"

# comp <word>… — complete the LAST word of `og <words>`, in $FIX/cwd; prints one
# candidate per line (sorted), then `compopt:<args>` if compopt was called.
comp() {
  ( cd "$FIX/cwd" && HOME="$FIX/home" PATH="$FIX/bin:$PATH" OG_EXCHANGE="$FIX/ex" OG_PROJECTS="${PROJ:-$FIX/projects}" bash -c '
      [[ -n "${COMP_FILE_ONLY:-}" ]] && unset OG_EXCHANGE OG_PROJECTS   # the settings file alone says where
      . "$OGUN/completion.bash"
      compopt() { printf "compopt:%s\n" "$*" >> "$FIX/compopt.log"; }
      rm -f "$FIX/compopt.log"
      COMP_WORDS=(og "$@"); COMP_CWORD=$#
      _og_complete
      printf "%s\n" "${COMPREPLY[@]}" | sort
      cat "$FIX/compopt.log" 2>/dev/null' _ "$@" )
}
export -f comp
has() { grep -qxF -- "$2" <<<"$1"; }
export -f has

expect_cmd 0 "og give <TAB>: sandbox names and files, directories included" \
  bash -c 'o=$(comp give ""); has "$o" cub && has "$o" fern && has "$o" report.pdf && has "$o" subdir'
expect_cmd 0 "…with -o filenames, so a directory completes with a slash and no space" \
  bash -c 'has "$(comp give "")" "compopt:-o filenames"'
expect_cmd 0 "og give cub <TAB>: files only, no sandbox names" \
  bash -c 'o=$(comp give cub ""); has "$o" report.pdf && has "$o" notes.md && has "$o" subdir && ! has "$o" cub && ! has "$o" fern'
expect_cmd 0 "og give cub ~/Dow<TAB>: a tilde path completes (the case that completed nothing)" \
  bash -c 'has "$(comp give cub "~/Dow")" "~/Downloads"'
expect_cmd 0 "…and every later argument keeps completing files" \
  bash -c 'o=$(comp give cub report.pdf no); has "$o" notes.md && has "$o" "compopt:-o filenames"'
expect_cmd 0 "og take <TAB>: sandbox names" \
  bash -c 'o=$(comp take ""); has "$o" cub && has "$o" fern && ! has "$o" report.pdf'
mkdir -p "$FIX/ex/sandboxes/sessions/oldbox/out" && touch "$FIX/ex/sandboxes/sessions/oldbox/out/old.txt"
expect_cmd 0 "og take <name> <TAB> reads only boxes/ (and the flat layout): the old sandboxes/ ones are gone" \
  bash -c '[ -z "$(comp take oldbox "" | grep -v -e --all -e compopt)" ]'
expect_cmd 0 "og take cub <TAB>: the files in its out/, plus --all" \
  bash -c 'o=$(comp take cub ""); has "$o" summary.pdf && has "$o" --all && has "$o" "with\\ space.txt" && ! has "$o" report.pdf'
expect_cmd 0 "…filtered by what's typed" \
  bash -c 'o=$(comp take cub su); has "$o" summary.pdf && ! has "$o" "with\\ space.txt" && ! has "$o" --all'
expect_cmd 0 "og take <name with no box> <TAB>: nothing, and no error" \
  bash -c '[ -z "$(comp take nobox "")" ]'
expect_cmd 0 "og take ../escape <TAB>: an invalid name reads nothing outside the exchange" \
  bash -c '[ -z "$(comp take ../cwd "")" ]'
expect_cmd 0 "og allow <TAB>: sandbox names and --all, no files" \
  bash -c 'o=$(comp allow ""); has "$o" cub && has "$o" fern && has "$o" --all && ! has "$o" report.pdf'
# ── every other command: what its table entry takes, never the command list ──
only() { [ "$(printf "%s\n" "$1" | grep -v "^compopt:" | sort | tr "\n" " ")" = "$2" ]; }   # <output> <expected, sorted, space-joined + trailing space>
export -f only
expect_cmd 0 "og attach|sh|ssh|pass <TAB>: sandbox names only — no commands, no flags" \
  bash -c 'for c in attach sh ssh pass; do only "$(comp $c "")" "cub fern " || { echo "$c: $(comp $c "")"; exit 1; }; done'
expect_cmd 0 "…and nothing after the name for attach, sh and ssh" \
  bash -c 'for c in attach sh ssh; do [ -z "$(comp $c cub "")" ] || { echo "$c"; exit 1; }; done'
expect_cmd 0 "og rm <TAB>: names, --force and --if-clean; og rm cub <TAB>: the flags, once (either one ends it)" \
  bash -c 'only "$(comp rm "")" "--force --if-clean cub fern " && only "$(comp rm cub "")" "--force --if-clean " \
           && [ -z "$(comp rm cub --force "")" ] && [ -z "$(comp rm cub --if-clean "")" ]'
expect_cmd 0 "…the flag first works too: og rm --force|-f <TAB> offers the names, and -f counts as --force" \
  bash -c 'only "$(comp rm --force "")" "cub fern " && only "$(comp rm -f "")" "cub fern " && [ -z "$(comp rm -f cub "")" ]'
expect_cmd 0 "og pass cub <TAB>: nothing (the ENV is yours); then its flags; nothing after a flag that takes a value" \
  bash -c '[ -z "$(comp pass cub "")" ] && only "$(comp pass cub KEY "")" "--expose --field --item --paste --vault " && [ -z "$(comp pass cub KEY --item "")" ]'
expect_cmd 0 "og template <TAB>: ls and every recipe; og template ls <TAB>: --json" \
  bash -c 'o=$(comp template ""); has "$o" ls && has "$o" work && has "$o" home && ! has "$o" cub && only "$(comp template ls "")" "--json " && [ -z "$(comp template work "")" ]'
expect_cmd 0 "…read from og's templates folder: completion reaches nowhere above og's own folder" \
  bash -c '! grep -nF "/../.." "$OGUN/completion.bash"'
expect_cmd 0 "og project <TAB>: ls add; ls → --json, add → --write" \
  bash -c 'only "$(comp project "")" "add ls " && only "$(comp project ls "")" "--json " && only "$(comp project add repo "")" "--write "'
expect_cmd 0 "og ls <TAB>: --json; og tidy <TAB>: --rm; og help <TAB>: the commands" \
  bash -c 'only "$(comp ls "")" "--json " && only "$(comp tidy "")" "--rm " && o=$(comp help ""); has "$o" ship && has "$o" template && ! has "$o" cub'
expect_cmd 0 "og net: --all or a sandbox, then one of --read-only, --deny, --rm until one is given; never the create flags" \
  bash -c 'o=$(comp net ""); has "$o" cub && has "$o" --all && ! has "$o" --sync \
           && only "$(comp net cub x.example "")" "--deny --read-only --rm " && [ -z "$(comp net cub x.example --rm "")" ]'
expect_cmd 0 "og give: --clip first or after the sandbox, with the sandboxes and files" \
  bash -c 'has "$(comp give --c)" --clip && has "$(comp give cub --c)" --clip && o=$(comp give ""); has "$o" cub && has "$o" --clip'
expect_cmd 0 "…og allow offers --read-only after the sandbox; og log its own flags" \
  bash -c 'only "$(comp allow cub "")" "--read-only " && only "$(comp log "")" "--json -n -v " && [ -z "$(comp log -n "")" ]'
# og mcp auth's servers come from og (_og_mcp_registry): this Mac's registry, its valid names only
mkdir -p "$FIX/mcp/fern" "$FIX/mcp/cub"
printf '{"mcp": ["notes"], "repos": {"fern": {"path": "%s", "mcp": ["db-fern"]}, "cub": {"path": "%s", "mcp": ["db-cub", "bad name"]}}}\n' \
  "$FIX/mcp/fern" "$FIX/mcp/cub" > "$FIX/mcp/registry.json"
# og reads it from its config folder, where a link to it is as good as the file
mkdir -p "$FIX/home/.config/ogun"; ln -sfn "$FIX/mcp/registry.json" "$FIX/home/.config/ogun/registry.json"
expect_cmd 0 "og mcp <TAB>: ls auth load" bash -c 'only "$(comp mcp "")" "auth load ls "'
# the only case here that runs og: the rest of the file needs no Python
if [[ -n "$OG_PY" ]]; then
  expect_cmd 0 "…og mcp auth <TAB>: --all and the registry's servers (through og)" \
    bash -c 'only "$(comp mcp auth "")" "--all db-cub db-fern notes "'
  # the folders completion reads are og's: set only in og's settings file, they're still the ones it reads
  mkdir -p "$FIX/home/.config/ogun" "$FIX/ex2/boxes/cub/out" "$FIX/projects2/acme"; touch "$FIX/ex2/boxes/cub/out/from-the-file.txt"
  printf 'exchange = "%s"\nprojects = "%s"\n' "$FIX/ex2" "$FIX/projects2" > "$FIX/home/.config/ogun/config.toml"
  expect_cmd 0 "og take cub <TAB> and --org <TAB> read the exchange and Projects og's settings file names" \
    bash -c 'o=$(COMP_FILE_ONLY=1 comp take cub ""); has "$o" from-the-file.txt && ! has "$o" summary.pdf \
             && only "$(COMP_FILE_ONLY=1 comp cub --org "")" "acme "'
  rm -f "$FIX/home/.config/ogun/config.toml"
else
  echo "  skip  og mcp auth <TAB>, and the folders og's settings name: og's Python isn't built here — run: $OGUN/setup.sh"
fi
expect_cmd 0 "og cub <TAB>: the create/attach flags; --org → owner folders" \
  bash -c 'only "$(comp cub "")" "--appa --help --item --name --no-attach --org --rm --sync " \
           && only "$(comp cub --org "")" "hooli umbrella " && [ -z "$(comp cub --name "")" ]'

expect_cmd 0 "flags before the name (og --sync <TAB>, og --org umbrella <TAB>): sandbox names and the flags, until a name is given" \
  bash -c 'F="--appa --help --item --name --no-attach --org --rm --sync "
           only "$(comp --sync "")" "${F}cub fern " && only "$(comp --org umbrella "")" "${F}cub fern " \
           && only "$(comp --org umbrella --sync "")" "${F}cub fern " && only "$(comp --sync cub "")" "$F" && only "$(comp --name box "")" "$F"'
expect_cmd 0 "--help inside a known command: og rm --h<TAB>, og stop cub --h<TAB>, og take cub --<TAB> offer it; typed once, never again" \
  bash -c 'only "$(comp rm --h)" "--help " && only "$(comp stop cub --h)" "--help " && has "$(comp take cub --)" --help \
           && has "$(comp take cub --)" --all && [ -z "$(comp rm --help --h)" ] && [ -z "$(comp stop -h cub --h)" ] && ! has "$(comp rm "")" --help'
expect_cmd 0 "…and --help after a sandbox name or a leading flag: og cub --h<TAB>, og --sync --h<TAB>" \
  bash -c 'only "$(comp cub --h)" "--help " && only "$(comp --sync --h)" "--help "'
expect_cmd 0 "og t<TAB> still completes commands: the table's, and nothing else" \
  bash -c 'only "$(comp t)" "take template tidy token "'
expect_cmd 0 "og give<TAB> (the command word itself) still completes commands, no files" \
  bash -c 'o=$(comp giv); has "$o" give && ! has "$o" report.pdf'


# ── speed: a Tab starts no program for what it already knows ──
# the sandbox names og last saw, kept in a file (src/ogun/core/sbx.py): no call to sbx
cached() { mkdir -p "$TEST_TMP/names/ogun"; printf 'kept1\nkept2\n' > "$TEST_TMP/names/ogun/sandbox-names"; rm -f "$FIX/sbx.log"
  local o; o=$(XDG_STATE_HOME="$TEST_TMP/names" comp attach "")
  has "$o" kept1 && has "$o" kept2 && ! has "$o" cub && [ ! -e "$FIX/sbx.log" ]; }
expect_cmd 0 "sandbox names come from the file og keeps, and a Tab never asks sbx" cached
fallback() { rm -f "$FIX/sbx.log"; local o; o=$(XDG_STATE_HOME="$TEST_TMP/no-names" comp attach "")
  has "$o" cub && grep -q '^ls' "$FIX/sbx.log"; }
expect_cmd 0 "…with no file yet (og hasn't listed on this Mac), they come from sbx, as before" fallback
no_og() { bash -c '. "$OGUN/completion.bash"
  _og_run() { echo "og ran" >> "$FIX/og.log"; }
  COMP_WORDS=(og t); COMP_CWORD=1; cur=t; _og_complete; COMP_WORDS=(og help ""); COMP_CWORD=2; _og_complete
  COMP_WORDS=(og rm --h); COMP_CWORD=2; _og_complete'; [ ! -e "$FIX/og.log" ]; }
expect_cmd 0 "…and the command list is text: completing a command, help's argument or --help starts no og" no_og

expect_cmd 0 "og token <TAB>: personal and the owner folders under ~/Projects; then nothing" \
  bash -c 'only "$(comp token "")" "hooli personal umbrella " && [ -z "$(comp token umbrella "")" ]'

expect_cmd 0 "with several project folders, og token <TAB> and --org <TAB> name every folder's owners, and a fixed folder's owner" \
  bash -c 'mkdir -p "$FIX/work/api" && export PROJ="$FIX/projects:$FIX/work=initech"
           only "$(comp token "")" "hooli initech personal umbrella " && only "$(comp cub --org "")" "hooli initech umbrella "'
expect_cmd 0 "og skills <TAB>: nothing, it takes no arguments" \
  bash -c '[ -z "$(comp skills "")" ]'

# completion.bash is completion and nothing else: every function it adds is one of
# completion's helpers (no command to type), every variable is completion's own, and
# the only completion it registers is og's
expect_cmd 0 "completion.bash adds only completion: its helpers, its command list, and og's complete line" \
  bash -c 'mid_f=$(declare -F | cut -d" " -f3 | sort); mid_v=$(compgen -v | sort)
           . "$OGUN/completion.bash"
           now_f=$(declare -F | cut -d" " -f3 | sort); now_v=$(compgen -v | sort)
           added=$(comm -13 <(printf "%s\n" "$mid_f") <(printf "%s\n" "$now_f") | paste -sd" " -)
           want=$(printf "%s\n" _og_complete _og_complete_args _og_comp_cmds _og_comp_names _og_comp_owners _og_comp_words _og_dirs \
                  _og_exchange_box _og_mcp_registry _og_name_chars _og_run _og_template_name_ok _og_template_recipes | sort | paste -sd" " -)
           [ "$added" = "$want" ] || { echo "functions added: [$added]"; exit 1; }
           newv=$(comm -13 <(printf "%s\n" "$mid_v") <(printf "%s\n" "$now_v") | grep -vxE "mid_f|mid_v|now_f|_" | paste -sd" " -)
           [ "$newv" = "_OG_COMP_CMDS _OG_DIR" ] || { echo "variables added: [$newv]"; exit 1; }
           [ "$(complete -p | grep -E " -F _og_complete " | sed "s/.* //" | sort | paste -sd" " -)" = "og ogun" ] \
             && ! complete -p | grep -q _completesbx'

summarize
