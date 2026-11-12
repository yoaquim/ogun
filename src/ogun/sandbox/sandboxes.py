"""`og ls`: the sandboxes sbx knows, from `sbx ls`'s own table. One reader for the
plain list, `--json`, and the commands that ask whether a sandbox is there or
running (listed(), find(): og sh, og stop, og pass, og ports, og mcp; og rm
reads as_json() only)."""

import json
import re
import sys

from ogun.core import boxes, log, records, sbx

# the columns og shows; sbx names the first SANDBOX or NAME depending on its version
_KEEP = {"SANDBOX", "NAME", "AGENT", "STATUS"}


def parse(listing: str) -> tuple[list[str], list[list[str]]] | None:
    """`sbx ls`'s table as (headers, rows) of the columns og keeps, or None when
    it doesn't have two of them. Each cell is the slice under its header, from
    where that header starts to where the next one does: an empty AGENT cell
    would shift a whitespace split."""
    lines = listing.splitlines()
    if not lines:
        return None
    fields = [(m.start(), m.group()) for m in re.finditer(r"\S+", lines[0])]
    keep = [i for i, (_, h) in enumerate(fields) if h.upper() in _KEEP]
    if len(keep) < 2:
        return None

    def cell(line: str, i: int) -> str:
        end = fields[i + 1][0] if i + 1 < len(fields) else None
        c = line[fields[i][0]:end].strip(" \t")
        # a newer sbx marks its own status ("● running"): the state is the word,
        # which every reader compares ("stopped") and og marks in its own way
        return re.sub(r"^[^\w]+", "", c) if fields[i][1].upper() == "STATUS" else c

    return [fields[i][1] for i in keep], [[cell(line, i) for i in keep] for line in lines[1:] if line.strip()]


def as_json(listing: str) -> list[dict]:
    """[{sandbox, agent, status}]: the key is ours whatever sbx calls the
    column, and an empty cell stays empty, never the table's "-"."""
    t = parse(listing)
    if not t:
        return []
    keys = ["sandbox" if h.upper() == "NAME" else h.lower() for h in t[0]]
    out = []
    for row in t[1]:
        d = dict(zip(keys, row, strict=False))
        out.append({k: d.get(k, "") for k in ("sandbox", "agent", "status")})
    return out


class Listed(dict):
    """The sandboxes sbx lists, in its order, each name with its status as a
    word ("running", "stopped", "starting"); .text is the table itself, for
    what else a row holds (sbx.workspace)."""

    def __init__(self, text: str):
        super().__init__((s["sandbox"], s["status"].lower()) for s in as_json(text))
        self.text = text

    def running(self) -> list[str]:
        return [n for n, st in self.items() if st == "running"]


def listed() -> Listed | None:
    """What `sbx ls` lists; None when sbx didn't answer, which is never "no
    sandboxes"."""
    out = sbx.ls()
    return None if out is None else Listed(out)


def find(cmd: str, name: str, undone: str = "nothing was done") -> Listed | None:
    """listed(), when name is among them. Otherwise og <cmd>'s error, said, and
    None: sbx couldn't list (so <undone>), or there's no such sandbox."""
    sbs = listed()
    if sbs is None:
        log.err(f"og {cmd}: sbx couldn't list its sandboxes, so {undone}")
        return None
    if name not in sbs:
        _no_sandbox(cmd, name)
        return None
    return sbs


def protected() -> set[str]:
    """The sandboxes created with OpenAPPA (docs/appa.md)."""
    names = set()
    for f in records.records_dir().glob("*.json"):
        appa = (records.read_record(f.stem) or {}).get("appa")
        if isinstance(appa, dict) and appa.get("version") not in (None, False):
            names.add(f.stem)
    return names


LS_USAGE = "[--json | <sbx ls args>]"
LS_HELP = dict(
    about="Every sandbox on this Mac, with its agent and status.",
    forms=[("og ls", "a table: sandbox, agent, status (and PLUGINS when one has OpenAPPA)"),
           ("og ls --json", "the same, for scripts"),
           ("og ls <sbx ls args>", "sbx's own ls, as is")],
    examples=["og ls", "og ls --json"],
)


def ls_usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("ls", LS_USAGE, problem=problem, err=err, **LS_HELP)


