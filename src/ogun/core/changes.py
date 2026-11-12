"""`og log`: the record of what og changed on this Mac (log.record writes it):
removals, allows, policy runs, registry grants. Newest last,
as a terminal scrolls."""

import json
import time

from ogun.core import boxes, log

LOG_USAGE = "[-n <count>] [--json]"
LOG_HELP = dict(
    about="What og changed on this Mac, newest last: removals, allows, policy, the registry.",
    forms=[
        ("og log", "the last 20 changes, each with the command that made it"),
        ("og log -n <count>", "the last <count>; 0 for all of them"),
        ("og log --json", "the same, as JSON, for scripts"),
    ],
    notes=["Only what og itself changed: a change made with sbx directly isn't here."],
    examples=["og log", "og log -n 100"],
)


def usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("log", LOG_USAGE, problem=problem, err=err, **LOG_HELP)


def entries() -> list[dict]:
    """Every change recorded, oldest first, the rotated file before the live one; a
    line that isn't a record (a cut-off write) is skipped, never fatal."""
    out = []
    f = log.record_file()
    for p in (f.with_name(f.name + ".1"), f):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and isinstance(e.get("what"), str):
                out.append({"t": str(e.get("t", "")), "cmd": str(e.get("cmd", "")), "what": e["what"]})
    return out


def _day(d: str) -> str:
    try:
        return time.strftime("%a %d %b %Y", time.strptime(d, "%Y-%m-%d"))
    except ValueError:
        return d or "?"


def show(args: list[str]) -> int:
    n, as_json, rest = 20, False, list(args)
    while rest:
        a = rest.pop(0)
        if a == "--json":
            as_json = True
        elif a == "-n" and rest and rest[0].isdigit():
            n = int(rest.pop(0))
        elif a == "-n":
            usage("og log -n needs a count: a number, 0 for all")
            return 1
        else:
            usage(f"og log has no option {a}" if a.startswith("-") else "og log takes no names")
            return 1
    es = entries()
    es = es[-n:] if n else es
    if as_json:
        print(json.dumps(es, indent=2, ensure_ascii=False))
        return 0
    if not es:
        log.info(f"nothing recorded yet ({log.path(log.record_file())})")
        return 0
    if not log.pretty():   # piped: one whole line each, date and all, for a grep
        for e in es:
            print(f"{e['t'].replace('T', ' ')}  {e['what']}" + (f"  ({e['cmd']})" if e["cmd"] else ""))
        return 0
    day = None
    for e in es:   # classic: each change as og said it, with the time it happened
        d, _, clock = e["t"].partition("T")
        if d != day:
            log.section(_day(d))
            day = d
        log.info(e["what"], clock=clock or "--:--:--")   # a replay: what happened, plain
        if e["cmd"]:
            log.aside(e["cmd"])
    return 0
