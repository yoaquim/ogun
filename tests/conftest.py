"""Shared fixtures: a scratch home that every og setting points into, a registry
builder, and fakes for the programs og runs. No test reaches a real sandbox,
vault, repo remote or network."""

import io
import json
import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

# og's own test data: invented recipes and an OpenAPPA pin of its own, so its tests
# read nothing outside og's folder
FIXTURES = Path(__file__).parent / "fixtures"

FAKED = ("sbx", "op", "curl", "git", "ssh")
REAL_GIT = shutil.which("git")
RUNNERS_HOME = os.environ.get("HOME", "")

# Each fake is this script under the program's name. It answers from <name>.answers
# (the first entry whose args prefix matches, and hold its text if it names one; one given
# once is used up by that call)
# and appends one JSON line per call to <name>.calls: its args, its stdin, and the files
# it inherited open (Linux; none elsewhere).
FAKE = """\
import json, os, sys, time
here, name = os.path.dirname(os.path.abspath(sys.argv[0])), os.path.basename(sys.argv[0])
args = sys.argv[1:]
stdin = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
fds = []
for x in os.listdir("/proc/self/fd") if os.path.isdir("/proc/self/fd") else []:
    try:
        fds.append(os.readlink("/proc/self/fd/" + x))
    except OSError:
        pass
with open(os.path.join(here, name + ".calls"), "a") as f:
    f.write(json.dumps({"args": args, "stdin": stdin, "fds": fds}) + "\\n")
try:
    with open(os.path.join(here, name + ".answers")) as f:
        answers = json.load(f)
except FileNotFoundError:
    answers = []
for i, a in enumerate(answers):
    if args[:len(a["prefix"])] == a["prefix"] and a["has"] in " ".join(args):
        if a["once"]:
            with open(os.path.join(here, name + ".answers"), "w") as f:
                json.dump(answers[:i] + answers[i + 1:], f)
        time.sleep(a["delay"])
        sys.stdout.write(a["stdout"])
        sys.stderr.write(a["stderr"])
        sys.exit(a["code"])
"""


class Fake:
    """One faked program: configure its answers, read back its calls."""

    def __init__(self, bin_dir: Path, name: str):
        self.name = name
        self._answers = bin_dir / f"{name}.answers"
        self._calls = bin_dir / f"{name}.calls"
        exe = bin_dir / name
        exe.write_text(f"#!{sys.executable}\n{FAKE}")
        exe.chmod(0o755)

    def answer(self, prefix: list[str], stdout: str = "", stderr: str = "", code: int = 0, once: bool = False,
               has: str = "", delay: float = 0) -> None:
        """Calls whose args start with prefix (and, joined, hold has) print these
        and exit with code, after delay seconds; earlier answers win. once: only
        the next such call, then it's gone."""
        have = json.loads(self._answers.read_text()) if self._answers.exists() else []
        have.append({"prefix": prefix, "stdout": stdout, "stderr": stderr, "code": code, "once": once, "has": has,
                     "delay": delay})
        self._answers.write_text(json.dumps(have))

    def clear(self) -> None:
        """Every answer dropped: from here on, each call succeeds silently again."""
        self._answers.unlink(missing_ok=True)

    def _records(self) -> list[dict]:
        if not self._calls.exists():
            return []
        return [json.loads(line) for line in self._calls.read_text().splitlines()]

    @property
    def calls(self) -> list[list[str]]:
        return [r["args"] for r in self._records()]

    @property
    def stdin(self) -> list[str]:
        return [r["stdin"] for r in self._records()]

    @property
    def fds(self) -> list[list[str]]:
        """What each call had open when it started: a file og meant to keep (a lock) must not be here."""
        return [r["fds"] for r in self._records()]


class Fakes:
    def __init__(self, bin_dir: Path):
        for name in FAKED:
            setattr(self, name, Fake(bin_dir, name))


@pytest.fixture(autouse=True)
def fresh_notes(monkeypatch):
    """Each test a fresh og run: a note said once a run (config.once) isn't spent by
    an earlier test in the same worker."""
    from ogun.core import config
    monkeypatch.setattr(config, "_said", set())


