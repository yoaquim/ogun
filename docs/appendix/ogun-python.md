# Appendix: ogun's Python

`og` is a Python command, in `src/ogun/`. `setup.sh` installs it into og's own
environment (`.venv` on a Mac) and links it as `~/.local/bin/og` and
`~/.local/bin/ogun` (`OG_BIN`), so it runs from any shell, script or cron job, with no profile loaded.
Its settings come from `~/.config/ogun/config.toml` and the environment
([flags-and-env.md](flags-and-env.md#settings)), never a shell profile. The command table
(`help.py`) is the one list of commands and their arguments, which `og help`, every usage
line and tab completion read. Tab completion is og's own, `completion.bash`, tested to
define nothing else and to work in bash 3.2 (a Mac's `/bin/bash`), bash 5 and zsh; a shell
profile sources it. In zsh it loads `completion.zsh`, which asks bash, running
`completion.bash`, for what a Tab offers, so both shells offer the same. What
it asks of og goes through `_og_run`, the installed og in its own folder (`og internal …`). The baseline lists live in
`src/ogun/net/baseline.toml`, beside the module that reads it; `og internal baseline`
prints the baseline og applies as a `[baseline]` table, ready to copy into `config.toml`.
og's own behaviour is pytest, in `tests`.

## What runs where

| You type | What runs |
|---|---|
| `og …` or `ogun …` | `~/.local/bin/og`, a link to `.venv/bin/og`: og's Python, from `src/ogun/` as it is |
| `og <TAB>` | og's completion, `completion.bash`, which your shell profile sources |

## Layout

og's package, `src/ogun/`, is one folder per concern, no module over 400 lines and
no function over 60 (`tests/test_layout.py` holds all three):

| Folder | What's in it |
|---|---|
| `core/` | the output (`log`, `boxes`), settings, paths, sandbox names, the registry, the `sbx` gateway, records |
| `net/` | the rule table, the baseline and ssh-agent guard, GitHub push rules, the registry's egress, `og allow`, `og net` and its `--log`/`--check`, `og policy` |
| `exchange/` | the checks every file a sandbox wrote goes through, a sandbox's folders, `og scan`, `take`, `give`, `tidy` |
| `sandbox/` | create (its choices, its record, the init offer), attach and its session, `ls`/`sh`/`stop`, `rm`, `out`, templates, setup, OpenAPPA, `ports`/`doctor` |
| `secrets/` | `og pass` and what a sandbox holds, the secret grants, the GitHub token, the bare `og`, ssh keys |

`cli.py`, `help.py`, `ship.py` and `mcp.py` sit beside them. The scripts og sends into a
sandbox live outside the package, in `sandbox-scripts/`, each one
shellcheck clean (tested too) and run by pytest against scratch folders. A name another module uses
is public, and no local name may hide a module its file imports (both are tested).

## Output

The rules are [og's style](ogun-style.md); in short:

- **On a terminal:** a dim clock, then each line in Rich's colors: green done, yellow
  warning, red error, a bold arrow on each step. `og policy` ends with a short summary.
- **Piped or in a file:** the same words, plain, with no clock, colors or summary, so a
  `grep` always matches.
- **More detail, when you ask:** `-v` shows each `sbx` command run, how it ended and how long
  it took; `-vv` adds what `sbx` printed. These lines go to stderr. The level travels as
  `OG_VERBOSE`, so `og -v <bash command>` shows the `sbx` calls bash makes through
  Python too.

og is never built, and installing it downloads nothing: `setup.sh` writes a `.pth`
file that puts `src` on the environment's path as it is, and the `og` script that
`pyproject.toml`'s `[project.scripts]` names, which runs the environment's `python -I`.
Run off a Mac (on Linux, inside a sandbox, say), `setup.sh` builds `.venv-<system>`
instead (`bin/venv` picks it), so a copy two systems share through a mount keeps one
venv for each. `-I` ignores `PYTHONPATH`, user
site-packages and the current folder, so a `json.py` in the folder you run it from is never
imported. An edit to `src` takes effect on the next run.

## How it's pinned

Nothing updates on its own. `setup.sh` builds the venv, and
installs only what these files name. A new version of anything is an edit to them, made
deliberately, then `setup.sh` again.

- **uv** is the version in `uv.pin`. `setup.sh` downloads that release from GitHub
  and refuses it unless its SHA-256 matches the pin, then keeps it in
  `~/.local/share/ogun/uv-<version>/`, apart from any other uv. Not Homebrew: a
  `brew upgrade` would move it. `required-version` in `pyproject.toml` makes any other uv
  refuse the project. uv is used only to build the venv, never when `og` runs. The wheels it
  downloads stay in its own cache, `~/.cache/uv`, so a rebuild is quick; it's safe to delete.
- **Python** is the exact version in `.python-version`. The Mac's own `/usr/bin/python3`
  is too old (3.9), so uv downloads that build into `~/.local/share/ogun/python/` and checks
  it against the checksums built into the pinned uv. `only-managed`, `--managed-python`:
  a Python Homebrew or Apple installed is never used. `setup.sh` checks the venv runs exactly
  that version.
- **Packages:** `uv.lock` pins every package to one version with its sha256 hashes.
  `uv sync --frozen` installs exactly that and never re-resolves. A file that doesn't match
  its hash is refused.
- **No outside settings:** `setup.sh` clears every `UV_*` variable and passes `--frozen`,
  `--no-build` and the Python as flags, which win over any `uv.toml`.
- **Wheels only** (`no-build`): no package's setup code runs at install time. ogun itself
  is never built (`package = false`); `setup.sh` writes the `og` command and a `.pth` file
  that points the venv at `src/` as it is.
- **A two-week cutoff** (`exclude-newer`): a lock can't pick a release newer than the
  date, so a hijacked release has usually been caught and pulled first. Move the date when
  you bump.
- **What's installed:** Typer, and what it needs: Rich (with Pygments, markdown-it-py and
  mdurl), Shellingham and annotated-doc. All pure Python. For tests and lint, the `dev`
  group: pytest (with pluggy, iniconfig and packaging), pytest-xdist and ruff, pinned and hashed the same
  way and installed into the same venv. ruff ships a native binary per platform, each wheel
  hashed in the lock. `tests/sh/python.test.sh` fails if
  a pin goes loose: uv without a version or a checksum, a Python range, a package without
  its hashes or its wheel, or a lock and `pyproject.toml` that disagree.

## Unit tests and lint

og's unit tests are pytest, in `tests/`, one test module per source module. A change
to og's behaviour comes with the test that shows it.
`tests/conftest.py` holds what they share:

- **`home`**: a scratch home, with `HOME`, og's state folder, its config folder (its files may be
  links, which og reads through) and `projects` all inside it, so no test reads or writes the real ones.
- **`registry`**: writes that home's registry, `registry({"name": {"owner": ...}})`.
- **`fakes`**: sbx, op, curl, git and ssh, first on `PATH`. `fakes.sbx.answer(["ls"],
  stdout=..., code=...)` sets what a call starting with those arguments prints and exits
  with (the first match wins; anything else succeeds silently; `once=True` answers only the
  next such call, `has=` only a call holding that text, `delay=` waits first). `fakes.sbx.clear()` drops every answer. `fakes.sbx.calls` and
  `fakes.sbx.stdin` read back each call's arguments and input.
- **`og`**: runs `og <args>` in the test's own process, `og(*args, stdin=...)` → exit code,
  stdout, stderr.

Run them with `.venv/bin/python -m pytest` in the repo (`.venv-<system>` off a Mac), and lint
with `.venv/bin/ruff check`. They run in parallel, a worker per core (`pytest-xdist`, a
test-only package pinned like the rest of the dev group, never in og itself): each test has
its own scratch home and fakes, so none depends on another or on their order. `-n0` runs
them one at a time, for one test or a debugger. A test never forks the test process
itself, since a worker has threads; a child it needs is a fresh process. The rules ruff applies are named in `pyproject.toml`, never
its defaults, which change between releases. og's own runner, `test.sh`, runs both
through `tests/sh/pytest.test.sh`, which also checks that a failing pytest test fails the
run, along with og's other shell tests in `tests/sh/`.

A name another module uses is public: `tests/test_public_names.py` fails on any
`module._name` reach-in, or `from ogun.x import _name`, between og's modules.

Bumping a pin:

- **a package:** its `==` pin in `pyproject.toml`, `exclude-newer` moved to two weeks ago,
  then `~/.local/share/ogun/uv-<version>/uv lock` in the repo;
- **uv:** `uv.pin`'s version and the four SHA-256s from the release
  (`gh api repos/astral-sh/uv/releases/tags/<version>`, each asset's `digest`), and
  `required-version` to match;
- **Python:** `.python-version`, to a version the pinned uv can download
  (`uv python list --only-downloads`).

Then `setup.sh`, and og's tests (`test.sh`).

Read the lock diff before committing: every new name in it is new code on your Mac.

## Testing a branch in one terminal

Leave the copy your shell's `og` runs from as it is; set up a second copy of og at the
branch (a git worktree, or another clone) and run its setup with `OG_BIN` empty, so it
leaves `~/.local/bin/og` pointing at your copy:

```bash
OG_BIN= <second copy>/setup.sh
og() { <second copy>/.venv/bin/og "$@"; }      # this tab only
```

That copy's `og` runs its own code, so that tab runs the branch. Close the tab and it's
gone. It still reads the real registry (through og's config folder) and talks to the real
sbx, exchange and records: test on throwaway sandbox names.
