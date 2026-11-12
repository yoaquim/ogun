"""`og mcp`: gateway MCP servers (docs/appendix/mcp-gateway.md). A gateway keeps
the credentials a server was loaded with: a login renewed on the Mac (`sbx mcp
auth`) reaches a running sandbox only when the server is loaded into it again.
`sbx mcp load` does that live, the session still running. So every attach logs
in again what needs it, then reloads (refresh(), which create and attach call)."""

import json
import os
import re
import sys

from ogun.core import boxes, config, log, paths, sbx
from ogun.sandbox import sandboxes

MCP_USAGE = "[ls [--json] | auth <server> | auth --all | load <name>]"
MCP_HELP = dict(
    about="MCP servers for your sandboxes: who's logged in, logging in again, loading them again.",
    forms=[
        ("og mcp [ls] [--json]", "every server: its login status, and who gets it"),
        ("og mcp auth <server>", "log in again, then load it again into the running sandboxes that use it"),
        ("og mcp auth --all", "the same, for every server in registry.json that has a login"),
        ("og mcp load <name>", "log in what needs it, then reload that sandbox's servers"),
    ],
    notes=["Every attach does load for its own sandbox. A server is registered once on the Mac: "
           "sbx mcp add <name> --url <its /mcp url>."],
    examples=["og mcp", "og mcp auth db-acme", "og mcp load cub"],
)

_NAME = re.compile(r"[A-Za-z0-9._-]+")


def usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("mcp", MCP_USAGE, problem=problem, err=err, **MCP_HELP)


def _registry() -> dict:
    return paths.read_registry() or {}


def _say(msg: str, err: bool = False) -> None:
    # one plain line: the attach and create around these print their own, and
    # tests and the person read the words as they are
    print(msg, file=sys.stderr if err else sys.stdout, flush=True)


def servers(d: str, quiet: bool = False) -> list[str]:
    """Servers for this directory's sandbox: the registry's top-level mcp list
    (machine-scoped entries only on those Macs), plus the repo's own list when
    the path names the entry's owner (repo names collide across owners).
    Unsafe names are skipped. quiet: say nothing about skips."""
    say = (lambda msg, err=False: None) if quiet else _say
    doc, machine = _registry(), config.label()
    names = []
    for g in doc.get("mcp") or []:
        if isinstance(g, dict):
            if machine and machine in config.profiles_of(g):
                names.append(g.get("name"))
        else:
            names.append(g)
    repo, owner = os.path.basename(d.rstrip("/")), paths.org_from_path(d)
    entry = (doc.get("repos") or {}).get(repo) or {}
    if isinstance(entry, dict) and entry.get("mcp"):
        no = paths.refusal(d, entry)
        if no == "unplaced":
            say(f"  ! mcp: {repo} lists servers, but its folder isn't under {paths.shown_repo('')}, so they're skipped", err=True)
        elif no == "ownerless":
            say(f"  ! mcp: {repo} lists servers but no owner, so they're skipped; add \"owner\": \"{owner}\" to its entry", err=True)
        elif no == "foreign":
            say(f"  ! mcp: {repo}'s servers are for {entry.get('owner')}, not {owner}, so they're skipped", err=True)
        else:
            names += list(entry["mcp"])
    out: list[str] = []
    for m in names:
        if not (isinstance(m, str) and _NAME.fullmatch(m)):
            say(f"  ! mcp: '{m}' isn't a server name (letters, digits, . _ - only), so it's skipped", err=True)
        elif m not in out:
            out.append(m)
    return out


def registry() -> dict[str, list[str]]:
    """Every server the registry gives sandboxes on THIS Mac, with who gets it
    ("every sandbox", or the repos). A registry may serve several Macs: a
    top-level entry scoped to other machines, or a repo not checked out here,
    is another Mac's, not listed."""
    doc, machine = _registry(), config.label()
    users: dict[str, set[str]] = {}

    def add(s, u):
        if isinstance(s, str) and _NAME.fullmatch(s):
            users.setdefault(s, set()).add(u)
    for g in doc.get("mcp") or []:
        if not isinstance(g, dict):
            add(g, "every sandbox")
        elif machine and machine in config.profiles_of(g):
            add(g.get("name"), "every sandbox")
    for r, e in (doc.get("repos") or {}).items():
        if not isinstance(e, dict) or not e.get("mcp"):
            continue
        if isinstance(e.get("path"), str):
            loc = os.path.expanduser(e["path"])
        elif isinstance(e.get("owner"), str):
            loc = os.path.join(paths.projects(), e["owner"], r)
        else:
            continue   # no owner: its servers are never given
        if os.path.isdir(loc):
            for s in e["mcp"]:
                add(s, r)
    return {s: sorted(users[s]) for s in sorted(users)}


