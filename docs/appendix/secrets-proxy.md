# Appendix: the secrets proxy

Reference for [Secrets](../secrets.md). Each fact below was checked against sbx on the date
given.

## Verified proxy behavior

| Date | Finding | Consequence |
|---|---|---|
| 2026-09-02 | sbx injects a **global** secret ahead of a sandbox-scoped one. so a sandbox made for one owner reaches another owner's repos with that global token | no global `github` secret, ever. `ogun` warns when `sbx secret ls` shows one |
| 2026-09-15 | the proxy stamps the sandbox's `github` secret onto every github.com request, overriding any credential the request carried, custom-secret placeholders included | one GitHub identity per sandbox. Cross-org work goes through the host |
| 2026-09-15 | `sbx secret set-custom` works for non-GitHub hosts: the sandbox holds a placeholder, and the proxy swaps in the value on requests to the declared hosts. Tested against a non-GitHub API host, including a CLI that insists on a local env var | `ogun pass <name> <ENV_VAR> <host>` |
| 2026-09-16 | with **no** `github` secret at all, a custom secret is still not substituted on github.com or api.github.com, while the same ref scoped to another host is | GitHub hosts are special-cased in the proxy, so there is no loophole there. `ogun pass` refuses them anyway |
| 2026-09-15 | the running proxy caches credentials; a removed secret can linger until the sandboxes daemon restarts | rotate by overwriting (`ogun pass` again), never delete-then-test |
| 2026-09-23 | sbx forwards the Mac's ssh-agent by default, so a sandbox can list the keys in the Mac's agent and authenticate to GitHub over SSH with them | the agent guard, below |

## `ogun pass` internals

```bash
ogun pass <name> <ENV_VAR> <host>...|--expose [--item <name>|--paste] [--vault <v>] [--field <f>]
```

- With hosts, it runs `sbx secret set-custom` with an `op://` reference, so the value never
  touches the shell or the clipboard. `set-custom --env` only reaches sandboxes created
  *later*, so `ogun pass` also exports the placeholder into the running sandbox's persistent
  env. When it can't, nothing in that sandbox could use the secret, so it undoes the
  registration and fails, printing the `ogun pass` to rerun (or, if the undo fails too, the
  `sbx secret rm` to run). Placeholders aren't secrets; printing them is fine.
- `--expose` pipes the value (from 1Password, or pasted) into the sandbox's stdin. It never
  goes through argv, a host file or the transcript.
- `--paste` reads a hidden prompt on a terminal, or all of stdin when piped (one trailing
  newline dropped). To the proxy it goes as `set-custom --value`: the one deliberate
  exception to "never in argv". The alternative, `--command`, would need the value in a file
  for as long as the secret lives.
- Refused exposed: items whose name contains `github`, pasted values that start like a GitHub token,
  and env names that gh and git read as credentials (`GH_TOKEN`, `GITHUB_TOKEN`, …). Any would
  be a second GitHub identity.
- The old `--host` and `--raw` refuse and name the new shape.
- `ogun tidy` lists custom secrets left behind by removed sandboxes, with the `sbx secret rm`
  command to run. It never removes them for you.

## The ssh-agent guard

A Mac's agent often holds its signing key (`AddKeysToAgent yes`). A sandbox that reached the agent
could make signatures that key's trusters accept, and push over SSH past its one-identity token.

| Check | When | Rule |
|---|---|---|
| `sbx settings get ssh.agentForwardingEnabled` | every create, and every template build | anything but a plain `false` counts as on (including a failed `get`, which is what sbx < 0.42.1 gives). `ogun` sets it to `false` itself and refuses |
| in-sandbox probe | every new sandbox, and every `--sync` | asks the agent socket (`SSH_AUTH_SOCK`, sbx's `/run/ssh-agent.sock`) **and** the sbx gateway's TCP port, which also speaks the agent protocol. Only an explicit "none" passes. A **new** sandbox that still reaches an agent is removed, token and box with it. On `--sync` the attach stops but the sandbox stays: remove it with `ogun rm <name> --force` |

The saved setting reads `false` as soon as `ogun` writes it, but the daemon only applies it on
restart, and a restart interrupts running sandboxes. So the restart is yours, once per Mac,
and again after `sbx setup`, which can turn forwarding back on:

```bash
sbx settings set ssh.agentForwardingEnabled false && sbx daemon restart   # sbx ≥ 0.42.1
```

`ogun policy` re-applies the setting along with the baseline egress allowlist.

## The `~/.ssh/sandbox` folder

| Rule | Detail |
|---|---|
| refused | a key `SBX_PROTECTED_KEYS` keeps out: the key in a file it names, or any key a signers file it names trusts (matched by fingerprint, private or public); unset, every key git's `~/.ssh/allowed_signers` trusts. Any symlink inside it, too. A folder that is itself a symlink isn't mounted at all |
| checked | at create and at `--sync` only |
| live | the mount is live: a file dropped in later is readable in every running sandbox at once, before any check. Check what you add |
| inside | og's `sandbox-scripts/sandbox-ssh.sh`, sent in as text, copies each private key to `~/.ssh/sandbox-keys/` (mode 600), pins GitHub's host keys in `~/.ssh/known_hosts` (never `ssh-keyscan`), and writes a `github.com` block that uses those keys and no agent |
| signing in a sandbox | name the key `signing` (made without a passphrase) and register its public key on GitHub as a **Signing** key, never in a signers file `SBX_PROTECTED_KEYS` names. Setup sets `gpg.format ssh`, `user.signingkey ~/.ssh/sandbox-keys/signing.pub` (derived from the private key) and `commit.gpgsign true` in `~/.config/git/config`, because sbx writes `~/.gitconfig`. The key is left out of the `github.com` block, since GitHub refuses a signing key for login. A key with a passphrase is refused with a warning, and signing stays off, because a sandbox has no agent to unlock it. Remove the key and the next `--sync` turns signing off, as long as the settings still name it |
