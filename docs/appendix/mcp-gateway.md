# Appendix: MCP gateway and plugins

Reference for og's MCP gateway (`og mcp`).

## Registering servers (once, on the Mac)

Register only the servers this Mac uses (`ogun mcp` lists them). A server can serve every
sandbox (the registry's top-level `mcp`) or one repo's (its entry's `mcp`). For a service
with a database per project, say, one server per repo:

```bash
sbx mcp add db-cub         --url https://mcp.db.example.com/cub
sbx mcp add db-widgets     --url https://mcp.db.example.com/widgets
ogun mcp auth db-cub              # a server that logs in with OAuth opens the browser

sbx mcp ls
ogun mcp                               # each server's login, and the repos that get it
```

- A server's name is yours to pick.
- Each name must match the repo's `mcp` list in og's registry (`registry.json`).
- Registrations are host-global and survive `sbx env rm`.

## Per project

og's registry (`registry.json` in its config folder) declares which servers a sandbox gets:

| List | Applies to |
|---|---|
| top-level `mcp` | every sandbox. An entry `{"name": …, "profiles": ["work"]}` reaches every sandbox on those Macs only (by og profile); with no profile, none |
| a repo entry's `mcp` | that repo's sandboxes, and **only** when the entry declares an `owner` and the sandbox's path names that owner. A same-named repo under another owner, or any directory that isn't the repo the entry describes, never gets that repo's servers |

`ogun` attaches them right after the create with `sbx mcp load <server> --sandbox <name>`,
which reuses the registration's URL and OAuth, and loads them again on every attach
([Logging in again](#logging-in-again) says why). `.sbxenv.yaml` **can't** name gateway servers:
each `mcp.servers` entry needs a `url` or `command`, and sbx rejects name-only entries.

A server added to a repo's list reaches its existing sandboxes on their next attach, or now
with `ogun mcp load <name>`.
For a one-off outside the registry, pass `--static-mcp <server>` when creating by
hand. With none of these, the sandbox would be in dynamic mode (`mcp-find` / `mcp-add`):
deny those two tools in the agent's settings inside the sandbox, so it can't attach a server
it wasn't given.

### Adding a server to a repo

```bash
sbx mcp add db-<repo> --url https://mcp.db.example.com/<repo>
ogun mcp auth db-<repo>        # a server that logs in with OAuth opens the browser
```

Then add `"mcp": ["db-<repo>"]`, and its `owner`, to the repo's entry in
og's registry. Its sandbox gets the server on the next `ogun <name>`.

## Logging in again

A sandbox's gateway keeps the credentials each server was loaded with. Logging in again on
the Mac doesn't reach a sandbox that's already running: its calls to that server keep failing until
the server is loaded into it again. `sbx mcp load` does that live, without restarting the
session.

| Command | Does |
|---|---|
| `ogun mcp` | every server the registry names, plus any other sbx has: its login status (`authorized`, `needs-refresh`, …; `registered` for one without OAuth, `not-registered` for a name sbx doesn't know) and the repos that get it |
| `ogun mcp auth <server>` · `--all` | `sbx mcp auth` for the registry's OAuth servers only (a header-secret or local server has no login), then reloads each into every running sandbox that uses it |
| `ogun mcp load <name>` | what an attach does, without attaching: log in again what needs it, then reload that sandbox's servers. A running sandbox only, since `sbx mcp load` attaches to one; `ogun <name>` starts a stopped one and reloads |

Every `ogun <name>` and `ogun attach <name>` checks the sandbox's servers first. A login that
isn't `authorized` opens the browser at a terminal, or prints the `ogun mcp auth` line
anywhere else. Then each server is loaded again. Before sbx v0.47 a login had no refresh
token, so it expired into `needs-refresh` on its own; from v0.47, one `ogun mcp auth --all`
gets each server a refresh token.

## Tool names inside a sandbox

The gateway is a single MCP server that Claude Code names `mcp-gateway`. Everything it
exposes is `mcp__mcp-gateway__<tool>`: its own `mcp-exec`, `code-mode`, `mcp-find`, `mcp-add`,
`mcp-config-set`, and the attached servers' tools under their native names. There are no
`mcp__<server>__*` tools, so a skill's `allowed-tools` lists `mcp__mcp-gateway__*`,
never a per-server pattern.

A registry may serve several Macs, so `ogun mcp` lists only this Mac's servers: a top-level entry scoped to other profiles, or a repo not checked out here, belongs to another Mac. A server every sandbox uses goes at the top level, as `{"name": "search"}`; `"profiles": ["home"]` keeps one to the Macs whose og profile is named there.

Two servers of one service in one sandbox would expose colliding tool names, so give a sandbox
one server of each service.

A server loaded **after** a Claude session started is reachable only through `mcp-exec`
until the session restarts. `ogun` loads everything before the session it attaches starts.

## Local stdio servers: the trap

`sbx mcp add x --command npx --args some-mcp` runs **on the Mac**, as you, outside every
sandbox. That's the host-local server sandboxes exist to avoid. Only register a local server
you'd install as a host application after reading it.

## Plugin marketplaces

`marketplaces.json` in og's config folder, one entry per marketplace inside a top-level
`marketplaces` object, keyed by its name:

```json
{"marketplaces": {"acme-kit": {"path": "~/Projects/acme/plugins", "profiles": ["work"]}}}
```


| Field | Meaning |
|---|---|
| `path` | the clone on the Mac, `~/`-relative |
| `profiles` | the og profiles whose sandboxes get it |

og only mounts each clone read-only at its own path. A repo entry can also ask for one under
any profile with `"marketplaces": ["acme-kit"]`, under the same owner gate as `mcp`. Turning its
plugins on is up to what you set up inside the sandbox (a provision command, or by hand):
Claude Code needs the mounted clone in its settings, for example:

```json
"extraKnownMarketplaces": { "acme-kit": { "source": { "source": "directory", "path": "/Users/<you>/Projects/acme/plugins" } } },
"enabledPlugins": { "widgets@acme-kit": true }
```

- The key must equal the `name` in the clone's `.claude-plugin/marketplace.json`, because
  Claude Code registers a marketplace under that name.
- A local-directory plugin loads in place, so nothing lands in `~/.claude/plugins/cache`.
- If `/plugin` shows it as not installed, run `claude plugin install widgets@acme-kit`
  inside once.
- The template build never touches the repo. The files come from the Mac's disk, not GitHub.
