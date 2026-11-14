# Testing og

og is tested in three layers. The first two run anywhere with stand-ins for `sbx`, `op` and
the rest; only the third drives real sandboxes.

| Layer | Runs | Where | Proves |
|---|---|---|---|
| [The suite](#the-suite) | `./test.sh` | any checkout, Mac or Linux | og's logic, with stand-ins for every outside tool |
| [The container](#the-container) | `tests/docker/run.sh` | anywhere with Docker; [CI](#ci) on every push | the suite passes on a clean Linux, with nothing skipped |
| [End to end](#end-to-end) | `tests/e2e/run.sh` | a Mac with Docker Sandboxes and 1Password, by hand | a real sandbox's whole life, create to removal |

## The suite

```bash
./setup.sh      # og's Python and packages, from pins
./test.sh       # everything
./test.sh e2e   # only files whose name contains "e2e"
```

`test.sh` runs each file in `tests/sh/` on its own; `pytest.test.sh` among them runs og's
pytest suite (`tests/`) and ruff. Every outside tool is a stand-in, first on `PATH`, so
nothing reaches a real sandbox, vault or network ([Appendix: ogun's Python](appendix/ogun-python.md#unit-tests-and-lint)).
A file that can't run here (og's Python not built) is a skip, said at the end, never a pass.

It doesn't prove what only the real tools show: what sbx mounts, what its proxy lets
through, what 1Password hands back.

## The container

```bash
tests/docker/run.sh           # build the image from this checkout, run the suite in it
tests/docker/run.sh python    # a filter, as test.sh takes
```

Needs only Docker. The image is Debian with the tools og's tests call, the Mac's two shells
among them (zsh, and bash 3.2 built from GNU's source, for completion), and runs
`./setup.sh` then `./test.sh` as a user that isn't root. Here a skip is a failure: the image
has everything a test needs, so a test that couldn't run means the image is wrong.

| Variable | For |
|---|---|
| `OG_TEST_CA` | a CA certificate file, on a network that inspects TLS: the build trusts it while setup downloads og's pins, and the image never keeps it |
| `OG_TEST_IMAGE` | the image's name (default `og-test`) |

## CI

Every push to `main` and every pull request runs the container (`.github/workflows/test.yml`):
the same `tests/docker/run.sh`, with a read-only token, no secrets, and its action pinned to a
commit. `tests/sh/ci.test.sh` holds the workflow to that.

## End to end

Docker Sandboxes runs each sandbox as a VM on the Mac, mounting the Mac's own paths, and
og's token comes from 1Password unlocked at your terminal. Neither is there in a container or
on a hosted runner, so this layer runs on a Mac, by hand, before a release.

### Before you run it

- `sbx` installed and signed in (`sbx ls` lists), and the 1Password CLI with your account added.
- A GitHub token item for one owner, in your vault: `github-pat-<owner>-<ending>`. The test
  reads it and never makes one; `og token <owner>` does.
- This checkout set up without taking over the `og` on your PATH:

  ```bash
  OG_BIN= ./setup.sh
  ```

### Run it

```bash
OG_E2E=1 OG_E2E_OWNER=acme OG_TOKEN_NAME=home tests/e2e/run.sh
```

| Variable | For |
|---|---|
| `OG_E2E=1` | the opt-in: without it, it refuses |
| `OG_E2E_OWNER` | the owner whose token item the sandbox gets |
| `OG_TOKEN_NAME` | the ending of your token items |
| `OG_VAULT` | the vault, when it isn't `Sandbox` |

og runs with an empty config folder of its own, so the run checks og's defaults and reads
nothing in `~/.config/ogun`. Its state, and what `og take` brings back, go to a scratch
folder. 1Password may ask you to unlock it when the token is read.

It checks, in order, stopping at the first that fails:

1. `og --no-attach` creates the sandbox, and it's listed running.
2. It holds its own GitHub token, for that owner.
3. A baseline host answers from inside; example.com, outside the baseline, is refused.
4. A file from `og give` reads inside; a file left in `out/` comes back with `og take`.
5. A program left in `out/` is quarantined; a script with its exec bit comes back without it,
   marked for Gatekeeper.
6. `og rm` removes it, and nothing of it is left: no folder, no stored secret, nothing
   `og tidy` reports.

A failed check prints the last lines its command printed. Every check's output is kept in a
log in `$TMPDIR` (`og-e2e-<run id>.log`), and a failed run names its path. Exit: 0 every
check passed, 1 one failed, 2 it refused to start.

### What it touches

- **Its own names.** Everything it makes is named `og-e2e-<run id>`. Teardown runs on every
  exit, a failure or an interrupt included, and removes only those: sandboxes, their stored
  secrets and their folders in the exchange, an earlier run's leftovers too. A sandbox or
  secret it can't remove fails the run, with the command to remove it by hand.
- **sbx's global rules.** Creating a sandbox applies og's network baseline, as any create
  does.
- **An approval request.** The refused host may leave a request for approval on your Mac
  until the sandbox goes.

It doesn't cover OpenAPPA, templates or MCP servers.