@pytest.fixture(autouse=True)
def nothing_of_yours(tmp_path, monkeypatch):
    """Every test, with or without the home fixture, a scratch HOME and state folder
    and none of the runner's settings or terminal: a test that forgets home writes no log line or
    name list into the real ones. The home fixture builds its fuller one over this."""
    from ogun.core import settings
    for n in (*settings.NAMES, "XDG_CONFIG_HOME"):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "no-home"))
    monkeypatch.setenv("SBX_OGUN_DIR", str(tmp_path / "no-home/.config/sbx/ogun"))
    # nor the runner's terminal: TERM=dumb or NO_COLOR would turn off the colors a test forces
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)


@pytest.fixture(autouse=True)
def no_profile_of_yours(monkeypatch):
    """No test runs under the profile the shell running the tests names (OG_PROFILE):
    one its config doesn't have stops og. A test that needs one sets it."""
    monkeypatch.delenv("OG_PROFILE", raising=False)


# two Macs' profiles in one config.toml: home naming its tokens, work using only
# -work tokens
MAC_PROFILES = '[profiles.home]\nSBX_TOKEN_NAME = "desk"\n\n[profiles.work]\nSBX_TOKEN_SUFFIX = "-work"\n'


def use_profile(home: Path, name: str | None) -> None:
    """Tell og which of this Mac's profiles to use (None: none), its config.toml
    holding both, after any settings a test wrote there."""
    d = home / ".config/ogun"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "config.toml"
    text = f.read_text() if f.exists() else ""
    if "[profiles." not in text:   # a config with profiles of its own keeps them as they are
        f.write_text(text + ("\n" if text else "") + MAC_PROFILES)
    p = d / "profile"
    p.unlink(missing_ok=True) if name is None else p.write_text(name + "\n")


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """A scratch home: HOME, og's state and config folders and ~/Projects all
    inside it, so nothing reads or writes the real ones; no other setting set, and
    no file in the config folder until a test writes one."""
    h = tmp_path / "home"
    for d in (".config/sbx/ogun", ".config/ogun", "Projects"):
        (h / d).mkdir(parents=True)
    # no setting, and no settings file, from whoever runs the tests
    from ogun.core import settings
    for n in (*settings.NAMES, "XDG_CONFIG_HOME", "OG_PROFILE"):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("SBX_OGUN_DIR", str(h / ".config/sbx/ogun"))
    monkeypatch.setenv("SBX_PROJECTS", str(h / "Projects"))
    yield h
    # writable again: a test may lock a folder (a skills store), and pytest can't clear
    # a read-only folder from its old runs, so they'd pile up
    for d, _, _ in os.walk(h):
        try:
            os.chmod(d, os.stat(d).st_mode | stat.S_IWUSR)
        except OSError:
            pass


@pytest.fixture
def registry(home):
    """Write og's registry: registry({"name": {"owner": ...}}) sets its repos."""
    f = home / ".config/ogun/registry.json"

    def write(repos: dict, **top) -> Path:
        f.write_text(json.dumps({"mcp": [], **top, "repos": repos}))
        return f

    write({})
    return write