def auth_status() -> dict[str, str] | None:
    """Every OAuth server sbx knows, with its login status (authorized,
    needs-refresh, …); None when sbx can't say, so a failed call is never read
    as "no logins"."""
    p = sbx.run("mcp", "auth", "status", "--all", "--json", wait="reading the MCP logins")
    if p.returncode != 0:
        return None
    try:
        d = json.loads(p.stdout)
    except ValueError:
        return None
    out = {}
    for x in d if isinstance(d, list) else []:
        n = x.get("server_name") if isinstance(x, dict) else None
        if isinstance(n, str) and _NAME.fullmatch(n):
            out[n] = re.sub(r"[^A-Za-z0-9._-]", "?", str(x.get("status") or "unknown"))
    return out


def _load(server: str, sb: str) -> bool:
    return sbx.run("mcp", "load", server, "--sandbox", sb, wait=f"loading {server} into {sb}").returncode == 0


def _login(server: str) -> bool:
    # sbx's own browser login, at this terminal
    return sbx.run("mcp", "auth", server, show=True).returncode == 0


def refresh(sb: str, d: str) -> int:
    """The sandbox's servers, each logged in again when its login isn't
    "authorized" (the browser, so only at a terminal), then loaded into the
    sandbox again. 1 when a login or a load failed: og mcp load reports it,
    attach and create carry on with the warning."""
    names = servers(d, quiet=True)
    if not names:
        return 0
    log.step("mcp servers")
    rc = 0
    st = auth_status()
    if st is None:   # the loads still run, but the login check didn't happen: say so
        _say("    ! couldn't check the MCP logins (og mcp shows them)")
        st, rc = {}, 1
    for m in names:
        s = st.get(m, "")
        if s and s != "authorized":
            if sys.stdin.isatty():
                _say(f"    {m}: {s} — logging in again (browser)")
                if not _login(m):
                    _say(f"    ! the login to {m} didn't finish; to try again, run: og mcp auth {m}")
                    rc = 1
            else:
                _say(f"    ! {m}: {s} — log in: og mcp auth {m}")
        if _load(m, sb):
            _say(f"    loaded {m}")
        else:
            _say(f"    ! couldn't load {m}; to see why, run: og mcp")
            rc = 1
    return rc


def reload_users(server: str) -> tuple[list[str], list[str]] | None:
    """Load it again into every running sandbox whose servers include it, after
    a new login: the sandboxes it was loaded into, and those it couldn't be;
    None when sbx couldn't list its sandboxes. _auth says which."""
    sbs = sandboxes.listed()
    if sbs is None:
        return None
    done, failed = [], []
    for n in sbs.running():
        ws = sbx.workspace(n, sbs.text)
        if not ws or server not in servers(ws, quiet=True):
            continue
        (done if _load(server, n) else failed).append(n)
    return done, failed


def mcp(argv: list[str]) -> int:
    sub, rest = (argv[0], argv[1:]) if argv else ("ls", [])
    if sub == "--json":
        sub, rest = "ls", ["--json", *rest]
    if sub == "ls":
        if rest not in ([], ["--json"]):
            usage("og mcp ls takes only --json")
            return 1
        return _ls(bool(rest))
    if sub == "auth":
        if len(rest) != 1 or not rest[0]:
            usage("og mcp auth takes one server, or --all")
            return 1
        return _auth(rest[0])
    if sub == "load":
        if len(rest) != 1 or not rest[0]:
            usage("og mcp load takes one sandbox name")
            return 1
        return _load_one(rest[0])
    usage(f"og mcp has no subcommand {sub}")
    return 1


