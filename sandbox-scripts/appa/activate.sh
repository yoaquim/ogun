#!/usr/bin/env bash
# activate.sh <version> <workspace> [--private <host/path>]… [<read-only mount>…] — run INSIDE a sandbox by
# `ogun` at create, once the pinned appa is installed (docs/appa.md). It
# turns OpenAPPA on for this sandbox:
#   1. the marker (~/.config/ogun/appa) a provision command may read, then og's provision command again
#      (OGUN_PROVISION), which may set up ~/.claude/skills its own way; whatever it
#      leaves (or with none, OGUN_PROVISION empty), the folder is made here for OpenAPPA's skill;
#   2. OpenAPPA's Claude Code plugin, at the pinned version, without a question;
#   3. its hooks, saved: every attach's provision may rewrite settings.json, and
#      ensure.sh merges these back before each session;
#   4. Ogun's policy block in OpenAPPA's policy (policy.py), checked;
#   5. the status line clappa shows: the provision command's own, when it left one at og's hook
#      (~/.config/ogun/appa-statusline), else OpenAPPA's;
#   6. the runtime, restarted on that policy (ensure.sh).
# Any step that fails exits non-zero, saying which; ogun then removes the sandbox.
set -euo pipefail
v=$1 ws=$2; shift 2
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)   # og's bundle, unpacked for this run
prov=${OGUN_PROVISION:-}   # og's provision command (SBX_PROVISION); set by og's runner, never the sandbox's own
data=$HOME/.local/share/appa conf=$HOME/.config/appa marker=$HOME/.config/ogun/appa
fail() { echo "activate: $*" >&2; exit 1; }

mkdir -p "$(dirname "$marker")"; printf '%s\n' "$v" > "$marker"
if [[ -n "$prov" ]]; then
    bash -lc "$prov" >/dev/null || fail "the provision command failed"
fi
# whatever the provisioning left (none, or one that sets up no claude config): the folder
# its skill goes in, and a settings file for its hooks; a link there is refused below
[[ -e "$HOME/.claude/skills" || -L "$HOME/.claude/skills" ]] || mkdir -p "$HOME/.claude/skills"
[[ -f "$HOME/.claude/settings.json" ]] || echo '{}' > "$HOME/.claude/settings.json"
[[ -d "$HOME/.claude/skills" && ! -L "$HOME/.claude/skills" ]] || fail "$HOME/.claude/skills is still a link; OpenAPPA can't add its skill"

appa plugin install claude-code --no-agent-yell --json --revision "$v" >/dev/null || fail "appa plugin install claude-code failed"
[[ -x "$data/bin/appa" && -f "$conf/appa.toml" && -f "$data/clappa.settings.json" ]] || fail "the plugin install left no runtime, policy or clappa settings"

jq '(.hooks // {}) | with_entries(.value |= map(select(any(.hooks[]?; (.command // "") | endswith("/appa")))))
                  | with_entries(select(.value | length > 0))' "$HOME/.claude/settings.json" > "$data/ogun-hooks.json" \
    || fail "could not read OpenAPPA's hooks from settings.json"
[[ "$(jq length "$data/ogun-hooks.json")" -gt 0 ]] || fail "the plugin install added no hooks to settings.json"

python3 "$here/policy.py" "$conf/appa.toml" "$ws" "$@" || fail "could not write Ogun's policy block"
"$data/bin/appa" describe --config "$conf/appa.toml" --check >/dev/null || fail "OpenAPPA rejects the policy with Ogun's block ($conf/appa.toml)"

# the provision command's own status line, when it left one at og's hook: else the plugin's own stays
hook=$HOME/.config/ogun/appa-statusline
if [[ -x "$hook" ]]; then
    jq --arg c "\"$hook\"" '.statusLine = {type: "command", command: $c}' \
        "$data/clappa.settings.json" > "$data/clappa.settings.json.tmp" || fail "could not set the status line clappa uses"
    mv -f "$data/clappa.settings.json.tmp" "$data/clappa.settings.json"
fi

"$data/bin/appa" runtime stop >/dev/null 2>&1 || true
"$here/ensure.sh" || fail "the runtime didn't start on the new policy"
echo "OpenAPPA $v on"
