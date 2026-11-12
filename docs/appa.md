# OpenAPPA

[OpenAPPA](https://www.openappa.com) is a guardrail that runs inside a Claude Code session. It
records what the session has read, and checks each write against who may see that data. Ogun
can turn it on for a sandbox, to close one gap its network rules can't: your own repos.

## Why

Ogun's network rules stop data reaching a stranger's account
([Network: what the baseline leaves out](network.md#what-the-baseline-leaves-out)), and a
`git push` reaches only the sandbox's own repos
([Network: pushes to GitHub](network.md#pushes-to-github)). What they can't stop is a pull
request or an issue in **your own** public repos. The sandbox's GitHub token can write to every
repo of its owner, the proxy sends every GitHub request as you, and `gh` sends those through
one GraphQL address that a network rule can't tell apart. So a pull request carrying private
code looks like normal work to the network layer: same host, same identity.

OpenAPPA works one level up. Reading the workspace marks the session's data "for you only".
After that, a push, PR or issue to a public repo is refused or held for your approval before it
runs.

The [leak tests](appendix/appa-leak-tests.md) check this on three routes: `git push`,
`gh pr create` and `gh issue create`, each refused with OpenAPPA on and each let through
without it.

## Turning it on

It's chosen when a sandbox is created, in one of two ways:

| How | What it covers |
|---|---|
| `ogun <name> --appa` | that new sandbox |
| `# appa: on` in a template recipe | every sandbox made from that template, and every repo whose registry entry names it |

```bash
cd ~/Projects/personal/cub
ogun --appa                      # a new sandbox with OpenAPPA
```

```bash
#!/usr/bin/env bash
# ogun template recipe: orders — …
#
# appa: on
```

- **At create only.** Passing `--appa` to an existing sandbox that was made without it is
  refused, and the error says how to recreate it. Passing it to one that has it does nothing.
- **A warning for private repos.** When a new sandbox's repo is a private GitHub repo and
  OpenAPPA isn't on, the create ends with a block headed `⚠ NO OPENAPPA ON A PRIVATE REPO`
  (orange on a terminal), saying how to recreate it with OpenAPPA. It never asks, and it says
  nothing for public repos, other hosts, or later attaches.

## Without it, nothing changes

A sandbox created without `--appa`, from a template without `# appa: on`, gets nothing
OpenAPPA-related: no download, no file, no rule, and its attach starts `claude` as always. The
private-repo reminder is the only thing it can see.

## What you see

- **Attach starts `clappa`.** `ogun <name>` and `ogun attach <name>` start OpenAPPA's launcher in
  the workspace instead of `claude`. `ogun sh <name>` stays a plain shell.
- **The status line** is OpenAPPA's: the session's trust and audience. `audience:self` means the session has read your private data.
- **Approval cards.** A call OpenAPPA won't allow on its own shows a card: approve it for that one
  call, or decline it.
- **`ogun ls`** gets a `PLUGINS` column, `OpenAPPA` on each protected sandbox's row, when any
  sandbox has it.

## What protection covers

Ogun writes a block into OpenAPPA's policy at create
([`policy.py`](../sandbox-scripts/appa/policy.py)). OpenAPPA's own rules for Claude Code's tools and
for GitHub stay as they ship.

| Rule | Effect |
|---|---|
| who you are | `self` is the GitHub account of the sandbox's token (`github:viewer`). Its email isn't needed |
| the workspace | reading or searching under it, by path, narrows the session to `self` |
| read-only related repos | the same, for each repo the create mounts read-only |
| shell commands | the shell classifier is told the same paths are private, relative paths included |
| pushes to your own repo | a `git push` to the workspace's own `origin` is for `self`, so pushing your own work doesn't ask. On GitHub, only when GitHub says the origin is private (asked at create, with the sandbox's token): a public origin, or one GitHub doesn't answer for, gets OpenAPPA's own rules, so pushing private reads there asks. Off GitHub, Ogun can't ask, and takes every origin as private, a public one included (see Limits). A push anywhere else is judged by OpenAPPA's GitHub rules |
| other private places | a `git push` to a place the repo's registry entry lists ([below](#other-private-places)) is for `self` too |

Once a session is `self`, a write to a public repo needs your approval, and a decline stops it.

### Other private places

A protected repo that also pushes somewhere private off GitHub, such as a GitLab project,
would show a card on every such push: OpenAPPA can't look those up. List them in the repo's
entry in og's registry (`registry.json` in its [config folder](config.md)), as `host/path` with no scheme:

```json
"orders": {
  "owner": "acme",
  "appa": { "private": ["gitlab.example.com/acme/orders-fixtures"] }
}
```

- **Same gate as the entry's other grants:** the entry declares `owner`, it's this sandbox's
  owner, and the folder is the repo the entry describes. Otherwise the list is skipped, with
  the reason.
- **Not GitHub.** A `github.com/…` entry is refused: OpenAPPA asks GitHub whether a repo is
  private, and a listed public one would take private reads without a question.
- **Read at create,** like the read-only mounts. The create prints the list. To change it,
  edit the entry and recreate the sandbox.
- **A hint, not a fixed rule.** The places are named in the hint for OpenAPPA's push
  classifier, beside the own `origin`, so a model applies them (see Limits). Everything must
  fit OpenAPPA's 512-character hint; a list that doesn't fails the create.

## What an install does

| Step | Detail |
|---|---|
| version | pinned in `appa.lock` in og's config folder ([config](config.md)): a release tag and each Linux archive's SHA-256. A bump changes what every new sandbox installs |
| network | `release-assets.githubusercontent.com`, where a GitHub release download lands, allowed for that sandbox only. `github.com` is already in the baseline. `sbx rm` drops the rule with the sandbox |
| download | `appa-<arch>-unknown-linux-gnu.tar.gz` from the pinned release, over HTTPS only, redirects included |
| script | [`appa/install.sh`](../sandbox-scripts/appa/install.sh), sent into the sandbox as text, since a template's build sandbox has no host mounts. It does the download, checks and install below |
| checks | the SHA-256 against the lock; no archive entry that's absolute or climbs out with `..`; `appa` a regular file, not a link; `appa --version` runs |
| install | `/usr/local/bin/appa`. An `appa` already at the pinned version, from a template's image, is kept |
| token | the sandbox's GitHub token is set before the install, not after it as without OpenAPPA: the policy asks GitHub whether the origin is private |
| activation | [`activate.sh`](../sandbox-scripts/appa/activate.sh), inside the sandbox: below. og sends it in with `ensure.sh` and `policy.py`, unpacked into a fresh folder for the run and removed after, so it needs nothing of og's mounted in the sandbox. Once the marker is written it runs og's provision command again (`provision`), and whatever that leaves, it makes `~/.claude/skills` and `settings.json` if they're missing |
| record | `"appa": {"version": …}` in the sandbox's record |

**Activation** turns it on:

1. **A marker,** `~/.config/ogun/appa`, then og's provision command again. A provision
   command can read the marker to leave `~/.claude/skills` a real folder, so OpenAPPA can
   keep its own skill there. With no provision
   command, or one that sets up no Claude Code config, the folder is made empty; a link there is
   refused.
2. **OpenAPPA's Claude Code plugin,** at the pinned version, with reporting to OpenAPPA off:
   `appa plugin install claude-code --no-agent-yell --revision <version>`.
3. **Its hooks, saved** to `~/.local/share/appa/ogun-hooks.json`. Every attach's provision
   command may rewrite `settings.json`; og merges them back before each session (below).
4. **Ogun's policy block,** then OpenAPPA's own check of the whole policy.
5. **The status line** `clappa` uses: the provision command's own, when it leaves an executable at og's hook, `~/.config/ogun/appa-statusline`; else OpenAPPA's. A line whose script has since gone is pointed at the hook on the next attach.
6. **The runtime,** OpenAPPA's local service on `127.0.0.1:8787`, restarted on that policy.

- **Fails closed.** A create that asked for OpenAPPA and couldn't install or activate it removes
  the new sandbox and stops, so a sandbox never looks as if it had OpenAPPA when it doesn't.
- **Template builds** with `# appa: on` install the binary after the recipe runs, before the
  scrub. Activation is per sandbox, at create, because the policy names its workspace.

## Every attach

[`ensure.sh`](../sandbox-scripts/appa/ensure.sh) runs before the session starts:

- **The hooks** go back into `settings.json`: each saved entry missing from its event is added, and what the
  provision command wrote stays. A `settings.json` that can't be read, or no saved hooks, is no session.
- **The runtime** must answer. A sandbox stops soon after its last session ends, and a stop
  ends every process in it, the runtime too, so most attaches start it again. That is
  expected, and nothing runs before it answers. The GitHub rules get the sandbox's token placeholder, and the proxy swaps in the real
  token.

If either can't be had, **no session starts**, and the error says to run `ogun <name> --sync`
and attach again. A sandbox with OpenAPPA
installed but not on (no marker) has activation run on its next attach first, with its workspace and
today's read-only related repos, and starts no session if that fails. OpenAPPA also fails
closed on its own: a protected session whose runtime is down blocks every tool call. A shell
from `ogun sh` doesn't start it, so `appa` commands there may find it down.

## Limits

- **Interactive sessions only.** OpenAPPA protects a session started with `clappa`. Background
  sessions start through Claude Code's background daemon and can't be protected.
- **Origins off GitHub count as private.** og can ask only GitHub whether a repo is private, so
  a push to the workspace's own origin anywhere else (GitLab, Codeberg, a server of your own)
  is taken as private, public ones included: pushing private reads there doesn't ask.
- **Shell commands are judged by a model.** `git`, `gh` and other shell calls are classified by
  OpenAPPA's shell classifier, guided by Ogun's hint, not by a fixed rule. Reads by path, with
  Read and Grep, are fixed rules.
- **Messages between sessions get stricter.** After a protected session reads private data,
  `SendMessage` to a session by name is refused, because a name could belong to an unprotected
  session. Messages from unprotected background sessions arrive held and untrusted. How many
  extra cards this adds isn't measured yet.
- **Agent view is off** in `clappa` sessions, so background sessions aren't listed there.
- **Extra model use.** For each Bash command that no fixed rule decides, the runtime starts a
  separate, tool-less `claude -p --model sonnet` with the sandbox's Claude login. That counts
  against your Claude plan's usage, not a separate bill. The model is OpenAPPA's
  `externals.claude_code.model` setting. How much a long session adds isn't measured yet.
- **Subagents that set `maxTurns` are refused,** because Claude Code skips the check of their
  return.
- **Connectors aren't in Ogun's block.** Gmail, Notion, Drive, Calendar and other connectors'
  tools are judged one call at a time, and may ask more often.
- **Preview software.** OpenAPPA is young, and it works through Claude Code's hooks, so an update
  to either can change its behavior. Rerun the
  [leak tests](appendix/appa-leak-tests.md) after a version bump.

## Bumping the version

1. Read the release notes.
2. Copy the tag and both Linux digests into `appa.lock` in og's config folder:

   ```bash
   gh api repos/archestra-ai/OpenAPPA/releases/tags/v0.38.0 \
     -q '.assets[] | select(.name | test("unknown-linux-gnu")) | "\(.name) \(.digest)"'
   ```

   (The `sha256:` prefix isn't part of the hash.)
3. Rebuild any template with `# appa: on` (`ogun template <name>`).
4. Rerun the [leak tests](appendix/appa-leak-tests.md).
