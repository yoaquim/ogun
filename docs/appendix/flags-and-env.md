# Appendix: environment

Reference for [Ogun](../README.md).

## Settings

og reads its settings from `~/.config/ogun/config.toml` (`$XDG_CONFIG_HOME/ogun/config.toml`
when that's set), one `name = value` a line, text or a number. The files beside it, your
registry, templates and the rest, are on [og's config folder](../config.md):

```toml
vault = "Shared"
exchange = "~/sandboxes.noindex"
apt_tools = "git-crypt shellcheck"
```

Each setting can be overridden for one run by its name in capitals after `OG_`
(`OG_VAULT`, `OG_APT_TOOLS`); a setting neither sets is its default below. A file og can't
read as its settings (not TOML, a name og doesn't have, a list or a table where text goes)
stops og with what's wrong, rather than reading as the defaults. Never a token in the file:
tokens live in 1Password ([Secrets](../secrets.md)).

| Setting | Default | What it is |
|---|---|---|
| `vault` | `Sandbox` | the 1Password vault for every sandbox-bound secret: `og token` mints into it, og reads from it |
| `projects` | `~/Projects` | the folders projects live in, colon-separated like `PATH`, each naming a repo's token owner: a folder alone is per-owner (`<folder>/<owner>/<repo>`, the owner from the folder under it), `folder=owner` is fixed-owner (`<folder>/<repo>`, every repo that owner's, nothing deeper). Compared by physical path, so a link to a folder elsewhere names nobody. Folders can't nest: one inside another, or the same folder twice (links resolved), stops og, so exactly one rule names each folder's owner. A command that makes or finds `<owner>/<repo>` (`og project add`, related checkouts, completion) uses the first per-owner folder, else `~/Projects`. An empty folder, a path that isn't full (`/…`, `~/…`) or an owner that isn't a plain name stops og. Example: `~/Projects:~/Team=acme` |
| `exchange` | `~/sandboxes.noindex` | the file exchange root |
| `take_dest` | `~/Downloads` | where `ogun take` delivers |
| `host_ro_mounts` | none | colon-separated host dirs mounted read-only into every sandbox, at their own paths; entries may be globs, a leading `~/` is your home, and ones that match nothing are skipped. A host folder og mounts is one only when this names it. Only add dirs that are safe for a hostile sandbox to read |
| `apt_tools` | none | apt packages every sandbox and template gets beyond og's own `jq socat`, space-separated |
| `provision` | none: nothing run | a command run inside every sandbox at create and on every attach (so it must be safe to run again), with `bash -lc`; a leading `~/` is your home, where sbx mounts host folders. A failure stops a create, and only warns on an attach. Unset, nothing runs, said once. |
| `skills_dir` | none: no mirror | the folder of skills mirrored into sbx's skills store (`~/` is your home); unset, a create mirrors nothing and says so once, and `og skills` fails saying so. |
| `token_name` | the profile's name | how this Mac's own token items end: `github-pat-<owner>-<it>`, the item `og token` mints into and og reads first. With neither it nor a profile, a create refuses before anything is made, and the token menu says why it is empty. og reads every profile's ending the way that profile would (its own, else the shared one, else its name), to tell an item's owner; two where one ends the other after a dash (`home-work`, `work`) stop og, since `github-pat-foo-home-work` could be either owner's |
| `token_suffix` | none: any item | the ending every token item this Mac uses must have (`-work`, say, for a Mac kept to its own tokens). Unset, og also falls back to the owner's items with the other profiles' endings |
| `github_owners` | none: each folder's own name | `<folder>=<github owner>` pairs, space-separated, for `og token`'s form: the GitHub account a folder's token is for when it isn't the folder's name. With no pair, `personal`'s form names no account, so GitHub takes your own. A pair that isn't one stops og, naming it. Example: `personal=jdoe acme=acme-corp` |
| `protected_keys` | `~/.ssh/allowed_signers` | the files whose keys never go into a sandbox's ssh keys folder, colon-separated, each a full path (`/…` or `~/…`): a key, private or public, or a signers file in git's `allowed_signers` form, every key it trusts. A key there refuses the folder, naming the file. A file that isn't there protects nothing; a path that isn't full stops og. Example: `~/.ssh/signing:~/.ssh/allowed_signers` |

### Profiles

One file can hold several profiles, each a `[profiles.<name>]` section of the same settings.
A profile's own setting wins over the shared one above the sections, and an `OG_` variable
wins over both. og never guesses which profile to use. It's told: `OG_PROFILE`, else
the one line in `~/.config/ogun/profile`. Neither means no profile, and only the shared
settings apply.

```toml
[profiles.home]
projects = "~/Projects:~/Team=acme"

[profiles.work]
token_suffix = "-work"
```

The profile's name is also the label the registry's `profiles` lists match (top-level
secret grants, MCP servers, marketplaces), and the default template (`ogun-<profile>`).
With no profile, none of those applies anywhere, and og says so once. A profile named
(by `OG_PROFILE` or the file) that the file has no section for stops og, so a typo never
reads as no profile.

### The network baseline

A `[baseline]` table replaces og's own network baseline whole: the hosts every sandbox may
reach, the read-only HTTP rules, and sbx's default rules og takes out. All three keys are
lists, and one left out stops og (an empty one is `[]`). `og internal baseline` prints og's
own as a table to start from ([Network](../network.md)).

```toml
[baseline]
domains = ["deb.debian.org", "security.debian.org", "api.github.com"]
http = ["pypi.org=GET,HEAD", "github.com=GET,HEAD"]
default_rules_off = ["default-ai-services", "default-package-managers"]
```

## Environment variables

| Variable | What it does |
|---|---|
| `OG_<SETTING>` | overrides that setting from `config.toml` (`OG_VAULT`, `OG_PROJECTS`…) |
| `OG_PROFILE` | which profile of the settings file to use, over `~/.config/ogun/profile` ([profiles](#profiles)) |
| `OG_VERBOSE` | `1` or `2`: what `-v` and `-vv` set |
| `OG_BIN` | where `setup.sh` links `og` and `ogun` (default `~/.local/bin`; empty, no links) |
| `OG_TOOLS` | where `setup.sh` keeps its pinned `uv` and Python (default `~/.local/share/ogun`) |
| `XDG_CONFIG_HOME`, `XDG_STATE_HOME` | move og's config folder and its own state (`~/.local/state/ogun`: records, approvals, its log) |
| `NO_COLOR`, `TERM=dumb` | plain output |
