"""`og`: every command runs here, a bare og (bare.py) and help (help.py)
included. setup.sh installs it as the command pyproject.toml declares.

`-v` / `-vv` (anywhere in a command's arguments; for a bare og, before its
flags) turn on more detail for everything this run starts: the level travels as
OGUN_VERBOSE (src/ogun/core/log.py)."""

import json
import os
import shlex
import sys

import typer

from ogun import help, mcp, ship
from ogun.core import boxes, changes, config, log, paths, registry, settings
from ogun.exchange import folders, give, scan, take, tidy
from ogun.net import allow, netcmd, policy
from ogun.sandbox import create, health, remove, sandboxes, session, template
from ogun.secrets import bare, secret, token

# only og internal goes through typer: what the shell's completion calls into, so
# each rule has one copy; not for typing. Every command a person types reads its
# own arguments (_RAW_CMDS) and draws its own help
app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)
internal = typer.Typer()
app.add_typer(internal, name="internal")

# each command's format (docs/appendix/ogun-style.md#two-formats): classic, og's
# lines; table, one box of rows. A test holds the guide to this list.
FORMAT = {"help": "classic", "ssh": "classic", "attach": "classic", "mcp": "table", "mcp auth": "classic", "mcp load": "classic", "give": "classic", "ship": "classic", "ports <name>": "table", "ports": "classic", "doctor": "classic", "pass <name>": "classic", "pass": "classic", "token": "classic", "sh": "classic", "stop": "classic", "template ls": "table", "template rm": "classic", "template": "classic", "tidy": "classic", "take <name>": "table", "take": "classic", "scan": "classic", "net <name>": "table", "net <name> --log": "table", "net <name> <domain> --check": "table", "net": "classic", "allow": "classic", "policy": "classic", "rm": "classic", "log": "classic", "project": "classic",
          "style": "classic", "skills": "classic", "ls": "table"}
PORTED = {"help", "ssh", "attach", "project", "mcp", "give", "ship", "ports", "doctor", "pass", "token", "sh", "stop", "template", "tidy", "take", "scan", "net", "allow", "policy", "internal", "style", "skills", "ls", "rm", "log"}
_RAW = {"allow_extra_args": True, "ignore_unknown_options": True}


def project(argv: list[str]) -> int:
    sub, rest = (argv[0], argv[1:]) if argv else ("", [])
    if sub == "ls" and rest in ([], ["--json"]):
        return _project_ls(bool(rest))
    if sub == "add" and len([a for a in rest if a != "--write"]) <= 1 and all(a == "--write" or not a.startswith("-") for a in rest):
        if _registry() is None:
            return 1
        try:
            registry.add(next((a for a in rest if a != "--write"), ""), "--write" in rest)
        except registry.Refused as e:
            log.err(f"og project: {e}")
            return 1
        return 0
    registry.usage("og project needs ls or add" if not sub else f"og project has no subcommand {sub}"
                   if sub not in ("ls", "add") else f"og project {sub}: {' '.join(rest)} isn't something it takes")
    return 1


def _project_ls(as_json: bool) -> int:
    f = _registry()
    if f is None:
        return 1
    d = paths.read_registry()
    if d is None:
        log.err(f"og project: {log.path(f)} can't be read as a JSON object")
        return 1
    if as_json:
        print(json.dumps(registry.entries(d), indent=2, ensure_ascii=False))
        return 0
    if not log.pretty():   # piped: one line a repo, its grants with it, for a grep
        for line in registry.ls_lines(d):
            print(line)
        return 0
    ungranted = []
    for e in registry.entries(d):   # classic: a section a repo, its grants as notes
        grants = ([f"reads {r}" for r in e["read"]] + [f"reads {r} and may push to it" for r in e["write"]]
                  + [f"may push to {u}" for u in e["push"]])
        if not grants:
            ungranted.append(e["repo"])
            continue
        log.section(e["repo"])
        for g in grants:
            log.note(g, clock="")   # a listing happened at no time: no clock
    if ungranted:
        log.section("nothing granted")
        log.note(", ".join(ungranted), clock="")
    return 0


def _registry():
    f = paths.registry_file()
    if not f.is_file():
        config.missing("og project", "registry.json")
        return None
    return f


STYLE_HELP = dict(about="Draw every kind of line, table and box og prints (docs/appendix/ogun-style.md).",
                  forms=[("og style", "one of each")], examples=["og style", "og style | cat"])


def style_usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("style", "", problem=problem, err=err, **STYLE_HELP)


def style(argv: list[str]) -> int:
    if argv:
        style_usage("og style takes no arguments")
        return 1
    boxes.preview()
    return 0


SKILLS_HELP = dict(about="Mirror your skills folder (skills_dir) into sbx's shared skills store, which every sandbox mounts, and lock it read-only.",
                   forms=[("og skills", "after a skill changes; a create does it too")],
                   notes=["Read-only is what stops one sandbox planting a skill for the rest: sandboxes mount the store "
                          "read-write, and this mirror is its only writer."],
                   examples=["og skills"])


def skills_usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("skills", "", problem=problem, err=err, **SKILLS_HELP)


def skills(argv: list[str]) -> int:
    if argv:
        skills_usage("og skills takes no arguments")
        return 1
    if not create.skills_dir():
        log.err("og skills: no skills folder is set (skills_dir names the folder to mirror)")
        return 1
    return 0 if create.skills() else 1


