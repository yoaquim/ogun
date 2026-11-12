# og's config folder

og keeps what's yours apart from what's its own. Its own files (the scripts it sends into a
sandbox, its default network baseline) ship inside og. Yours live in one folder,
`~/.config/ogun/` (or `$XDG_CONFIG_HOME/ogun/`), beside the settings file:

| File | What it's for | Missing means |
|---|---|---|
| `config.toml` | plain settings: the 1Password vault, folders, your setup, shared or in a profile ([profiles](appendix/flags-and-env.md#profiles)); and, if you want your own, the network baseline ([baseline](appendix/flags-and-env.md#the-network-baseline)) | every default, og's own baseline |
| `profile` | one line: which profile of `config.toml` this Mac uses (`OG_PROFILE` wins over it) | no profile: only the shared settings, and nothing per-profile applies |
| `registry.json` | the repos og knows: their owners, read-only mounts, secret grants, MCP servers and templates | no registry: no mounts, grants or MCP servers; `og project` says so |
| `marketplaces.json` | the plugin marketplaces this Mac's sandboxes mount | no plugins |
| `templates/` | the recipes `og template` builds sandbox images from, `<name>.sh` each | no templates: a create uses sbx's own image; `og template` says so |
| `appa.lock` | the OpenAPPA release sandboxes install, by version and SHA-256 | no OpenAPPA: `--appa` says so |

Each file may be a link, and is read through it; an edit og makes (`og project add`) goes to
the file the link points at, never replacing the link. A file that's there but can't be read
as what it should be (JSON or TOML that doesn't parse, a file that isn't text or that og can't open) stops og with one line naming it: it's never skipped, since skipping a broken
registry would read as "nothing granted".

A `[baseline]` table in `config.toml` replaces og's own baseline whole. There's no merge:
what's allowed is always the content of one table. So it sets all three lists, `domains`,
`http` and `default_rules_off` (an empty one is `[]`); one left out stops og, naming it.

## Treat these as code

These files decide what sandboxes get: a change to the registry, a recipe or a pin deserves
the care a code change does. Each may be a link to a file kept elsewhere. `profile` stays a
plain file, each Mac's own choice.

## Handing og to a team

og names nothing of any one Mac's setup: everything that's a Mac's own is in this folder, so a
team gets og by cloning its repo and writing a folder of their own. With none of it, og still
runs: no registry, templates, plugins or OpenAPPA, og's own baseline, nothing provisioned,
each said once where it matters.

What they write, each optional:

| File | What to put in it |
|---|---|
| `config.toml` | the settings below, shared or per profile |
| `profile` | one line, the profile this Mac uses (or `OG_PROFILE`) |
| `registry.json` | their repos: owners, mounts, grants, MCP servers ([registry](sandboxes.md)) |
| `marketplaces.json` | the plugin marketplaces their sandboxes mount |
| `templates/` | their recipes, `<name>.sh` each ([templates](templates.md)) |
| `appa.lock` | the OpenAPPA release to install, if they use it |

Tab completion for `og` is `completion.bash`, sourced from their shell profile;
`setup.sh` ends by saying so.

The settings (each also an environment variable; defaults and details in
[flags and environment](appendix/flags-and-env.md)):

| Setting | For |
|---|---|
| `vault` | the 1Password vault their tokens and secrets live in |
| `projects` | their project folders, per-owner or one owner each |
| `token_name`, `token_suffix` | how their token items are named, and which a Mac may use |
| `github_owners` | the GitHub account behind a project folder whose name differs, for `og token`'s form |
| `protected_keys` | the keys that must never go into a sandbox: a commit-signing key, git's `allowed_signers`, say |
| `provision` | the command that sets up each sandbox (their own setup script) |
| `skills_dir` | the skills folder mirrored into sbx's skills store |
| `host_ro_mounts` | host folders every sandbox reads (none by default; a folder of shared settings, say) |
| `apt_tools` | apt tools beyond og's own, in every sandbox and template |
| `exchange`, `take_dest` | the file exchange, and where `og give` and `og take` look |

## Make sandboxes your own

og sets up only what it needs itself. Everything else a sandbox should have, you add with
these, and og runs or mounts what they name without knowing what's in it:

| To | Use |
|---|---|
| give every sandbox host folders, read-only | `host_ro_mounts`: mounted at their own paths (a Mac path inside is the same path), live |
| give one repo's sandbox other repos, read-only | that repo's `repos.read` in `registry.json` ([sandboxes](sandboxes.md)) |
| run your own setup in every sandbox | `provision`: a command run inside at create and on every attach, so it must be safe to run again |
| install extra apt packages | `apt_tools` |
| bake heavier tools into an image | a recipe in `templates/` ([templates](templates.md)) |

The setup command runs inside the sandbox, so the script it names has to be there: keep it
in a folder `host_ro_mounts` mounts. A leading `~/` in either is your Mac's home:

```toml
host_ro_mounts = "~/sandbox-setup"
provision = "~/sandbox-setup/provision.sh"
```

### Example: AWS

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

### Example: the Mac's fonts

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
