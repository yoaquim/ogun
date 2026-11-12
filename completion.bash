# shellcheck shell=bash
# og's tab completion, for og (and ogun, the same command): source this file from a shell
# profile, as setup.sh says. It defines completion and nothing else. `og help` lists
# every command (the table in src/ogun/help.py).

# og's own folder, this file's, wherever it was sourced from
_SBX_OG="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
# _sbx_og <og args…> — this folder's og, for what completion asks of it: its folders
# and the MCP servers. og reads its own settings (~/.config/ogun/config.toml)
_sbx_og() { "$("$_SBX_OG/bin/venv")/bin/og" "$@"; }

# The folders completion reads are og's settings (~/.config/ogun/config.toml or the
# environment), as og resolves them: _sbx_dirs asks og once per shell, before
# completion's helpers run in their subshells, and keeps the answer (a shell opened
# before a settings change keeps the old one). Without og yet: the shell's own value,
# else og's default. A Tab on the command word, or on a word starting with -, starts
# no og: it takes what's already known (_sbx_dirs --known).
_sbx_dirs() {
    [[ -n "${_SBX_DIRS_READ:-}" ]] && return 0
    _SBX_D_EXCHANGE=${SBX_EXCHANGE:-$HOME/sandboxes.noindex} _SBX_D_PROJECTS=${SBX_PROJECTS:-$HOME/Projects}
    _SBX_D_STATE=${SBX_OGUN_DIR:-$HOME/.config/sbx/ogun} _SBX_D_TEMPLATES=${XDG_CONFIG_HOME:-$HOME/.config}/ogun/templates
    [[ "${1:-}" == --known ]] && return 0
    local k v
    while IFS=$'\t' read -r k v; do
        case "$k" in
            SBX_EXCHANGE) _SBX_D_EXCHANGE=$v ;; SBX_PROJECTS) _SBX_D_PROJECTS=$v ;;
            SBX_OGUN_DIR) _SBX_D_STATE=$v ;; TEMPLATES) _SBX_D_TEMPLATES=$v ;;
        esac
    done < <(_sbx_og internal paths 2>/dev/null)
    _SBX_DIRS_READ=1
}

# ── templates: recipes in og's config folder, images on this Mac ─────────────
# the recipes `og template <TAB>` offers: <name>.sh in og's templates folder
_sbx_template_name_ok() { [[ "$1" =~ ^[a-z0-9][a-z0-9-]{0,40}$ ]]; }   # = template.py NAME_RE (tests/sh/shared-values.test.sh)
_sbx_template_recipes() {   # every recipe name, sorted
    local f n
    _sbx_dirs
    for f in "$_SBX_D_TEMPLATES"/*.sh; do
        [[ -f "$f" ]] || continue
        n=${f##*/}; n=${n%.sh}
        _sbx_template_name_ok "$n" && printf '%s\n' "$n"
    done
}

# ── gateway MCP servers: `og mcp`, in Python (src/ogun/mcp.py) ─────
# _sbx_mcp_registry — every server this Mac's registry gives, with who gets it (completion)
_sbx_mcp_registry() { _sbx_og internal mcp-registry 2>/dev/null; }
# ── sandbox file exchange ─────────────────────────────────────────────────
# completion reads a box's out/ from the host side, never from inside the sandbox

# Boxes: every sandbox's own writable out/ (and in/) lives in boxes/<name>/ (og's folders.box).
_sbx_exchange_box() {   # <name> → the box dir; rc 1 when the sandbox has none yet
    _sbx_dirs
    [[ -d "$_SBX_D_EXCHANGE/boxes/$1" ]] && { printf '%s\n' "$_SBX_D_EXCHANGE/boxes/$1"; return 0; }
    return 1
}