def _ls(as_json: bool) -> int:
    reg = registry()
    # a failed read is not an empty one: every server would read as logged out
    st = auth_status()
    if st is None:
        log.err("og mcp: sbx couldn't say which servers are logged in")
        return 1
    p = sbx.run("mcp", "ls", wait="reading the MCP registrations")
    if p.returncode != 0:
        log.err("og mcp: sbx couldn't list its MCP servers")
        return 1
    known = [f[0] for f in (line.split() for line in p.stdout.splitlines()[1:]) if f]
    # registry servers first, then ones sbx has that no repo names: its OAuth
    # logins and its registrations (header-secret, local)
    order = list(reg) + [m for m in dict.fromkeys([*st, *known]) if m not in reg and _NAME.fullmatch(m)]
    rows = []
    for m in order:
        s = st.get(m) or ("registered" if m in known else "not-registered")
        rows.append((m, s, reg.get(m, [])))
    if as_json:
        print(json.dumps([{"server": m, "status": s, "used_by": u} for m, s, u in rows], indent=2))
        return 0
    if not rows:
        log.info("no MCP servers: none registered, none in registry.json")
        return 0
    # what to do about each row that isn't fine (og mcp auth takes registry
    # servers only: one no repo names goes to sbx)
    foot = []
    for m, s, u in rows:
        if s == "not-registered":
            foot.append(f"register once: {log.cmd(f'sbx mcp add {m} --url <its /mcp url>')}")
        elif s not in ("authorized", "registered"):
            foot.append(f"log in again: {log.cmd(f'{"og" if u else "sbx"} mcp auth {m}')}")
    boxes.columns(["SERVER", "STATUS", "USED BY"], [[m, s, ",".join(u) or "-"] for m, s, u in rows],
                title="mcp", quiet=(2,), foot="\n".join(foot))
    return 0


def _auth(which: str) -> int:
    reg = registry()
    # OAuth servers only: sbx mcp auth has nothing to do for a header-secret or
    # local one, and they're the ones its status lists
    st = auth_status()
    if st is None:
        log.err("og mcp: sbx couldn't say which servers have a login, so nothing was done")
        return 1
    if which == "--all":
        pick = [m for m in reg if m in st]
    elif which not in reg:
        log.err(f"og mcp: '{which}' isn't in registry.json; to log in to it anyway, run:", fix=log.cmd(f"sbx mcp auth {which}"))
        return 1
    elif which in st:
        pick = [which]
    else:
        log.err(f"og mcp: '{which}' has no OAuth login sbx knows of, so there's nothing to log in to; og mcp shows its status")
        return 1
    if not pick:
        log.info("no server in registry.json has a login: nothing to do")
        return 0
    rc = 0
    for m in pick:
        if len(pick) > 1:   # a step a server, so each one's lines sit under its name
            log.step(f"{m}: logging in (browser)")
        if not _login(m):
            log.err(f"og mcp: the login to {m} didn't finish; to try again, run:", fix=log.cmd(f"og mcp auth {m}"))
            rc = 1
            continue
        users = reload_users(m)
        if users is None:   # logged in all the same: that much is done, and recorded
            log.ok(f"logged in to {m}")
            log.record(f"logged in to {m}")
            log.err(f"og mcp: sbx couldn't list its sandboxes, so {m} wasn't loaded again into any; for each, run:",
                    fix=log.cmd("og mcp load <name>"))
            rc = 1
            continue
        done, failed = users
        log.ok(f"logged in to {m}", f"reloaded into {', '.join(done)}" if done else "" if failed else "no running sandbox uses it")
        log.record(f"logged in to {m}" + (f", reloaded into {', '.join(done)}" if done else ""))
        for n in failed:
            log.err(f"og mcp: couldn't load {m} again into {n}; to try again, run:", fix=log.cmd(f"og mcp load {n}"))
            rc = 1
    return rc


def _load_one(name: str) -> int:
    sbs = sandboxes.find("mcp", name)
    if sbs is None:
        return 1
    # sbx mcp load attaches to a RUNNING sandbox; attaching starts it, and reloads
    if sbs[name] != "running":
        log.err(f"og mcp: {name} isn't running; attaching starts it and loads its servers again:", fix=log.cmd(f"og {name}"))
        return 1
    ws = sbx.workspace(name, sbs.text)
    if not ws:
        log.err(f"og mcp: can't tell which folder {name} works in, so not which servers it gets")
        return 1
    if not servers(ws, quiet=True):
        log.info(f"'{name}' gets no MCP servers (registry.json)")
        return 0
    return refresh(name, ws)

