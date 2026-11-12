# Secrets

og holds no secret itself. The Mac keeps them in 1Password, and `sbx` hands them to
sandboxes, in most cases without the sandbox ever seeing the value.

## How a credential reaches a sandbox

| Kind | Channel | Does the sandbox see the value? |
|---|---|---|
| GitHub token | `ogun` sets it per sandbox (`sbx secret set -f github --sandbox <name>`); the proxy injects it | **no** |
| Other HTTP API tokens | `og pass <name> <ENV_VAR> <host> --item …` (or `--paste`); the proxy swaps a placeholder for the value | **no** |
| Secret grants (`registry.json` `secrets`) | applied per sandbox at create, through `ogun pass`, once approved on this Mac | **no** |
| Keys used locally (decryption, signing) | `og pass <name> <ENV_VAR> --expose --item …` (or `--paste`); the real value goes into its env | yes, deliberately. Scope the key; it dies with the sandbox |
| Files a task needs | `ogun give <name> <file>` (its private `in/`), `sbx cp`, or `<project>/.inbox/`, which the sandbox sees at `/run/sandbox/source/.inbox/` | yes. Delete host copies afterwards |
| AWS | an SSO session inside the sandbox (`aws sso login`), set up by you ([config](config.md#example-aws)) | yes, short-lived |
| Anything pasted into chat | — | **never do this.** It lands in the transcript on disk |

## 1Password

- `op` runs on the host through the 1Password app. Its unlock prompt authorizes a terminal session
  until the app auto-locks, so keep auto-lock short.
- No service accounts, and no `op` inside sandboxes.
- og reads from **one vault, `Sandbox`** unless `SBX_VAULT` names another, so what sandboxes
  may be given can be listed, picked from and loaded as a set. `og pass --vault` takes a
  single secret from elsewhere.

## GitHub tokens

One fine-grained token per resource owner, rotated every 60 days by default.

| Rule | Detail |
|---|---|
| **Keyed by folder** | the folder under `~/Projects` names the owner: `~/Projects/acme/x` → `acme`. `og token`, `og` and og's registry all use this one key. Other project folders can be listed in `SBX_PROJECTS`, each per-owner like `~/Projects` or fixed to one owner ([settings](appendix/flags-and-env.md)) |
| **Item name** | `github-pat-<folder>-<ending>`; the personal token's folder is `personal`. `<ending>` is the Mac it was minted for, from og's profile (`SBX_TOKEN_NAME`, else the profile's name): `home` or `work`, say. Examples: `github-pat-personal-home`, `github-pat-acme-home`, `github-pat-acme-work` |
| **Machine rule** | a profile that sets `SBX_TOKEN_SUFFIX` uses only the items with that ending (a `work` profile with `-work`: only `github-pat-*-work`). One that doesn't may use every `github-pat-*` item, and `ogun` tries its own first, then the other profiles' |
| **Picking the owner** | from the path. `--org <owner>` or `--item <vault item>` overrides it. Outside `~/Projects`, at a terminal, `ogun` offers a numbered menu of the vault's tokens; without a terminal it uses personal |
| **Registry override** | a repo entry may declare `"github": "<org>"` when its GitHub org differs from its folder (`acme/shop` → the `acme-labs` token). It applies only when the path names the entry's declared `owner` |
| **One per sandbox** | set at create, scoped to that sandbox, and set on attach if missing. The proxy stamps it over any other GitHub credential, so a sandbox can never hold a second GitHub identity. Cross-org work goes through the host: `git fetch sandbox-<name>`, then push yourself |
| **Never global** | a global `github` secret is injected ahead of every sandbox's own, which silently switches identities. `ogun` warns if one appears; remove it with `sbx secret rm github` |

The choice never comes from a file inside the worked-on repo. If it did, anyone who could
push to that repo could hand its sandbox a different token.

### Minting and rotating: `og token`

```bash
og token              # personal, 60 days
og token acme         # any folder under ~/Projects
og token acme 90      # another lifetime: 1 to 366 days, GitHub's maximum
```

`og token` opens GitHub's token form **pre-filled** with the spec below, waits while you paste
the result over the 1Password item's `credential` field, and records the expiry date, so
`ogun` warns a week before it runs out. The lifetime you give pre-fills the form and is the
date recorded, so the warning stays right. An org's lifetime policy can cap it lower, and
GitHub enforces that in the form. Create a new item under the exact name `og token` prints, of
the **API Credential** kind: og reads the item's `credential` field, which a Login or Password
item doesn't have.
The expiry is recorded only once the item holds a new token. Press Enter without saving
(or with the old token still there, or 1Password locked) and `og token` checks the item three
times in all, asking you again after each of the first two misses. It never sends you to rerun it, which would mint a second token. If there's still
nothing, it records nothing and prints the one-line command to record the expiry by hand. The
owner must be the folder name as it is, lowercase (`og token Acme` is refused), because only
those item names are listed by the menu.

`og` also keeps the date right on its own. Each time it reads an owner's token from
1Password (a create, `og <name> --sync`, a token replaced on attach), it asks GitHub when that
token expires and records GitHub's answer. So a token saved without `og token` recording it
(a Ctrl-C after saving, one made by hand on GitHub) shows its real date from its next create
or `--sync`. The token goes to `curl` on its standard input, never on its command line, and
no answer leaves the date as it was. The warning comes before each create and attach, beside
the one for a global `github` secret, which sbx would hand every sandbox ahead of its own token.

| Setting | Value | Why |
|---|---|---|
| Resource owner | the folder's GitHub owner | the org must allow fine-grained tokens (Org settings → Third-party Access) |
| Repository access | all repositories | one token per owner, reaching every repo of that owner. Protect a repo whose history matters on GitHub itself (branch rules, required reviews), not by keeping the token from it |
| Contents, Pull requests | read and write | push branches, open and update PRs |
| Metadata | read | required by GitHub |
| Actions, Commit statuses | read | an agent can read a PR's checks and CI results |
| Workflows | **none** | a hijacked sandbox can't plant CI that exfiltrates Actions secrets, publish a poisoned build, or reach a self-hosted runner. A branch that edits workflows is pushed from the Mac instead, after you read it: the agent's push fails, it runs `workflow-push-request.sh` (og puts it on every sandbox's PATH, at setup and on every attach), and that prints a `WORKFLOW PUSH REQUEST`, puts a patch in its `out/` and gives one `ogun ship` line. Once you've pushed, the agent runs it again with `--landed` to move its branch onto GitHub's. `ogun ship` applies it in a throwaway worktree with hooks off, refuses a binary or a submodule in any commit, pages every commit's patch with control bytes escaped, and pushes on your `y` |
| Issues, account permissions | none | not needed to push or open PRs; widen the token yourself if your agents use GitHub Issues |
| Expiration | 60 days, or `og token <owner> <days>` for 1–366 | short enough that a leaked token dies on its own |

Rotation takes effect **per sandbox**, not everywhere at once:

1. `og token <owner>`, generate the token, paste it into 1Password.
2. Existing sandboxes keep the old token until you run `og <name> --sync`, which reads the
   token from 1Password again (one unlock). `og token` reminds you.
3. Only then delete the old token on GitHub.

If a token leaks, the damage is limited to code pushes and PRs on that owner's repos, until it
expires: 60 days by default. It has no account, org, workflow or secret access.

## Any other secret: `og pass`

```bash
og pass <name> API_TOKEN api.orders.example --item "orders API token"   # API token
og pass <name> API_TOKEN api.orders.example --paste                     # …not in 1Password
og pass <name> SIGNING_KEY --expose --item "signing key"               # local-use key
og pass <name> SIGNING_KEY --expose --paste                            # …not in 1Password
og pass <name> API_TOKEN --rm                                          # remove it
og pass <name>                                                         # what it holds
```

The defaults are the safe pair: the value comes from 1Password, and the sandbox holds only a
placeholder.

| | The sandbox gets | Use for |
|---|---|---|
| `<host>…` (default) | a placeholder in `ENV`. The proxy swaps in the real value only on requests to those hosts | API tokens. A hijacked sandbox can *use* the token but can't *steal* it |
| `--expose` | the real value in its persistent env. Takes no host | keys used locally, where there's no request to inject into |

| | The value comes from |
|---|---|
| `--item <name>` (default) | that item in the vault `SBX_VAULT` names (`Sandbox` unset), asked for when left out (`--vault`, `--field` for exceptions) |
| `--paste`, `-p` | a hidden prompt, one line. Pipe it in for a multi-line key: `pbpaste \| og pass …` |

- A host is required unless you `--expose`: forgetting it refuses rather than exposing.
- An exposed value goes into the sandbox's stdin, never through argv or a host file.
- A pasted value for the proxy reaches `sbx` as `--value`, so it is in the Mac's process list
  for the instant `sbx` runs. It's never typed on a command line, so never in shell history,
  and nothing is written to disk. `og -v`, which shows each `sbx` command, shows it as not shown.
  `sbx secret ls` shows its first few characters (`dummy-***`): that's sbx's own listing.
- **GitHub is refused.** GitHub hosts are refused. `--expose` refuses items whose name contains `github`,
  pasted GitHub tokens (`ghp_…`, `github_pat_…`) and env names like `GH_TOKEN`. The GitHub
  identity only ever comes from `og`.
- **`--rm` takes it back:** out of `sbx`, and out of the sandbox's environment, a placeholder or an
  exposed value. The proxy may still swap it in until `sbx` restarts. One that came from a secret
  grant stays gone from that sandbox; a new sandbox of the repo gets it.
- **Rotate by passing again.** Don't delete the secret and then test: the proxy caches.

[Appendix: the secrets proxy](appendix/secrets-proxy.md) has the verified proxy behavior.

## Secret grants

A grant hands a 1Password value to sandboxes without anyone running `ogun pass`. Grants live in og's
registry (`registry.json` in its [config folder](config.md)), and come in two scopes:

```json
"secrets": [
  {"env": "EXAMPLE_API_KEY", "hosts": ["api.example.com"], "item": "api-example",
   "field": "credential", "profiles": ["home"]}
],
"repos": {
  "orders": {"owner": "acme", "secrets": [
    {"env": "ORDERS_API_KEY", "hosts": ["api.orders.example"], "item": "orders-staging-key"}]}
}
```

| Scope | Reaches | Gate |
|---|---|---|
| a repo's `secrets` | that repo's sandboxes only | the per-repo gate `template` and `mcp` take: the entry declares `owner`, it matches the path's, and the directory is the repo the entry describes |
| top-level `secrets` | **every** sandbox on the Macs its `profiles` name | the profile rule fails closed: no og profile, no top-level grant |

Top-level is for keys with no identity attached, like an API key billed to nobody in
particular. A token that acts as someone (a git host account, a personal API token) goes on the
repo whose sandboxes need it, never top-level.

**At create.** Each grant the sandbox qualifies for goes through `ogun pass`: the sandbox holds a
placeholder in the env var, the proxy swaps in the value only on requests to the grant's hosts,
and those hosts are allowed for that sandbox alone (`--sandbox`). Nothing is registered
globally. The create record lists the grants that were actually applied, by 1Password source;
a grant is only applied where it can be recorded (no record: none applied; a record that can't be
written: the grant is removed at once), so none is ever live and untracked. Each attach applies any approved grant the record doesn't show yet (a create that
stopped early, or a grant declared since), and never registers one twice: one the sandbox already holds exactly (same variable, hosts and 1Password source, e.g. passed by hand before grants existed) is adopted, its placeholder exported and recorded. Two such registrations are never picked between; the attach says how to keep one. A grant whose variable is also registered for every sandbox (a global registration made by hand) is not applied: sbx won't start a sandbox that holds one variable twice. The attach prints the `sbx secret rm --placeholder … -f` that removes the global one; grants replace it.

**Revoking.** Removing or narrowing a grant (a host dropped, another owner, another source) takes
effect at the sandbox's next attach: the grant's placeholder is removed from the proxy and leaves the
record, its `export` line leaves the sandbox's env (unless the variable was passed again since), and
its hosts' egress is removed unless a kept grant or the template's runtime egress still needs it. One whose placeholder can't be removed, or can't be found in a listing ogun can't fully read, is printed with the commands and tried
again next time (a grant changed in place waits for it: the new one is given once the old is gone); one a full listing shows is
already gone (removed by hand) just leaves the record, its `export` line left naming a placeholder nothing swaps; a registry that doesn't parse revokes nothing. The running proxy may keep
serving a removed secret until the sandboxes daemon restarts. Until a sandbox is attached again it
keeps the grant, so for an urgent revocation, attach to it (or remove it) now.

**Approved once per Mac.** A grant this Mac hasn't approved is printed in full at the create
(`SECRET GRANT, not yet approved on this Mac: …`, with `EVERY SANDBOX` for a top-level one) and
asked about before anything is made. The answer, yes or no, is remembered in `~/.config/sbx/ogun/approved-secrets`
(0600, outside every repo); a changed item, field, host, 1Password vault (`SBX_VAULT`), owner (for a repo grant) or og profile (for a top-level one) is a new grant and is asked again.
With no terminal (a background run), an unapproved grant is skipped and named. A declined grant
isn't asked about again (being asked at every attach would train a reflexive yes); to undo a
decline, delete its line in that file. So an
edit to the registry still hands nothing out until you approve it at a terminal.

**Refused**, with the reason printed: GitHub hosts (one GitHub identity per sandbox), wildcards
or anything but an exact host name, a grant with no host, the env names gh and git read as a
GitHub credential (`GH_TOKEN`, `GITHUB_TOKEN`, …), malformed names, and one variable granted two
different ways (neither is applied).

**Removing a sandbox** leaves its proxy registrations behind, as `ogun pass` does; `ogun tidy`
lists them with the `sbx secret rm` command to run.

## AWS

The proxy can't inject AWS credentials, because requests are signed rather than carrying a
token. So AWS access lives inside each sandbox as a short-lived SSO session, which og leaves
to you: [config: AWS](config.md#example-aws) shows the setup.

## SSH from a sandbox

Sandboxes never get the Mac's ssh-agent. Keys you choose to share go in `~/.ssh/sandbox`,
which is mounted into every sandbox. Put only keys you'd accept losing there, never
your signing key. See [Sandboxes: SSH](sandboxes.md#ssh-no-agent-keys-on-purpose).