def ls(args: list[str]) -> int:
    if "--json" in args:
        # --json is OUR shape of sbx's standard table, so an argument that changes
        # what sbx prints would be half-honoured, and silently
        if len(args) != 1:
            log.err("og ls: --json is this table in JSON; it takes no other sbx ls arguments")
            return 1
        p = sbx.run("ls")
        if p.returncode:   # a failed list must not read as "no sandboxes"
            log.err("og ls: sbx couldn't list its sandboxes:")
            sbx.said(p)
            return 1
        print(json.dumps(as_json(p.stdout), indent=2, ensure_ascii=False))
        return 0
    if args:
        return sbx.run("ls", *args, show=True).returncode
    p = sbx.run("ls")
    if p.returncode:
        log.err("og ls: sbx couldn't list its sandboxes:")
        sbx.said(p)
        return p.returncode
    t = parse(p.stdout)
    if not t:   # not the table og knows: sbx's own words, untouched
        print(p.stdout, end="")
        return 0
    headers, rows = t
    rows = [[c or "-" for c in r] for r in rows]
    prot = protected()
    if prot:
        headers.append("PLUGINS")
        rows = [[*r, "OpenAPPA" if r[0] in prot else ""] for r in rows]
    col = {h.upper(): i for i, h in enumerate(headers)}
    boxes.columns(headers, rows, state=col.get("STATUS"), title="ls",
                quiet=tuple(i for h, i in col.items() if h == "AGENT"), tags=tuple(i for h, i in col.items() if h == "PLUGINS"))
    return 0


SH_USAGE = "<name> [<command> [<arg>...]]"
SH_HELP = dict(
    about="A shell inside a sandbox, or one command run there.",
    forms=[
        ("og sh <name>", "a login shell inside the sandbox"),
        ("og sh <name> <command>…", "run that one command there, in a login shell's environment, and exit with its code"),
    ],
    notes=["Everything after the name is the command's, flags and all: og sh cub grep --help asks grep. "
           "Piped in or out, it runs without a terminal, so its output can be read or redirected."],
    examples=["og sh cub", "og sh cub git status", "og sh cub cat notes.md > notes.md"],
)
STOP_USAGE = "<name>... | --all"
STOP_HELP = dict(
    about="Stop sandboxes without removing them: their files and state stay, and attaching starts them again.",
    forms=[
        ("og stop <name>…", "stop these sandboxes"),
        ("og stop --all", "stop every running sandbox"),
    ],
    notes=["A session running inside one ends with it."],
    examples=["og stop cub", "og stop --all"],
)


def sh_usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("sh", SH_USAGE, problem=problem, err=err, **SH_HELP)


def stop_usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("stop", STOP_USAGE, problem=problem, err=err, **STOP_HELP)


def _no_sandbox(cmd: str, name: str) -> None:
    log.err(f"og {cmd}: no sandbox '{name}'; to see yours, run:", fix=log.cmd("og ls"))


def sh(args: list[str]) -> int:
    """A command runs in a login shell's environment (PATH and the env the
    sandbox's profile sets), its argv passed as is: no shell reads it twice. A terminal only when both ends
    are one, so `og sh cub cat f > f` gets the bytes, not a terminal's."""
    if not args or not args[0] or args[0].startswith("-"):
        sh_usage("og sh needs a sandbox name")
        return 1
    name, cmd = args[0], args[1:]
    if cmd[:1] == ["--"]:
        cmd = cmd[1:]
    if find("sh", name, "nothing was run") is None:
        return 1
    if not cmd:
        return sbx.run("exec", "-it", name, "bash", "-l", show=True).returncode
    tty = sys.stdin.isatty() and sys.stdout.isatty()
    return sbx.run("exec", "-i", *(["-t"] if tty else []), name, "bash", "-lc", 'exec "$@"', "_", *cmd, show=True).returncode


def stop(args: list[str]) -> int:
    """Every name checked before any is stopped, so a typo stops nothing; one
    already stopped is said, not stopped again."""
    if not args or (args != ["--all"] and any(a.startswith("-") for a in args)):
        bad = next((a for a in args if a.startswith("-")), "")
        stop_usage("og stop needs sandbox names, or --all" if not args else
                   "og stop: --all takes no names" if bad == "--all" else f"og stop has no option {bad}")
        return 1
    state = listed()
    if state is None:
        log.err("og stop: sbx couldn't list its sandboxes, so nothing was stopped")
        return 1
    # anything but stopped is up (running, or on its way)
    names = [n for n, st in state.items() if st != "stopped"] if args == ["--all"] else list(dict.fromkeys(args))
    for n in names:
        if n not in state:
            _no_sandbox("stop", n)
            return 1
    for n in [n for n in names if state.get(n) == "stopped"]:
        log.info(f"{n} is already stopped")
    todo = [n for n in names if state.get(n) != "stopped"]
    if not todo:
        if args == ["--all"]:
            log.info("no sandbox is running: nothing to stop")
        return 0
    p = sbx.run("stop", *todo, wait=f"stopping {', '.join(todo)}")
    if p.returncode != 0:
        log.err(f"og stop: sbx couldn't stop {', '.join(todo)}:")
        sbx.said(p)
        return 1
    log.ok(f"stopped {', '.join(todo)}", "attaching starts it again" if len(todo) == 1 else "attaching starts each again")
    log.record(f"stopped {', '.join(todo)}")
    return 0
