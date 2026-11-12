"""sbx's network rules as og reads and changes them: the rule table (`sbx policy ls
--wide`), what a rule covers and narrows, removing one, and sbx calls whose failure is said."""

import fnmatch
import re
import shlex
import subprocess

from ogun.core import log, sbx
from ogun.core.log import shown


def sbx_said(p: subprocess.CompletedProcess) -> None:
    """The last lines sbx printed, as notes under og's own line about its failure."""
    for line in sbx.tail(p):
        log.note(shown(line.strip()), err=True)


def run_quiet(cmd: str, what: str, *args: str) -> bool:
    """Run `sbx <args>` with og's own line in place of sbx's; a failure is og's
    error, with what sbx said under it."""
    p = sbx.run(*args, wait=what)
    if p.returncode == 0:
        return True
    log.err(f"og {cmd}: {what} failed (exit {p.returncode})")
    sbx_said(p)
    return False


def _failed(p: subprocess.CompletedProcess, what: str) -> None:
    log.warn(f"  {log.WARNING} {what} failed (exit {p.returncode})", err=True)
    sbx_said(p)


def allow_twice(*args: str) -> bool:
    """One rule, tried again once if sbx refuses it (a daemon mid-restart), the
    second failure shown."""
    p = sbx.run(*args)
    if p.returncode:
        p = sbx.run(*args)
    if p.returncode:
        _failed(p, "sbx " + " ".join(args))
    return p.returncode == 0


# ── sbx's rule table ──

def read_rules() -> list[dict] | None:
    """Every network rule sbx lists (`policy ls --wide`): of type network (a host)
    or http (a host limited to a method and a path: a read-only allow, a push),
    with its id, scope (all or sandbox:<name>), how it came (default, kit,
    added, approval), decision, method, path and resources; None when sbx didn't
    answer. A rule is a row; its further resources are indented lines under it."""
    p = sbx.run("policy", "ls", "--wide")
    if p.returncode != 0:
        return None
    out: list[dict] = []
    for line in (p.stdout or "").splitlines():
        f = line.split()
        if line[:1].islower() and len(f) >= 13:
            out.append({"scope": f[2], "via": f[1], "id": f[-7], "type": f[-6], "method": f[-5], "path": f[-4],
                        "decision": f[-3], "res": [f[-1]]} if f[-6] in ("network", "http") else None)
        elif out and out[-1] and f and line[:1] == " ":
            out[-1]["res"].append(f[-1])
    return [r for r in out if r]


def rm_cmd(who: str, res: str) -> str:
    """The og net --rm line that removes a rule, for a message."""
    return log.cmd(f"og net {who} {shlex.quote(res)} --rm")


def _covers(host: str, res: str) -> bool:
    h = host.lower()
    return fnmatch.fnmatchcase(h, res.lower()) or fnmatch.fnmatchcase(h, res.removesuffix(":443"))


def rule_notes(kind: str, sb: str, hosts: list[str]) -> None:
    """After `og allow`, one line for each host an existing rule undercuts.
    blocked: a block (for every sandbox, or this one) also covers it, and a block
    wins over an allow. full: a --read-only allow, but the same scope already
    allows the whole host. Says how to fix it; removes nothing."""
    rows = [(r["scope"], res) for r in read_rules() or []
            if (r["decision"] == "deny" if kind == "blocked" else r["type"] == "network" and r["decision"] == "allow")
            for res in r["res"]]
    for h in hosts:
        for scope, res in rows:
            if kind == "blocked":
                if not (scope == "all" or (sb and scope == f"sandbox:{sb}")):
                    continue
            elif not ((sb and scope == f"sandbox:{sb}") or (not sb and scope == "all")):
                continue
            if not _covers(h, res):
                continue
            rm = rm_cmd("--all" if scope == "all" else sb, res)
            if kind == "blocked":
                log.warn(f"  {log.WARNING} {h} is also blocked, and a block wins over an allow — to unblock it:", err=True, fix=rm)
            else:
                log.warn(f"  {log.WARNING} {h} is also allowed for everything{f' for {sb}' if sb else ''}, so reading only has no effect — to leave only reading:",
                         err=True, fix=f"{rm}, then {log.cmd(f'og net {sb or "--all"} {shlex.quote(h)} --read-only')}")


# ── og allow ──

def covers_github(pattern: str) -> bool:
    """Would an allow for this domain pattern let traffic to github.com through?
    The scheme, a trailing slash and a port aside, it is matched as sbx matches a
    rule's resource: `*github.com`, `*.com`, `git*` and `**` all cover it. A
    whole-host github.com allow undoes the push limit (a POST to any repo's
    git-receive-pack), so no pattern may cover it."""
    d = re.sub(r"^[a-z]+://", "", pattern.strip().lower()).removesuffix("/")
    d = re.sub(r":\d+$", "", d)
    return any(fnmatch.fnmatchcase(h, d) for h in ("github.com", "www.github.com"))


PUSH_PATH = re.compile(r"/([A-Za-z0-9-]+/[A-Za-z0-9._-]+?)(?:\.git)?/git-receive-pack")


def is_github(res: str) -> bool:
    return res.lower().removesuffix(":443") == "github.com"


def has_value(v: str) -> bool:
    return v not in ("-", "")


def narrows(path: str) -> bool:
    """A path that narrows a rule: sbx writes /** for the whole site."""
    return has_value(path) and path != "/**"


def push_of(r: dict) -> str | None:
    """The repo a rule grants a push to, or None: an ALLOW on a receive-pack path
    (a block on one is a block, never a push)."""
    m = PUSH_PATH.fullmatch(r["path"]) if r["decision"] == "allow" else None
    return m.group(1) if m else None


def rm_rule(cmd: str, r: dict, keep: list[str]) -> bool:
    """Remove one rule by its id, with no y/N: typing og net … --rm is the
    decision. A rule can hold several hosts (og allow a.com b.com is one rule):
    keep names those that stay, set again as they were."""
    # a sandbox's own rule is found by its id only with that sandbox named
    scope = [] if r["scope"] == "all" else ["--sandbox", r["scope"].removeprefix("sandbox:")]
    if not run_quiet(cmd, f"removing rule {r['id'][:8]}", "policy", "rm", "network", "--id", r["id"], *scope, "--force"):
        return False
    if keep:
        how = ["--method", r["method"]] if has_value(r["method"]) else []
        how += ["--path", r["path"]] if narrows(r["path"]) else []
        verb = "deny" if r["decision"] == "deny" else "allow"
        if not run_quiet(cmd, f"adding back {', '.join(keep)}", "policy", verb, "network", *scope, ",".join(keep), *how):
            # set again as they were: a block stays a block, reading only stays reading only
            again = " --deny" if verb == "deny" else " --read-only" if set(r["method"].split(",")) <= {"GET", "HEAD"} and has_value(r["method"]) else ""
            log.err(f"og {cmd}: {', '.join(keep)} shared that rule and weren't added back — set them again:",
                    fix=log.cmd(f"og net {r['scope'].removeprefix('sandbox:') if r['scope'] != 'all' else '--all'} {' '.join(keep)}{again}"))
            return False
    return True