@internal.command("mcp-registry")
def _mcp_registry() -> None:
    """Every server this Mac's registry gives, with who gets it, tab-separated (completion)."""
    for m, users in mcp.registry().items():
        print(f"{m}\t{','.join(users)}")


@internal.command("baseline")
def _baseline() -> None:
    """The baseline og applies, as NAME="value" lines, its settings' hosts in: what a
    check of the live rules compares them with."""
    from ogun.net import baseline
    b = baseline.baseline_lists()
    print("".join(f'{k}="{b.get(k, "")}"\n' for k in baseline.LISTS), end="")


@internal.command("paths")
def _paths() -> None:
    """The folders the shell's completion (or an installer) looks in, as og resolves them,
    a NAME<tab>path line each: one og start gives all four (TEMPLATES: the recipes
    `og template <Tab>` offers; PROJECTS: every project folder, folder[=owner]
    colon-joined as the setting writes them)."""
    from ogun.sandbox import template
    vals = {"EXCHANGE": folders.exchange(), "PROJECTS": ":".join(f + (f"={o}" if o else "") for f, o in paths.roots()),
            "STATE": paths.state_dir(), "TEMPLATES": template.recipes_dir()}
    print("".join(f"{k}\t{v}\n" for k, v in vals.items()), end="")


_VERBOSE = {"-v": 1, "-vv": 2, "--verbose": 1}


def _verbosity(args: list[str], anywhere: bool) -> list[str]:
    """Take -v / -vv / --verbose out of the arguments into OGUN_VERBOSE: every
    one before the command, and anywhere in a command's own arguments."""
    level, rest, leading = log.verbosity(), [], True
    for a in args:
        if a in _VERBOSE and (leading or anywhere):
            level += _VERBOSE[a]
            continue
        leading = False
        rest.append(a)
    if level:
        os.environ["OGUN_VERBOSE"] = str(min(level, 2))
    return rest


# each command here reads its own arguments, exactly as given: Click would eat a
# `--`, and `og allow -- cub x` must be refused, not read as `cub x`
_RAW_CMDS = {"help": help.help_, "ssh": help.ssh, "attach": session.attach, "project": project, "style": style, "skills": skills, "mcp": mcp.mcp, "give": give.give, "ship": ship.ship, "ports": health.ports, "doctor": health.doctor, "pass": secret.pass_, "token": token.token, "sh": sandboxes.sh, "stop": sandboxes.stop, "template": template.template, "tidy": tidy.tidy, "scan": scan.scan_cmd, "take": take.take, "net": netcmd.net, "allow": allow.allow, "policy": policy.policy, "ls": sandboxes.ls, "rm": remove.rm,
             "log": changes.show}
# the raw commands that draw their own help box
_USAGE = {"help": help.help_usage, "ssh": help.ssh_usage, "attach": session.attach_usage, "project": registry.usage, "style": style_usage, "skills": skills_usage, "doctor": health.doctor_usage, "policy": policy.policy_usage, "ls": sandboxes.ls_usage, "mcp": mcp.usage, "give": give.give_usage, "ship": ship.usage, "ports": health.ports_usage, "pass": secret.usage, "token": token.usage, "sh": sandboxes.sh_usage, "stop": sandboxes.stop_usage, "template": template.usage, "take": take.take_usage, "tidy": tidy.tidy_usage, "scan": scan.scan_usage, "net": allow.net_usage, "allow": allow.allow_usage, "rm": remove.rm_usage, "log": changes.usage}


# commands whose arguments after the first are another program's: help and -v
# there are that program's, so only a first argument asks og
_COMMAND_ARGS = {"sh"}


# where Homebrew puts sbx, op and the rest, lowest first: cron's bare PATH has
# neither, and the native /opt/homebrew ends up frontmost on a Mac that also
# carries the Intel prefix
BREW = ("/usr/local/bin", "/opt/homebrew/bin")


def with_brew(path: str, dirs: tuple[str, ...]) -> str:
    """PATH with each of dirs this Mac has put in front, unless it's on PATH already."""
    have = path.split(":") if path else []
    for d in dirs:
        if os.path.isdir(d) and d not in have:
            have.insert(0, d)
    return ":".join(have)


def main() -> None:
    os.environ["PATH"] = with_brew(os.environ.get("PATH", ""), BREW)
    try:
        _main()
    except settings.Unreadable as e:   # a setting misread would quietly be its default: stop instead
        log.err(f"og: {e}")
        sys.exit(1)


def _main() -> None:
    args = sys.argv[1:]
    # what the record names as the command: the line as typed
    log.COMMAND = shlex.join(["og", *args])
    head = _verbosity(args, anywhere=False)
    if head and head[0] in _RAW_CMDS:
        # og sh's words after the name are the command's, -v and --help among them
        rest = head[1:] if head[0] in _COMMAND_ARGS else _verbosity(head[1:], anywhere=True)
        asks = rest[:1] if head[0] in _COMMAND_ARGS else rest
        if ("--help" in asks or "-h" in asks) and head[0] != "help":
            _USAGE[head[0]](err=False)   # help is help, never a removal or a grant
            sys.exit(0)
        sys.exit(_RAW_CMDS[head[0]](rest))
    if head[:1] == ["internal"]:
        app(args=_verbosity(head, anywhere=True), prog_name="og")
    elif head[:1] in (["--help"], ["-h"]):
        help.page()
    else:
        sys.exit(bare.up(head))   # a bare og: create or attach (bare.py)