# _sbx_name_chars <name> — the characters alone, any length: what keeps a name
# safe in a host path, before completion reads a box (og's own check is
# core/naming.py's name_chars: tests/sh/shared-values.test.sh). A sandbox made with plain sbx
# can be named past 61 characters, so only the characters are checked here.
_sbx_name_chars() { [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; }

# tab completion
# give: files (and, as the first argument, sandbox names too: a file there goes to
# inbox/). take <name>: the files waiting in that sandbox's out/, read from the
# host side of the exchange, never from inside the sandbox. -o filenames makes a
# directory complete with a slash and no space, so you can keep descending.
# Every other command completes what its table entry takes, in its place: names
# where a name goes, its subcommands and flags after — never the command list.
# every command's name, as text: a Tab starts no program for it. The same list as
# src/ogun/help.py's COMMANDS (tests/sh/shared-values.test.sh)
_SBX_COMP_CMDS="ls attach sh ports doctor stop ssh rm net allow style skills policy log pass token give ship take scan tidy project mcp template help"
_sbx_comp_cmds() { printf '%s\n' $_SBX_COMP_CMDS; }
_sbx_comp_words() { mapfile -t COMPREPLY < <(compgen -W "$1" -- "$cur"); }   # <words>, against the caller's $cur
# the sandbox names og last saw (core/sbx.py keeps the file): a Tab never asks the
# sandbox daemon. No file yet (og hasn't listed on this Mac): sbx, as before. A word
# starting with - is never a name: nothing is read for it
# the owners SBX_PROJECTS names: each per-owner folder's subfolders, each folder=owner's owner
_sbx_comp_owners() {
    local part w IFS=:
    for part in $_SBX_D_PROJECTS; do
        if [[ "$part" == *=* ]]; then echo "${part##*=}"; continue; fi
        part=${part/#\~/$HOME}
        for w in "$part"/*/; do [[ -d "$w" ]] && basename "$w"; done
    done
}

_sbx_comp_names() {
    [[ "${cur:-}" == -* ]] && return 0
    _sbx_dirs --known   # read already for any word but the command's (_og_complete_args)
    if [[ -s "$_SBX_D_STATE/sandbox-names" ]]; then cat "$_SBX_D_STATE/sandbox-names"
    else sbx ls 2>/dev/null | awk 'NR>1{print $1}'; fi
}
# `--help` works anywhere in a known command (og checks every
# argument), so a word starting with `-` there is offered it too, once
_og_complete() {
    _og_complete_args
    local cur=${COMP_WORDS[COMP_CWORD]} cmd=${COMP_WORDS[1]:-}
    (( COMP_CWORD >= 2 )) && [[ -n "$cmd" && "$cur" == -* && "--help" == "$cur"* ]] || return 0
    grep -qxF -- "$cmd" < <(_sbx_comp_cmds) || return 0
    [[ " ${COMP_WORDS[*]:1:COMP_CWORD-1} " == *" --help "* || " ${COMP_WORDS[*]:1:COMP_CWORD-1} " == *" -h "* ]] && return 0
    [[ " ${COMPREPLY[*]} " == *" --help "* ]] || COMPREPLY+=(--help)
}
_og_complete_args() {
    local cur=${COMP_WORDS[COMP_CWORD]} prev=${COMP_WORDS[COMP_CWORD-1]:-} names box w
    local cmd=${COMP_WORDS[1]:-}
    # read here, in this shell: the helpers below run in subshells, which would lose it
    (( COMP_CWORD >= 2 )) && [[ "$cmd" != help && "$cur" != -* ]] && _sbx_dirs
    case "$cmd:$COMP_CWORD" in
        *:1) ;;   # the command (or a sandbox name) itself: below
        give:*)
            compopt -o filenames 2>/dev/null
            # --clip first, or right after the sandbox's name; files anywhere
            if (( COMP_CWORD == 2 )); then names="--clip $(_sbx_comp_names)"; elif (( COMP_CWORD == 3 )); then names=--clip; fi
            mapfile -t COMPREPLY < <(compgen -W "${names:-}" -- "$cur"; compgen -f -- "$cur")
            return ;;
        allow:2|net:2) _sbx_comp_words "--all $(_sbx_comp_names)"; return ;;
        net:*)   # one of the three, until one is given; the domains are yours to type
            local acts="--read-only --deny --rm"
            for w in "${COMP_WORDS[@]:3:COMP_CWORD-3}"; do case "$w" in --read-only|--deny|--rm) acts="" ;; esac; done
            _sbx_comp_words "$acts"; return ;;
        allow:*) _sbx_comp_words --read-only; return ;;
        log:*) [[ "$prev" == -n ]] && COMPREPLY=() || _sbx_comp_words "-n -v --json"; return ;;
        take:2|attach:2|sh:2|ssh:2|pass:2|ports:2) _sbx_comp_words "$(_sbx_comp_names)"; return ;;
        stop:*) _sbx_comp_words "--all $(_sbx_comp_names)"; return ;;
        take:*)
            COMPREPLY=()
            _sbx_name_chars "${COMP_WORDS[2]}" || return
            box=$(_sbx_exchange_box "${COMP_WORDS[2]}" 2>/dev/null) && [[ -d "$box/out" ]] || return
            mapfile -t COMPREPLY < <(compgen -W "--all" -- "$cur"
                find "$box/out" -mindepth 1 -maxdepth 1 -print0 2>/dev/null \
                    | while IFS= read -r -d '' f; do f=${f##*/}; [[ "$f" == "$cur"* ]] && printf '%q\n' "$f"; done)
            return ;;
        rm:*)   # the flag and the name, in either order: offer whichever is still missing
            local force="--force --if-clean" nm; nm=$(_sbx_comp_names)
            for w in "${COMP_WORDS[@]:2:COMP_CWORD-2}"; do case "$w" in --force|-f|--if-clean) force="" ;; -*) ;; *) nm="" ;; esac; done
            _sbx_comp_words "$force $nm"; return ;;
        pass:3) COMPREPLY=(); return ;;   # the ENV name: yours to type
        token:2) _sbx_comp_words "personal $(_sbx_comp_owners)"; return ;;
        pass:*) case "$prev" in --item|--vault|--field) COMPREPLY=() ;; *) _sbx_comp_words "--expose --paste --item --vault --field" ;; esac; return ;;
        template:2) _sbx_comp_words "ls rm $(_sbx_template_recipes)"; return ;;
        template:3) [[ "${COMP_WORDS[2]}" == ls ]] && _sbx_comp_words --json || COMPREPLY=(); return ;;
        project:2) _sbx_comp_words "ls add"; return ;;
        mcp:2) _sbx_comp_words "ls auth load"; return ;;
        mcp:3) case "${COMP_WORDS[2]}" in ls) _sbx_comp_words --json ;; auth) _sbx_comp_words "--all $(_sbx_mcp_registry | cut -f1)" ;; load) _sbx_comp_words "$(_sbx_comp_names)" ;; *) COMPREPLY=() ;; esac; return ;;
        mcp:*) COMPREPLY=(); return ;;
        project:*) case "${COMP_WORDS[2]}" in ls) _sbx_comp_words --json ;; add) _sbx_comp_words --write ;; *) COMPREPLY=() ;; esac; return ;;
        ls:2) _sbx_comp_words --json; return ;;
        tidy:2) _sbx_comp_words --rm; return ;;
        help:2) _sbx_comp_words "$(_sbx_comp_cmds)"; return ;;
        ship:2) _sbx_comp_words "$(_sbx_comp_names)"; return ;;
        ship:*) [[ "$prev" == --* ]] && COMPREPLY=() || _sbx_comp_words "--remote --branch --base --commits --tree"; return ;;
        attach:*|sh:*|ssh:*|ls:*|tidy:*|policy:*|scan:*|template:*|help:*|token:*|skills:*)
            COMPREPLY=(); return ;;
        *)  # `ogun <name> …`: the create/attach flags, and what the one before wants
            case "$prev" in
                --org) _sbx_comp_words "$(_sbx_comp_owners)" ;;
                --item|--name) COMPREPLY=() ;;
                *)  # flags may come first (`og --sync cub`): names too, until one is given
                    local have="" skip=0
                    for w in "${COMP_WORDS[@]:1:COMP_CWORD-1}"; do
                        if (( skip )); then skip=0; continue; fi
                        case "$w" in --org|--item) skip=1 ;; --name) have=1; skip=1 ;; -*) ;; *) have=1 ;; esac
                    done
                    _sbx_comp_words "--rm --sync --no-attach --appa --org --item --name --help ${have:+ }$([[ -n "$have" ]] || _sbx_comp_names)" ;;
            esac
            return ;;
    esac
    names=$(_sbx_comp_names)
    # the commands (_SBX_COMP_CMDS, kept equal to help.py's table by tests/sh/shared-values.test.sh)
    mapfile -t COMPREPLY < <(compgen -W "$(_sbx_comp_cmds) --rm --sync --no-attach --appa --org --item --name --help $names" -- "$cur")
}
complete -F _og_complete ogun og