@pytest.fixture
def fakes(tmp_path, monkeypatch):
    """sbx, op, curl, git and ssh, faked first on PATH."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    # a call given no input inherits fd 0: empty, so a fake reading it never waits
    # on whatever pipe the test run itself was started with
    saved, null = os.dup(0), os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    try:
        yield Fakes(bin_dir)
    finally:
        os.dup2(saved, 0)
        os.close(saved)
        os.close(null)


@pytest.fixture
def stand_in(tmp_path, monkeypatch):
    """stand_in(name, script): a program og runs that isn't one of the fakes (file,
    pngpaste, xattr, ps), as a small sh script first on PATH."""
    d = tmp_path / "stand-ins"
    d.mkdir()
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")

    def put(name: str, script: str) -> Path:
        f = d / name
        f.write_text(f"#!/bin/sh\n{script}\n")
        f.chmod(0o755)
        return f

    return put


@pytest.fixture
def real_git(tmp_path, monkeypatch):
    """The real git first on PATH, ahead of the fake, for cases that read or make a
    real checkout. Only git: every other fake stays in front. No system config."""
    d = tmp_path / "real-git"
    d.mkdir()
    (d / "git").symlink_to(REAL_GIT)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return REAL_GIT


@pytest.fixture
def og(home, monkeypatch, capfd):
    """Run og in this process, as `og <args>` would: og(*args) -> (exit code, stdout,
    stderr). Output is captured at the file descriptors, sbx's own included, so it's
    the plain form a pipe gets."""
    from ogun import cli
    from ogun.core import log

    # Homebrew's folders never go ahead of the fakes
    monkeypatch.setattr(cli, "BREW", ())

    def run(*args: str, stdin: str | None = None) -> tuple[int, str, str]:
        log._consoles.clear()
        monkeypatch.setattr(sys, "argv", ["og", *args])
        # set, not deleted: og's -v writes os.environ itself, and only a set is undone after the test
        monkeypatch.setenv("OGUN_VERBOSE", "")
        if stdin is not None:
            # bytes underneath, as a pipe is: og pass --paste reads sys.stdin.buffer
            monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin.encode())))
        try:
            cli.main()
            code = 0
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        out = capfd.readouterr()
        return code, out.out, out.err

    return run


@pytest.fixture
def world(home, registry):
    """The registry and folders the cases below stand in: two umbrella repos that grant
    each other, personal repos, a repo placed by path outside ~/Projects, and
    lookalikes that share a registered repo's basename."""
    p = home / "Projects"
    for d in ("umbrella/shop-a", "umbrella/shop-b", "umbrella/sneak", "personal/oddball", "personal/plain",
              "personal/placed", "elsewhere/oddball", ".hidden-repo/sub", ".tilde", "misnamed", "ownerless", "tmp/.hidden-repo"):
        (p / d if not d.startswith((".", "elsewhere", "misnamed", "ownerless", "tmp")) else home / d).mkdir(parents=True)
    registry({
        "shop-a": {"owner": "umbrella", "description": "x",
                    "repos": {"read": ["umbrella/shop-b", "personal/plain", "umbrella/../sneak"], "write": []}},
        "shop-b": {"owner": "umbrella", "description": "x", "repos": {"read": [], "write": ["umbrella/shop-a"]}},
        "oddball": {"owner": "personal", "github": "oddball-org", "description": "x"},
        "plain": {"owner": "personal", "description": "x"},
        "planner": {"owner": "personal", "description": "x"},
        "orphan": {"description": "x"},
        ".hidden-repo": {"owner": "umbrella", "github": "hidden-org", "path": str(home / ".hidden-repo"), "description": "x",
                  "mcp": ["db-hidden"], "repos": {"read": ["umbrella/shop-b"], "write": []}},
        ".tilde": {"owner": "umbrella", "path": "~/.tilde", "description": "x"},
        "placed": {"owner": "umbrella", "path": str(p / "personal/placed"), "description": "x"},
    })
    return home


TST_RECIPE = """#!/usr/bin/env bash
# a test recipe
#
# egress: example.com, *.example.org
# runtime-egress: api.example.com *.api.example.com
# scrub: ~/.cache/tst
echo recipe-body
"""


@pytest.fixture
def recipes(home, registry, fakes, real_git, monkeypatch):
    """A Mac with the fixture recipes plus tst (declared egress, runtime egress, a scrub),
    the pinned OpenAPPA, a team plugin's marketplace (the work profile only), a skill to
    mirror, and a registry: initech/printer asks for the work template and the
    plugin, loose asks with no owner, odd for a recipe that isn't there, archive
    declares OpenAPPA private places. This Mac is the home. The token step reads one
    from 1Password; GitHub never answers about its expiry."""
    t = home / ".config/ogun/templates"
    t.mkdir(parents=True)
    for f in (FIXTURES / "templates").glob("*.sh"):
        shutil.copy(f, t)
    (t / "tst.sh").write_text(TST_RECIPE)
    shutil.copy(FIXTURES / "appa.lock", home / ".config/ogun/")
    registry({
        "printer": {"owner": "initech", "template": "work", "marketplaces": ["initech-kit"]},
        "loose": {"template": "work"},
        "odd": {"owner": "personal", "template": "nope"},
        "archive": {"owner": "personal", "repos": {"read": ["personal/notes"]}, "appa": {"private": [
            "gitlab.example.com/me/fixtures", "github.com/me/notes", "https://x.example/y", "git.example.com/../etc"]}},
        "withnotes": {"owner": "personal", "repos": {"read": ["personal/notes"]}},
        "stray": {"owner": "umbrella", "appa": {"private": ["git.example.com/me/stray"]}},
    })
    (home / ".config/ogun/marketplaces.json").write_text(json.dumps({"marketplaces": {"initech-kit": {
        "path": "~/Projects/initech/plugins", "profiles": ["work"], "plugins": ["widgets"]}}}))
    use_profile(home, "home")
    (home / "agent-config/skills/one").mkdir(parents=True)
    (home / "agent-config/skills/one/SKILL.md").write_text("skill\n")
    for d in ("initech/printer/sub/printer", "personal/printer", "personal/loose", "personal/plain", "personal/odd"):
        (home / "Projects" / d).mkdir(parents=True)
    for k, v in (("SBX_EXCHANGE", "exchange"), ("SBX_SSH_DIR", "no-ssh"), ("SBX_SKILLS_STORE", "skills-store")):
        monkeypatch.setenv(k, str(home / v))
    # a team's agent config: its setup run in every sandbox, its skills, and the folder mounted
    monkeypatch.setenv("SBX_PROVISION", "~/agent-config/provision.sh --all")
    monkeypatch.setenv("SBX_SKILLS_DIR", "~/agent-config/skills")
    monkeypatch.setenv("SBX_HOST_RO_MOUNTS", f"~/agent-config:{home / 'reference'}")
    (home / "exchange").mkdir()
    monkeypatch.setenv("SBX_VAULT", "Sandbox")
    fakes.curl.answer([], code=1)
    return home


