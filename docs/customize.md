# Make sandboxes yours

A new sandbox has Claude Code, og's own tools (`jq socat`) and your repo. Everything else you
add yourself, and og runs or mounts what you name without knowing what's in it:

| You want | Use | Section |
|---|---|---|
| your `CLAUDE.md`, settings and hooks | a setup folder and a provision command | [Your Claude setup](#your-claude-setup) |
| your skills | `skills_dir` | [Skills](#skills) |
| your plugins | `marketplaces.json` | [Plugins](#plugins) |
| MCP servers | the registry's `mcp` | [MCP servers](#mcp-servers) |
| a few apt packages | `apt_tools` | [Packages and tools](#packages-and-tools) |
| heavier tools, ready at create | a template | [Packages and tools](#packages-and-tools) |
| folders of yours, to read | `host_ro_mounts` | [Files and repos](#files-and-repos) |
| other repos, beside this one | the registry's related repos | [Files and repos](#files-and-repos) |

Settings go in `~/.config/ogun/config.toml`, shared or per profile; the registry and the
rest sit beside it ([og's config folder](config.md)). A sandbox gets most changes at its next
attach; mounts and templates at its next create.

## Your Claude setup

A sandbox's Claude starts with nothing of yours. Keep what it should have in one folder on the
Mac, mount it into every sandbox, and have a script there copy it into place:

```text
~/sandbox-setup/
  provision.sh     # runs inside every sandbox
  CLAUDE.md        # your instructions for the agent
  settings.json    # Claude Code settings: permissions, hooks, plugins
```

```toml
# ~/.config/ogun/config.toml
host_ro_mounts = "~/sandbox-setup"
provision = "~/sandbox-setup/provision.sh"
```

```bash
#!/usr/bin/env bash
# ~/sandbox-setup/provision.sh: runs inside the sandbox, at create and on every attach
set -euo pipefail
here="$(dirname "${BASH_SOURCE[0]}")"
mkdir -p ~/.claude
cp "$here/CLAUDE.md" ~/.claude/CLAUDE.md
cp "$here/settings.json" ~/.claude/settings.json
```

- **Where it runs.** `provision` runs inside the sandbox, in a login shell (`bash -lc`), after
  og's tools and Claude Code are in place, at create, on every attach and with `--sync`. It
  must be safe to run again.
- **Its script must be in the sandbox.** A mounted folder keeps its Mac path inside, so the
  same path works on both sides, and a leading `~/` in either setting is your Mac's home.
  Mounts are read-only and live: an edit on the Mac is seen inside at once, and copied into
  place on the next attach.
- **A failure stops a create.** A provision command that exits non-zero stops the create
  (or `--sync`), saying so. On a plain attach it warns and the session still starts, maybe
  without what it sets up; run `og <name> --sync` to set it up again.
- **Tell the agent og's rules.** og says nothing to the agent itself; your `CLAUDE.md` is
  where it learns what to do when a request is blocked or a workflow push refused
  ([What a provision command should tell the agent](setup.md#what-a-provision-command-should-tell-the-agent)).

Keep secrets out of this folder: every sandbox can read it. A secret goes to one sandbox with
`og pass` ([Secrets](secrets.md)).

## Skills

```toml
skills_dir = "~/sandbox-setup/skills"
```

og mirrors that folder into sbx's shared skills store, which every sandbox mounts, at each
create, with `--sync`, and when you run `og skills`. og leaves the store's files read-only, so
one sandbox can't plant a skill for the rest.

## Plugins

A plugin marketplace is a clone on your Mac, mounted read-only into the sandboxes you name:

```json
{"marketplaces": {"acme-kit": {"path": "~/Projects/acme/plugins", "profiles": ["work"]}}}
```

That's `marketplaces.json` in og's config folder: every sandbox on a Mac whose profile is
`work` mounts it, at its own path. A repo's registry entry can ask for one too. og only
mounts it; turning its plugins on is your `settings.json`'s job, which the setup above copies
in. The fields, and the settings Claude Code needs:
[Appendix: plugin marketplaces](appendix/mcp-gateway.md#plugin-marketplaces).

## MCP servers

Register a server once on the Mac, then name who gets it in the registry:

```bash
sbx mcp add tracker --url https://mcp.tracker.example.com
sbx mcp add db-cub --url https://mcp.db.example.com/cub
og mcp auth tracker      # a server that logs in with OAuth opens the browser
```

```json
{"mcp": ["tracker"],
 "repos": {"cub": {"owner": "acme", "mcp": ["db-cub"]}}}
```

In `registry.json`, the top-level `mcp` reaches every sandbox (an entry
`{"name": …, "profiles": ["work"]}`, only those Macs'), and a repo entry's `mcp` that repo's
sandboxes alone. og loads them at create and on every attach; the
login stays on the Mac. The details: [Appendix: MCP gateway](appendix/mcp-gateway.md).

## Packages and tools

A few apt packages, in every sandbox and template:

```toml
apt_tools = "ripgrep fd-find postgresql-client"
```

og installs them with its own at create and with `--sync`. A failed install is said, and the
sandbox goes on without them.

Anything heavier (a language toolchain, a CLI from its own installer) belongs in a template:
a recipe, `templates/<name>.sh` in og's config folder, that og builds into an image new
sandboxes start from, so a create doesn't install it each time:

```bash
#!/usr/bin/env bash
# templates/work.sh
# egress: sh.rustup.rs,static.rust-lang.org
# runtime-egress: index.crates.io,static.crates.io

curl -fsSL --proto '=https' --tlsv1.2 https://sh.rustup.rs -o /tmp/rustup-init.sh
sh /tmp/rustup-init.sh -y --profile minimal --no-modify-path
sudo ln -sf ~/.cargo/bin/cargo ~/.cargo/bin/rustc ~/.cargo/bin/rustup /usr/local/bin/
cargo --version
```

```bash
og template work
```

A sandbox uses the template its repo's registry entry names, else the one named after this
Mac's profile. The headers name the hosts the build, and later each sandbox, may reach. No
logins or secrets in a recipe: every sandbox made from it would share them
([Templates](templates.md)).

Something your setup script downloads needs its host allowed: approve it for one sandbox
when it's asked for, or list it in a template's `runtime-egress` ([Network](network.md)).

## Files and repos

Folders of yours that every sandbox should read (reference docs, shared configs):

```toml
host_ro_mounts = "~/sandbox-setup:~/Documents/reference"
```

Colon-separated, `~/` your home, globs allowed, each skipped when it isn't there. They're
mounted read-only at their own paths, at create. Name only what a sandbox may safely read:
never credentials.

Other repos one repo's sandbox should see, read-only:

```bash
cd ~/Projects/acme/cub
og project add widgets      # cub's sandboxes mount widgets read-only
```

([Related repos](sandboxes.md#related-repos-ogun-project)). Files to hand over once, rather
than mount, go through the [file exchange](exchange.md): `og give`.

## Examples

### AWS

og doesn't set up AWS. The proxy can't inject AWS credentials (requests are signed rather
than carrying a token), so access lives inside each sandbox as a short-lived SSO session:

- **The CLI:** install it from your setup script, or in a template's recipe so it's baked in.
- **Profiles:** mount the folder holding your AWS config and point `AWS_CONFIG_FILE` at it
  from your setup script, or have the script write one. A config holds identifiers only;
  no keys or sessions leave the Mac.
- **Login:** run `aws sso login --profile <p> --use-device-code` inside the sandbox and
  approve the code in the Mac's browser. The sandbox asks you to approve the login's hosts
  the first time, as it does any host outside the baseline
  ([network](network.md#what-the-baseline-leaves-out)).

### The Mac's fonts

For a sandbox to render with the Mac's fonts (a browser, a PDF tool), mount the font
folders and point fontconfig at them from your setup script:

```toml
host_ro_mounts = "~/sandbox-setup:~/Library/Fonts:/Library/Fonts"
```

```bash
# in provision.sh: the mounts keep their Mac paths
mkdir -p ~/.config/fontconfig
{ echo '<?xml version="1.0"?>'; echo '<fontconfig>'
  for d in /Users/*/Library/Fonts /Library/Fonts; do [ -d "$d" ] && echo "  <dir>$d</dir>"; done
  echo '</fontconfig>'; } > ~/.config/fontconfig/fonts.conf
```
