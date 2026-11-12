# Appendix: template recipes

Reference for [Templates](../templates.md). `ogun template <name>` builds
`templates/<name>.sh` (in og's config folder) into the image `ogun-<name>:latest`. The recipes below
are examples; og's tests build them (`tests/fixtures/templates/`).

## How a recipe runs

- inside the build sandbox `golden-<name>`, as the agent user, after the common base;
- from a login shell, as `bash -euo pipefail <recipe>`, so any failing command fails the build
  and nothing is saved;
- passed in as a file, not on stdin, so a command that reads stdin can't swallow the rest of
  the recipe;
- with nothing else in the sandbox: no host folder copied (those are live mounts at runtime), no
  secrets, no logins, no repos.

Recipe names match `[a-z0-9][a-z0-9-]{0,40}`.

## Header lines

The builder reads these anywhere in the recipe's leading comment block. Values are separated
by commas or spaces.

| Header | Means | Shape check |
|---|---|---|
| `# egress: a.example.com,b.example.com` | domains the build downloads from, allowed with `sbx policy allow network --sandbox golden-<name>` (gone with the build sandbox) and printed | each a domain, optionally `*.`-prefixed |
| `# runtime-egress: a.example.com,*.example.com` | domains a sandbox made from the template needs, allowed with `--sandbox <name>` at each create, from the recipe as it is then. Kept in the create's record; `sbx rm` drops them. A value off its shape is warned at create and nothing is allowed | as `egress` |
| `# scrub: ~/.config/tool ~/.cache/tool` | extra paths deleted before the save | each `~/<path>`, no `..` |
| `# appa: on` | the image carries the pinned [OpenAPPA](../appa.md), and every create from it has OpenAPPA | `on` only; any other value stops the build and the create |

A header value that fails its shape check builds nothing.

## Build steps

| Step | Detail |
|---|---|
| guard | the ssh-agent check, as for a create |
| lock | one build per recipe at a time, across processes (two terminals): a kernel lock on `~/.local/state/sbx-golden-<name>.lock`, dropped when the build ends. A second build of the same recipe is refused, not queued |
| sandbox | `sbx env create --force` for `golden-<name>`, from an empty workspace the Mac makes at `~/.local/state/sbx-golden-<name>` (deleted afterwards). A leftover sandbox of that name, from a build that didn't finish, is removed first, without a prompt. Only one whose workspace is that build path counts: a `golden-<name>` made by hand stops the build instead, and `ogun` refuses to create a sandbox named `golden-<recipe>` for any recipe (in any case), so only one made with plain `sbx` can collide |
| network | the baseline allowlist, then the recipe's `egress` for `golden-<name>` only |
| base | apt tools (`jq socat`, plus `apt_tools`), `claude update` |
| recipe | `templates/<name>.sh` in og's config folder |
| OpenAPPA | with `# appa: on` only: the pinned release, as a create installs it ([OpenAPPA](../appa.md#what-an-install-does)) |
| scrub | the base list plus the recipe's `scrub` paths. **The build fails if one survives** |
| save | `sbx stop golden-<name>`, then `sbx template save golden-<name> ogun-<name>`: sbx saves only a stopped sandbox |
| cleanup | the build sandbox is removed, whether the build worked or not. The calls that can ask for confirmation get no terminal input, and `rm` passes `--force` (sbx refuses its own y/N without a terminal), so none stops to ask |

Base scrub list (`SCRUB` in `src/ogun/sandbox/template.py`): `~/.aws/sso`, `~/.claude/.credentials.json`,
`~/.bash_history`, `~/.git-credentials`, `~/.config/gh`.

## `work.sh`

It installs a Rust toolchain with rustup's own script from `sh.rustup.rs`, with `-y` (no prompt)
and `--profile minimal`. The script downloads `rustup-init` from `static.rust-lang.org` over
HTTPS only; it checks no signature of its own, so trust rests on that host. `rustup-init` then
installs the stable toolchain, checking every component against the SHA-256 the channel's
manifest lists. `cargo`, `rustc` and `rustup` are linked into `/usr/local/bin` so non-login
shells and hooks find them, and the build ends with `cargo --version`.

- egress: `sh.rustup.rs` (the script), `static.rust-lang.org` (`rustup-init`, the toolchain)
- runtime-egress: `index.crates.io` (the registry's index), `static.crates.io` (crate
  downloads), `*.rust-lang.org` (`rustup update`)
- scrub: `~/.cargo/credentials.toml` (a registry token, should the build write one)
- auth: `cargo login` per user, inside each sandbox, or a [secret grant](../secrets.md#secret-grants)
  for the crate registry's token

## `orders.sh`

For the `orders` repo's sandboxes (its registry entry names it), a service whose tests run
against a staging API and a local PostgreSQL. The build installs the PostgreSQL client
(`postgresql-client`, from apt) and ends by checking `psql --version`. The staging API key is
no part of the image: it's a [secret grant](../secrets.md#secret-grants) on the `orders` entry,
so each sandbox holds a placeholder the proxy swaps on that host alone.

- egress: none beyond the baseline (apt's mirrors are in it)
- runtime-egress: `api.orders.example`
- scrub: `~/.psql_history`, `~/.pgpass` (a password a build step might leave)
- appa: `on`. The repo handles customer records, so every orders sandbox is [protected by
  OpenAPPA](../appa.md)
