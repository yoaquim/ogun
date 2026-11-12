#!/usr/bin/env bash
# Values og's completion (completion.bash) and og's Python each define on their own.
# Nothing imports one from the other, so this suite is what keeps them equal: a change
# on one side fails here until the other follows. A check written as code (a regex in
# a bash function) is compared by running both sides on the same inputs.
#   - a template name: NAME_RE (src/ogun/sandbox/template.py) and _sbx_template_name_ok
#   - every command's name: help.py's COMMANDS and _SBX_COMP_CMDS (a Tab starts no og)
#   - a sandbox name's characters: core/naming.py's name_chars and _sbx_name_chars,
#     completion holding no other copy
#   - a sandbox's exchange box: _sbx_exchange_box and folders.box
# shellcheck disable=SC2016  # the bash -c bodies expand in the child, on purpose
set -uo pipefail
# shellcheck source=/dev/null
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
og_python_or_skip   # og's Python runs these: built by setup.sh
echo "shared values: bash and Python agree"

FIX="$TEST_TMP/shared-values"; mkdir -p "$FIX"
export FIX

# py <expr> — a value from og's template.py, as JSON
py() {
  "$OG_PY" -I - "$OGUN/src" "$1" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1])
from ogun.sandbox import template
print(json.dumps(eval(sys.argv[2], vars(template))))
PY
}
export -f py

# every printable ASCII character, alone and after a valid first one: a sample
# of names can't show two checks accept the same SET, the whole alphabet can
ASCII="$(python3 -c "print(\"\".join(chr(c) for c in range(32, 127)))")"; export ASCII
expect_cmd 0 "a template name: the bash check's pattern is NAME_RE's, anchored" \
  bash -c 'b=$(grep -m1 "^_sbx_template_name_ok()" "$OGUN/completion.bash" | sed -E "s/.*=~ \^(.*)\\$ \]\].*/\1/")
           [ "$b" = "$(py NAME_RE.pattern | jq -r .)" ]'
expect_cmd 0 "…and both sides agree on every printable character, first and later" \
  bash -c '. "$OGUN/completion.bash"; R=$(py NAME_RE.pattern | jq -r .)
           for ((i = 0; i < ${#ASCII}; i++)); do c=${ASCII:i:1}
             for n in "$c" "a$c"; do
               b=no; _sbx_template_name_ok "$n" && b=yes
               p=no; python3 -c "import re,sys; sys.exit(0 if re.fullmatch(sys.argv[1], sys.argv[2]) else 1)" "$R" "$n" && p=yes
               [ "$b" = "$p" ] || { echo "disagree on [$n]: bash $b, py $p"; exit 1; }
             done
           done'
expect_cmd 0 "a template name: NAME_RE and _sbx_template_name_ok accept and refuse the same names" \
  bash -c '. "$OGUN/completion.bash"
           A41=$(printf "a%.0s" {1..41}); A42=$(printf "a%.0s" {1..42})
           for n in home work a 0 a-b a1-2 "$A41" "$A42" "" -a A Home a_b a.b "a b" "a;b"; do
             b=no; _sbx_template_name_ok "$n" && b=yes
             p=$(python3 -c "import re,sys; print(\"yes\" if re.fullmatch(sys.argv[1], sys.argv[2]) else \"no\")" "$(py NAME_RE.pattern | jq -r .)" "$n")
             [ "$b" = "$p" ] || { echo "disagree on [$n]: bash $b, py $p"; exit 1; }
           done'

expect_cmd 0 "every command's name: completion's list is help.py's table, in its order" \
  bash -c '. "$OGUN/completion.bash"
           p=$("$OG_PY" -I -c "import sys; sys.path.insert(0, sys.argv[1]); from ogun import help; print(\" \".join(help.COMMANDS))" "$OGUN/src")
           [ -n "$p" ] && [ "$_SBX_COMP_CMDS" = "$p" ] || { echo "completion [$_SBX_COMP_CMDS], help.py [$p]"; exit 1; }'

# _sbx_name_chars gates completion's reads of the exchange
expect_cmd 0 "a sandbox name's characters: name_chars and _sbx_name_chars agree on every printable character" \
  bash -c '. "$OGUN/completion.bash"
           N=(""); for ((i = 0; i < ${#ASCII}; i++)); do c=${ASCII:i:1}; N+=("$c" "a$c" "$(printf "a%.0s" {1..70})$c"); done
           p=$("$OG_PY" -I -c "import sys; sys.path.insert(0, sys.argv[1]); from ogun.core import naming; print(\"\".join(\"y\" if naming.name_chars(n) else \"n\" for n in sys.argv[2:]))" "$OGUN/src" "${N[@]}")
           b=; for n in "${N[@]}"; do if _sbx_name_chars "$n"; then b+=y; else b+=n; fi; done
           [ "$b" = "$p" ] || { echo "py $p"; echo "sh $b"; exit 1; }'
expect_cmd 0 "…and completion has no other copy of the name check, nor any of the reserved list (og's Python holds that)" \
  bash -c 'F="$OGUN/completion.bash"
           [ "$(grep -cF "[A-Za-z0-9][A-Za-z0-9._-]" "$F")" = 1 ] && ! grep -qE "inbox.shared.boxes" "$F"'


same_box() {   # the bash box lookup (fast, no Python start) and folders.box: one answer
  local ex; ex=$(mktemp -d)
  mkdir -p "$ex/boxes/new/out" "$ex/toplevel/out" "$ex/notabox"
  local n b p
  for n in new toplevel notabox missing; do
    b=$(SBX_EXCHANGE="$ex" bash -c '. "$1/completion.bash" >/dev/null 2>&1; _sbx_exchange_box "$2"' _ "$OGUN" "$n")
    p=$(SBX_EXCHANGE="$ex" "$OG_PY" -I -c 'import sys; sys.path.insert(0, sys.argv[1]); from ogun.exchange import folders; print(folders.box(sys.argv[2]) or "")' "$OGUN/src" "$n")
    [ "$b" = "$p" ] || { echo "$n: bash '$b' python '$p'"; return 1; }
  done; }
expect_cmd 0 "a sandbox's exchange box: the bash lookup and the Python one agree on every layout" same_box

summarize
