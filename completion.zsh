# og's tab completion in zsh. completion.bash works out what a Tab offers, run by bash
# (any from 3.2, the one a Mac ships), so both shells offer the same; this hands its
# answer to zsh. completion.bash sources it when zsh sources completion.bash.

_OG_DIR=${${(%):-%x}:A:h}

# _og_zsh: what bash offers for the words so far. The folders it reads are asked once a
# shell (bash completion.bash --dirs) and handed back each Tab, as bash keeps them
_og_zsh() {
    local -a got
    local line files=0
    if (( ! ${+_og_zsh_dirs} )); then
        typeset -ga _og_zsh_dirs
        _og_zsh_dirs=(_OG_DIRS_READ=1 ${(f)"$(bash "$_OG_DIR/completion.bash" --dirs 2>/dev/null)"})
    fi
    while IFS= read -r line; do
        if [[ $line == $'\001files' ]]; then files=1; else got+=("$line"); fi
    done < <(env "${_og_zsh_dirs[@]}" bash "$_OG_DIR/completion.bash" --complete $(( CURRENT - 1 )) "${words[@]}" 2>/dev/null)
    (( ${#got} )) || return 1
    # bash matched them to the word already (-U); files as files, so a folder ends in /;
    # anything else as bash quoted it (-Q)
    if (( files )); then compadd -U -f -- "${got[@]}"; else compadd -U -Q -- "${got[@]}"; fi
}

# zsh's completion system, started when the profile hasn't
(( ${+functions[compdef]} )) || { autoload -Uz compinit && compinit -i; }
compdef _og_zsh og ogun
