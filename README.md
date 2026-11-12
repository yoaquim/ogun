<div align="center">

<h1><img src="docs/og-mark.svg" width="30" height="30" alt=""> ogun</h1>

**Claude Code in a sandbox per repo. Never on your Mac.**

[Install](#install) · [What it does](#what-it-does) · [Docs](docs/README.md) · [MIT license](LICENSE)

</div>

<br>

```bash
cd ~/Projects/acme/shop
og              # creates the sandbox and attaches you; next time, just attaches
og rm shop      # removes it, unless that would lose work
```

[Docker Sandboxes](https://docs.docker.com/ai/sandboxes/) gives each agent its own VM.
`og` (or `ogun`) makes that one command per repo, and decides what each sandbox gets: its
code, its token, its network, its files.

<img src="docs/overview.svg" alt="You run og in your repo. og, on the Mac, takes the owner's GitHub token from 1Password, then creates the repo's sandbox and wires up its token, network rules and mounts. The sandbox runs Claude Code on its own clone and trades files with the Mac through the file exchange." width="100%">

## What it does

**One sandbox per repo.** Run `og` in a repo to create its sandbox and attach; exiting
Claude only detaches. The sandbox works on its own clone, so the agent's edits never reach
your checkout. `og rm` refuses while unpushed or uncommitted work would be lost.

**A network that's closed by default.** Each sandbox starts from a short baseline: OS
mirrors and GitHub's download hosts open, npm, PyPI and github.com read-only, everything else
blocked. When the agent needs more, you approve it for that sandbox alone, read-only first.

**GitHub, scoped to the owner.** Each owner's token lives in 1Password (`og token` makes and
rotates it). Every sandbox can clone and pull; pushes go only to its own repo and the ones
you list, so a tricked agent can't push private code into one of your public repos.

**Secrets that never enter the sandbox.** A sandbox holds a placeholder; the proxy on the
Mac swaps in the real value only on requests to the host it's for. `og pass` hands one
sandbox one secret this way.

<img src="docs/proxy.svg" alt="The sandbox holds only a placeholder. The sbx proxy on the Mac swaps in the real token from 1Password on requests to its own API; every other host gets the fake value." width="100%">

**Files through one door.** `og give` puts files in a sandbox's inbox; `og take` brings its
results out after a check, quarantining links, executables and files that aren't what their
name says.

**Sandboxes that start ready.** Templates are images built from recipes you keep in git,
picked per repo. MCP servers load per repo through sbx's gateway, their tokens kept on the
Mac, and Claude plugins mount from your marketplaces.

**An optional guard inside the session.** With `--appa`, [OpenAPPA](docs/appa.md) checks
each write against what the session has read, so private data can't land somewhere public
in a way the network can't tell from normal work.

**Yours to shape.** Mount folders, run your own setup script, add tools: og runs what you
name without knowing what's in it ([customizing](docs/config.md#make-sandboxes-your-own)).

## Install

Requires macOS, Docker Sandboxes (`sbx`), 1Password and its CLI (`op`), `git` and `curl`.

```bash
git clone https://github.com/yoaquim/ogun.git && cd ogun
./setup.sh
```

`setup.sh` builds og from pinned, checksummed versions and puts `og` on your PATH. It runs
with no configuration; settings, repos and templates go in `~/.config/ogun/` when you need
them ([config](docs/config.md)).

## Docs

[Overview](docs/README.md) · [Setup](docs/setup.md) · [Sandboxes](docs/sandboxes.md) ·
[Network](docs/network.md) · [Secrets](docs/secrets.md) · [Templates](docs/templates.md) ·
[File exchange](docs/exchange.md) · [OpenAPPA](docs/appa.md)
