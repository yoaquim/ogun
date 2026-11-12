<div align="center">

<img src="docs/og-mark.svg" width="64" height="64" alt="">

# Ogun

**Claude Code in a sandbox per project. Never on your Mac.**

[Install](#install) · [How it works](#how-it-works) · [Docs](docs/README.md) · [MIT](LICENSE)

</div>

<br>

```bash
cd ~/Projects/acme/shop
og              # creates the sandbox and attaches you; next time, just attaches
og rm shop      # removes it, unless that would lose work
```

`og` wraps [Docker Sandboxes](https://docs.docker.com/ai/sandboxes/): one command creates a
sandbox for the repo you're in, wires up its token, network and files, and drops you into
Claude Code inside it.

## How it works

<img src="docs/proxy.svg" alt="The sandbox holds only a placeholder. The sbx proxy on the Mac swaps in the real token from 1Password on requests to its own API; every other host gets the fake value." width="100%">

Secrets stay on the Mac. A sandbox gets a placeholder, and the proxy swaps in the real value
only on requests to the host it's for, so a hijacked agent can use a token where it's meant
to go but never copy it out.

| | |
|---|---|
| **One sandbox per repo** | Its own clone, so the agent's edits never touch your checkout. Exiting only detaches. |
| **Scoped GitHub access** | A token per owner from 1Password; pushes only to the repo's own remotes. |
| **Default-deny network** | A small read-mostly baseline. Anything else asks you first, for that sandbox alone. |
| **File exchange** | `og give` and `og take` move files in and out, screened on the way. |
| **Yours to shape** | Mount folders, run your own setup, add tools, build templates. |

## Install

Requires macOS, Docker Sandboxes (`sbx`), 1Password and its CLI (`op`), `git` and `curl`.

```bash
git clone https://github.com/yoaquim/ogun.git && cd ogun
./setup.sh
```

`setup.sh` builds og from pinned, checksummed versions and puts `og` on your PATH. It runs
with no configuration; add settings, repos and templates in `~/.config/ogun/` when you need
them ([config](docs/config.md)).

## Docs

[Overview](docs/README.md) · [Setup](docs/setup.md) · [Sandboxes](docs/sandboxes.md) ·
[Network](docs/network.md) · [Secrets](docs/secrets.md) · [Templates](docs/templates.md) ·
[File exchange](docs/exchange.md) · [Customizing](docs/config.md#make-sandboxes-your-own)
