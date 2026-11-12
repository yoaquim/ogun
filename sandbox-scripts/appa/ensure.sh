#!/usr/bin/env bash
# ensure.sh — run INSIDE a protected sandbox by `ogun` before every protected
# session, and by activate.sh (docs/appa.md). It puts OpenAPPA's saved hooks back into
# settings.json (a provision command may rewrite that file on any attach), checks they're
# there, and that its runtime answers. A runtime that isn't running, after a sandbox stop and
# start, is started. Exits non-zero, saying why, when either can't be had: ogun
# then doesn't start the session, rather than start one that isn't protected.
# Exit 3: OpenAPPA was installed but never turned on; ogun turns it on (activate.sh)
# and asks again.
set -euo pipefail
data=$HOME/.local/share/appa conf=$HOME/.config/appa
url=${APPA_RUNTIME_URL:-http://127.0.0.1:8787}
# how many times a started runtime is asked, 0.2s apart: an argument for the tests, never sandbox env
tries=${1:-50}
fail() { echo "ensure: $*" >&2; exit 1; }

[[ -f "$HOME/.config/ogun/appa" ]] || { echo "ensure: OpenAPPA is installed here but was never turned on" >&2; exit 3; }

[[ -s "$data/ogun-hooks.json" ]] || fail "no saved OpenAPPA hooks ($data/ogun-hooks.json)"
# each saved entry not already in its event's list goes back at its end; the rest stays as written
s=$HOME/.claude/settings.json
merged=$(jq --slurpfile want "$data/ogun-hooks.json" '
    .hooks = (reduce ($want[0] | to_entries[]) as $w (.hooks // {};
        .[$w.key] = ((.[$w.key] // []) as $have | $have + [$w.value[] | . as $e | select($have | any(. == $e) | not)])))' "$s") \
    || fail "could not read ~/.claude/settings.json"
if [[ "$merged" != "$(jq . "$s")" ]]; then
    { printf '%s\n' "$merged" > "$s.tmp" && mv -f "$s.tmp" "$s"; } || fail "could not put OpenAPPA's hooks back into ~/.claude/settings.json"
fi
missing=$(jq -rn --slurpfile want "$data/ogun-hooks.json" --slurpfile have "$HOME/.claude/settings.json" '
    [$want[0] | keys[] as $e
     | select((($have[0].hooks[$e] // []) | [.[].hooks[]?.command // ""] | any(endswith("/appa"))) | not) | $e]
    | join(" ")') || fail "could not read ~/.claude/settings.json"
[[ -z "$missing" ]] || fail "OpenAPPA's hooks are missing from settings.json for: $missing"

# clappa's status line is a script that's gone (the provision command moved it) while og's hook
# is there: point it at the hook, as activate.sh would now
cs=$data/clappa.settings.json hook=$HOME/.config/ogun/appa-statusline
cmd=$(jq -r '.statusLine.command // ""' "$cs" 2>/dev/null || true)
script=${cmd#\"}; script=${script%%\"*}
if [[ -x "$hook" && "$cmd" == \"/* && ! -e "$script" ]]; then
    if ! { jq --arg c "\"$hook\"" '.statusLine = {type: "command", command: $c}' "$cs" > "$cs.tmp" \
            && mv -f "$cs.tmp" "$cs"; }; then
        fail "could not point clappa's status line at og's hook"
    fi
fi

health() { curl -fsS --noproxy '*' -m 2 "$url/health" >/dev/null 2>&1; }
health && exit 0
# setsid: the runtime outlives the `sbx exec` that started it. The GitHub battery
# reads the sandbox's token placeholder; the proxy swaps in the real token.
APPA_PROVIDER_GITHUB_TOKEN="${GH_TOKEN:-}" setsid -f "$data/bin/appa" runtime --adapter claude-code \
    --listen "${url#http://}" --config "$conf/appa.toml" --db "$data/appa.db" \
    >>"$data/runtime.stdout.log" 2>>"$data/runtime.stderr.log" </dev/null
for _ in $(seq 1 "$tries"); do health && exit 0; sleep 0.2; done
fail "OpenAPPA's runtime didn't answer at $url (see $data/runtime.stderr.log)"
