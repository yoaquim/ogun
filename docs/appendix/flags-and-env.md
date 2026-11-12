# Appendix: environment

Reference for [Ogun](../README.md).

## Settings

og reads its settings from `~/.config/ogun/config.toml` (`$XDG_CONFIG_HOME/ogun/config.toml`
when that's set), one `NAME = value` a line, text or a number. The files beside it, your
registry, templates and the rest, are on [og's config folder](../config.md):

```toml
SBX_VAULT = "Shared"
SBX_EXCHANGE = "~/sandboxes.noindex"
SBX_RM_PROBE_TIMEOUT = 120
```

An environment variable of the same name wins over the file; a setting neither sets is its
default below. A file og can't read as its settings (not TOML, a name og doesn't have, a
list or a table) stops og with what's wrong, rather than reading as the defaults. Never a
token in the file: tokens live in 1Password ([Secrets](../secrets.md)).

### Profiles

One file can hold several profiles, each a `[profiles.<name>]` section of the same settings.
A profile's own setting wins over the shared one above the sections, and an environment
variable wins over both. og never guesses which profile to use. It's told: `OG_PROFILE`, else
the one line in `~/.config/ogun/profile`. Neither means no profile, and only the shared
settings apply.

```toml
[profiles.home]
SBX_PROJECTS = "~/Projects:~/Team=acme"

[profiles.work]
SBX_TOKEN_SUFFIX = "-work"
```

The profile's name is also the label the registry's `profiles` lists match (top-level
secret grants, MCP servers, marketplaces), and the default template (`ogun-<profile>`).
With no profile, none of those applies anywhere, and og says so once. A profile named
(by `OG_PROFILE` or the file) that the file has no section for stops og, so a typo never
reads as no profile.

## Environment variables

| Variable | Default | Used by |
|---|---|---|
| `SBX_VAULT` | `Sandbox` | the 1Password vault for every sandbox-bound secret: `og token` mints into it, og reads from it |
| `SBX_PROJECTS` | `~/Projects` | the folders projects live in, colon-separated like `PATH`, each naming a repo's token owner: a folder alone is per-owner (`<folder>/<owner>/<repo>`, the owner from the folder under it), `folder=owner` is fixed-owner (`<folder>/<repo>`, every repo that owner's, nothing deeper). Compared by physical path, so a link to a folder elsewhere names nobody. Folders can't nest: one inside another, or the same folder twice (links resolved), stops og, so exactly one rule names each folder's owner. A command that makes or finds `<owner>/<repo>` (`og project add`, related checkouts, completion) uses the first per-owner folder, else `~/Projects`. An empty folder, a path that isn't full (`/…`, `~/…`) or an owner that isn't a plain name stops og. Example: `~/Projects:~/Team=acme` |
| `SBX_EXCHANGE` | `~/sandboxes.noindex` | the file exchange root |
| `SBX_TAKE_DEST` | `~/Downloads` | where `ogun take` delivers |
| `SBX_HOST_RO_MOUNTS` | none | colon-separated host dirs mounted read-only into every sandbox, at their own paths; entries may be globs, a leading `~/` is your home, and ones that match nothing are skipped. A host folder og mounts is one only when this names it. Only add dirs that are safe for a hostile sandbox to read |
| `SBX_APT_TOOLS` | none | apt packages every sandbox and template gets beyond og's own `jq socat`, space-separated |
| `SBX_APPA_LOCK` | `~/.config/ogun/appa.lock` | the OpenAPPA pin, if not in og's config folder |
| `SBX_SKILLS_STORE` | `~/Library/Application Support/com.docker.sandboxes/sandboxes/agent-skills` | sbx's shared skills store, which `og skills` and every create mirror `SBX_SKILLS_DIR` into, then leave read-only |
| `SBX_SKILLS_DIR` | none: no mirror | the folder of skills mirrored into sbx's skills store (`~/` is your home); unset, a create mirrors nothing and says so once, and `og skills` fails saying so. |
| `SBX_PROVISION` | none: nothing run | a command run inside every sandbox at create and on every attach (so it must be safe to run again), with `bash -lc`; a leading `~/` is your home, where sbx mounts host folders. A failure stops a create, and only warns on an attach. Unset, nothing runs, said once. |
| `SBX_SSH_DIR` | `~/.ssh` | where `sandbox/` (the keys folder) and the signer files are looked up |
| `SBX_OGUN_DIR` | `~/.config/sbx/ogun` | ogun's own state: the create records (`sandboxes/`); each sandbox's GitHub token owner and item, and each owner's token expiry (`tokens/`) |
| `SBX_CLAUDE_UPDATE_TIMEOUT` | `300` | seconds for `claude update` in a sandbox (about 230 MB) |
| `SBX_CLAUDE_UPDATE_LOG` | `/tmp/ogun-claude-update.log` | the updater's log inside the sandbox, shown when the update times out |
| `SBX_SECRETS_APPROVED` | `~/.config/sbx/ogun/approved-secrets` | the secret grants this Mac has approved ([Secrets](../secrets.md#secret-grants)) |
| `SBX_EGRESS_APPROVED` | `~/.config/sbx/ogun/approved-egress` | the registry egress this Mac has approved |
| `SBX_RM_PROBE_TIMEOUT` | `120` | seconds `ogun rm --if-clean` waits for the check inside a running sandbox; no answer keeps it |
| `SBX_RM_BOOT_TIMEOUT` | `400` | the same for a stopped sandbox, which the check boots |
| `SBX_TOKEN_NAME` | the profile's name | how this Mac's own token items end: `github-pat-<owner>-<it>`, the item `og token` mints into and og reads first. With neither it nor a profile, a create refuses before anything is made, and the token menu says why it is empty. og reads every profile's ending the way that profile would (its own, else the shared one, else its name), to tell an item's owner; two where one ends the other after a dash (`home-work`, `work`) stop og, since `github-pat-foo-home-work` could be either owner's |
| `SBX_TOKEN_SUFFIX` | none: any item | the ending every token item this Mac uses must have (`-work`, say, for a Mac kept to its own tokens). Unset, og also falls back to the owner's items with the other profiles' endings |
| `SBX_GITHUB_OWNERS` | none: each folder's own name | `<folder>=<github owner>` pairs, space-separated, for `og token`'s form: the GitHub account a folder's token is for when it isn't the folder's name. With no pair, `personal`'s form names no account, so GitHub takes your own. A pair that isn't one stops og, naming it. Example: `personal=jdoe acme=acme-corp` |
| `SBX_PROTECTED_KEYS` | `~/.ssh/allowed_signers` | the files whose keys never go into a sandbox's ssh keys folder, colon-separated, each a full path (`/…` or `~/…`): a key, private or public, or a signers file in git's `allowed_signers` form, every key it trusts. A key there refuses the folder, naming the file. A file that isn't there protects nothing; a path that isn't full stops og. Example: `~/.ssh/signing:~/.ssh/allowed_signers` |
| `OG_PROFILE` | `~/.config/ogun/profile` | which profile of the settings file to use ([profiles](#profiles)); environment only |
| `SBX_MENU_IN` | `/dev/tty` | where the token menu reads its answer (tests) |
| `SBX_AGENT_SOCK`, `SBX_AGENT_GATEWAY` | `/run/ssh-agent.sock`, `gateway.docker.internal:3129` | what the ssh-agent probe asks (tests) |
| `NO_COLOR`, `TERM=dumb` | — | plain output from `ogun` |

Every row above `OG_PROFILE` is a setting the file takes too, shared or in a profile;
`OG_PROFILE`, `SBX_MENU_IN`, the agent probe's and the plain-output variables are environment only.
