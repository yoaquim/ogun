#!/usr/bin/env bash
# sandbox-ssh.sh <keys dir> — runs INSIDE a sandbox, from og's base.setup: SSH to
# GitHub with the keys you put in the host's ~/.ssh/sandbox (mounted
# read-only at the same path), never with the Mac's ssh-agent.
#
#   ~/.ssh/sandbox-keys/   each private key 0600 (ssh refuses group/world-readable
#                          keys, and the mount's modes and owner are the host's),
#                          plus its .pub
#   ~/.ssh/known_hosts     GitHub's host keys, pinned below — never ssh-keyscan
#   ~/.ssh/config          github.com: those keys only, no agent
#   ~/.config/git/config   commit signing, when the folder holds a key named
#                          `signing` (a GitHub *Signing* key): gpg.format ssh,
#                          user.signingkey, commit.gpgsign. Not ~/.gitconfig —
#                          sbx writes that one. That key signs only: it is left
#                          out of the github.com block (GitHub refuses a
#                          signing key for auth)
#
# Idempotent: every run rebuilds the key copies and the config from the folder
# as it is now. With no folder or no private key in it, ssh is left unset (a
# config this script wrote earlier is removed); with no signing key, signing
# is left unset (the three keys removed only while they still name ours). HTTPS with the sandbox's PAT
# stays the default for git; SSH is opt-in (git@github.com:… urls).
set -euo pipefail

src="${1:?usage: sandbox-ssh.sh <keys dir>}"
ssh_dir="$HOME/.ssh"
keys="$ssh_dir/sandbox-keys"
mark="# managed by ogun (sandbox-ssh.sh) — rewritten on every setup"
gitcfg="${XDG_CONFIG_HOME:-$HOME/.config}/git/config"
signing_pub="$keys/signing.pub"

# ours <file> — the file is a config this script wrote
ours() { [[ -f "$1" ]] && head -n1 "$1" | grep -qxF -e "$mark"; }

# signing <on|off> — commit signing with ~/.ssh/sandbox-keys/signing. Only the
# three keys are touched; off leaves them alone once they name another key.
signing() {
    local g=(git config --file "$gitcfg")
    if [[ "$1" == on ]]; then
        mkdir -p "$(dirname "$gitcfg")"
        "${g[@]}" gpg.format ssh && "${g[@]}" user.signingkey "$signing_pub" && "${g[@]}" commit.gpgsign true
    elif [[ -f "$gitcfg" && "$("${g[@]}" --get user.signingkey 2>/dev/null)" == "$signing_pub" ]]; then
        # each may already be gone (a hand edit): remove what remains, never fail
        local k; for k in user.signingkey gpg.format commit.gpgsign; do "${g[@]}" --unset "$k" || true; done
        echo "  signing key gone — commit signing turned off"
    fi
}

# GitHub's published SSH host keys (api.github.com/meta `ssh_keys`), fetched
# 2026-09-23; the test suite checks each against GitHub's fingerprint:
#   ED25519 SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU
#   ECDSA   SHA256:p2QAMXNIC1TJYWeIOttrVc98/R1BUFWu3/LiyKgUfQM
#   RSA     SHA256:uNiVztksCsDhcc0u9e8BujQXVUpKZIDTMczCvj3tD2s
github_known_hosts() {
    cat <<'KEYS'
github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl
github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=
github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk=
KEYS
}

# private keys: regular top-level files whose first line is a PEM/OpenSSH
# private-key header; symlinks are skipped (the host refuses them anyway)
privs=()
if [[ -d "$src" ]]; then
    for f in "$src"/*; do
        [[ -f "$f" && ! -L "$f" && "$f" != *.pub ]] || continue
        head -n1 "$f" 2>/dev/null | grep -q -- '-----BEGIN .*PRIVATE KEY-----' && privs+=("$f")
    done
fi

if (( ${#privs[@]} == 0 )); then
    # leave ssh unset — undo only what this script wrote
    signing off
    rm -rf "$keys"
    ours "$ssh_dir/config" && rm -f "$ssh_dir/config"
    echo "  no ssh keys in $src — ssh left unset"
    exit 0
fi

mkdir -p "$ssh_dir"; chmod 700 "$ssh_dir"
rm -rf "$keys"; mkdir -m 700 "$keys"
ids=(); sign=""
for f in "${privs[@]}"; do
    b=$(basename "$f")
    install -m 600 "$f" "$keys/$b"
    [[ -f "$f.pub" && ! -L "$f.pub" ]] && install -m 644 "$f.pub" "$keys/$b.pub"
    if [[ "$b" == signing ]]; then sign="$keys/$b"; else ids+=("$keys/$b"); fi
done

# signing: with no agent in a sandbox, only a key without a passphrase can
# sign — a locked one would fail every commit, so it is refused loudly instead
if [[ -z "$sign" ]]; then
    signing off
elif ! pub=$(ssh-keygen -y -P '' -f "$sign" 2>/dev/null </dev/null); then
    signing off
    echo "  ! $src/signing has a passphrase — a sandbox has no agent to unlock it, so commits are NOT signed. Make it without one (ssh-keygen -N '')" >&2
else
    # the .pub is derived from the private key, never trusted beside it
    printf '%s\n' "$pub" > "$signing_pub"; chmod 644 "$signing_pub"
    signing on
    echo "  commit signing on: $signing_pub (register it on GitHub as a Signing key)"
fi

# known_hosts: other hosts' entries are kept; any github.com line is replaced
# by the pinned set
kh="$ssh_dir/known_hosts"; tmp="$kh.tmp.$$"
{ [[ -f "$kh" ]] && awk '{ split($1, h, ","); for (i in h) if (h[i] == "github.com") next; print }' "$kh"
  github_known_hosts; } > "$tmp"
chmod 644 "$tmp"; mv -f "$tmp" "$kh"

# only a signing key: no key to log in with, so no github.com block
if (( ${#ids[@]} == 0 )); then
    ours "$ssh_dir/config" && rm -f "$ssh_dir/config"
    exit 0
fi

# config: a hand-made one is kept aside, never silently lost — every time one
# appears, under the first free config.pre-ogun[.N]
cfg="$ssh_dir/config"
if [[ -f "$cfg" ]] && ! ours "$cfg"; then
    bk="$cfg.pre-ogun"; n=1
    while [[ -e "$bk" ]]; do bk="$cfg.pre-ogun.$n"; n=$((n + 1)); done
    mv "$cfg" "$bk"
    echo "  kept your ssh config aside: $bk"
fi
{   echo "$mark"
    echo "Host github.com"
    echo "    User git"
    echo "    IdentitiesOnly yes"
    echo "    IdentityAgent none"
    echo "    StrictHostKeyChecking yes"
    for i in "${ids[@]}"; do printf '    IdentityFile "%s"\n' "$i"; done
} > "$cfg.tmp.$$"
chmod 600 "$cfg.tmp.$$"; mv -f "$cfg.tmp.$$" "$cfg"
echo "  ${#ids[@]} ssh key(s) → $keys (github.com, no agent)"