def with_header(recipe: Path, line: str) -> None:
    """The recipe with one more header line, after its first."""
    lines = recipe.read_text().splitlines(keepends=True)
    recipe.write_text("".join([*lines[:1], line + "\n", *lines[1:]]))


def listing(*images: str) -> str:
    """`sbx template ls` holding these images, and sbx's own default."""
    rows = [f"docker.io/library/{i + ':latest':<28} 3 days ago" for i in images]
    return "\n".join(["TEMPLATE                                       CREATED", *rows,
                      "docker.io/docker/sandbox-templates:claude-code-docker   2 months ago"]) + "\n"


@pytest.fixture
def stub(recipes, fakes):
    """sbx as creates and builds meet it, set per case. images: what `template ls`
    lists. golden: the build sandboxes that exist once a build's create has run
    (listed at their own workspace, or at race_ws: someone else's). leftover: one
    listed before the build starts, at leftover_ws. The rest fail one step each."""
    s = fakes.sbx
    state = recipes / ".local/state"

    def set_(*images, tpl_fail=False, policy_fail=False, golden=(), leftover="", leftover_ws="", race_ws="",
             stop_fail=False, rm_fail=False, appa_fail=False, activate_fail=False, origin="", private="false",
             recipe_fail=False, create_fail=False, op_fail=False):
        s.clear()
        s.answer(["template", "ls"], stdout=listing(*images), code=1 if tpl_fail else 0)
        s.answer(["settings", "get"], stdout="false\n")
        head = "NAME  STATUS  WORKSPACE\n"
        first = head + (f"{leftover}  stopped  {leftover_ws or state / leftover.replace('golden-', 'sbx-golden-')}\n"
                        if leftover else "")
        made = "" if create_fail else "".join(
            f"{g}  running  {race_ws or state / g.replace('golden-', 'sbx-golden-')}\n" for g in golden)
        s.answer(["ls"], stdout=first, once=True)
        s.answer(["ls"], stdout=head + made)
        s.answer(["policy"], code=1 if policy_fail else 0)
        s.answer(["stop"], code=1 if stop_fail else 0)
        s.answer(["rm"], code=1 if rm_fail else 0)
        for has, out, code in (("agent:none", "agent:none\n", 0), ("releases/download", "", int(appa_fail)),
                               ("activate.sh", "", int(activate_fail)), ("remote get-url origin", origin and origin + "\n", 0),
                               ("gh api repos/", private + "\n", 0), ("bash -euo pipefail /tmp/ogun-recipe.sh", "", int(recipe_fail)),
                               ("claude update", "v 1.0 1.1\n", 0)):
            s.answer(["exec"], stdout=out, code=code, has=has)
        s.answer(["env", "create"], stdout="Environment plan: 9 mounts — needs your approval\n",
                 stderr="error: create failed: disk full\n" if create_fail else "", code=1 if create_fail or race_ws else 0)
        fakes.op.clear()
        fakes.op.answer([], stdout="" if op_fail else "ghp_testtoken", code=1 if op_fail else 0)
        return s

    return set_
