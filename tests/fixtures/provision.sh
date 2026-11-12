#!/usr/bin/env bash
# A stand-in provision command (SBX_PROVISION) for og's OpenAPPA tests: one that sets up
# a claude config, as a provision command might. With OpenAPPA's marker
# (~/.config/ogun/appa) its skills are a folder OpenAPPA can add to, without it one link;
# a status line of its own is at og's hook (~/.config/ogun/appa-statusline) for clappa to
# point at. It says whether it saw the
# marker, so a test can tell it ran after activate.sh wrote it.
set -euo pipefail
skills=$HOME/.claude/skills
mkdir -p "$HOME/.config/ogun"
if [[ -f "$HOME/.config/ogun/appa" ]]; then
    [[ -L "$skills" ]] && rm "$skills"
    mkdir -p "$skills"
    echo "provisioned, marker $(cat "$HOME/.config/ogun/appa")" >> "$HOME/provision.log"
else
    [[ -e "$skills" || -L "$skills" ]] || ln -s "$HOME/elsewhere-skills" "$skills"
    echo "provisioned, no marker" >> "$HOME/provision.log"
fi
[[ -f "$HOME/.claude/settings.json" ]] || echo '{}' > "$HOME/.claude/settings.json"
printf '#!/bin/sh\necho stand-in\n' > "$HOME/.config/ogun/appa-statusline"
chmod +x "$HOME/.config/ogun/appa-statusline"
