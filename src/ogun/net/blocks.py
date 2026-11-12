"""`og net --log` and `--check`: what sbx blocked, and whether a host would be let through."""

import datetime
import fnmatch
import json
import re

from ogun.core import boxes, log, sbx
from ogun.core.log import shown
from ogun.net import allow, ruletable

_DEFAULT_DENY = "No matching allow rule (default deny)"


def _why(reason: str) -> str:
    """sbx's reason for a block, as og says it."""
    return "no rule allows it" if reason == _DEFAULT_DENY else shown(reason)


def _what(rule: str) -> tuple[str, str]:
    """The request that was blocked, from sbx's rule text: an HTTP method and
    path when the host was allowed but not that request (a POST to a read-only
    host), else ("all", "")."""
    m = re.search(r"action=http:request:(\w+)", rule or "")
    if not m:
        return "all", ""
    path = re.search(r"http:path:([^\],]*)", rule)
    return m.group(1).upper(), shown(path.group(1)) if path else ""


def _host(h: str) -> str:
    return shown(h.removesuffix(":443"))


def _instant(iso) -> float:
    """A time sbx gives, as a moment: its offset applied, so an entry from
    either side of a clock change sorts where it happened. Unreadable: oldest."""
    try:
        return datetime.datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return float("-inf")


def _seen(iso: str) -> str:
    """When, short enough for --log's table: month, day and time, no year."""
    try:
        return log.when(datetime.datetime.fromisoformat(iso).timestamp())[5:]
    except (TypeError, ValueError):
        return "?"


def show_log(who: str, args: list[str]) -> int:
    """og net <name>|--all --log [-n <count>]: what the sandbox tried to reach, a row a host
    (the table format): blocked first, then allowed, each newest first; how
    often, when last. A column takes no long text, so beneath: a block that
    blocked one request only (a POST to a read-only host), its method and
    path; any reason that isn't the default deny; how to allow one."""
    n = 20
    if args[:1] == ["-n"] and len(args) == 2 and args[1].isdigit():
        n = int(args[1])
    elif args:
        allow.net_usage("og net --log takes only -n <count> (0 for all)")
        return 1
    every = who == "--all"
    them = "every sandbox" if every else who
    p = sbx.run("policy", "log", *([] if every else [who]), "--json", wait=f"reading what {them} tried to reach")
    try:
        d = json.loads(p.stdout) if p.returncode == 0 else None
    except ValueError:
        d = None
    if not isinstance(d, dict):
        log.err(f"og net: sbx couldn't say what {them} tried to reach — try again")
        return 1
    rows, foot, hidden, blocked = [], [], False, False
    for key in ("blocked", "allowed"):
        got = [e for e in d.get(key) or [] if isinstance(e, dict)]
        got.sort(key=lambda e: _instant(e.get("last_seen")), reverse=True)
        hidden |= bool(n) and len(got) > n
        for e in got[:n] if n else got:
            host = _host(str(e.get("host", "?")))
            sb = shown(str(e.get("sandbox_id", "?")))
            on = f"{sb}: {host}" if every else host   # a note names its sandbox, as its row does
            req, path = _what(str(e.get("rule", ""))) if key == "blocked" else ("all", "")
            reason = str(e.get("reason", ""))
            if req != "all":
                foot.append(f"{on}: only {req} {path}".rstrip() + " was blocked")
            if key == "blocked" and reason and reason != _DEFAULT_DENY:
                foot.append(f"{on}: {_why(reason)}")
            blocked |= key == "blocked"
            rows.append(([sb] if every else [])
                        + [host, key, str(e.get("count", "?")), _seen(e.get("last_seen"))])
    if hidden:
        foot.append(f"the newest {n} of each; all of them: {log.cmd(f'og net {who} --log -n 0')}")
    if blocked and not every:   # which one is yours to judge: a block is often right (telemetry, a POST)
        foot.append(f"to allow one: {log.cmd(f'og allow {who} <host> --read-only')}")
    boxes.columns((["SANDBOX"] if every else []) + ["HOST", "STATE", "TIMES", "LAST SEEN"], rows,
                state=1 + every, title=f"net {who} --log", quiet=(2 + every, 3 + every), foot="\n".join(foot))
    return 0


_CLONE_PATH = re.compile(r"/[^/]+/[^/]+/git-upload-pack")


def _partly(who: str, host: str, rules: list[dict]) -> str:
    """What a host with only http rules lets through, from the allow rules that
    cover it, short: `read` (GET, HEAD, or GitHub's clone POST), `push to
    <owner>/<repo>` for a repo's push rules, else the method and path. "" when
    no rule covers it, or sbx couldn't list them: no proof any request passes."""
    scopes = {"all"} | ({f"sandbox:{who}"} if who != "--all" else set())
    read, pushes, other = False, [], []
    for r in rules:
        if not (r["type"] == "http" and r["decision"] == "allow" and r["scope"] in scopes
                and any(fnmatch.fnmatch(host, res.removesuffix("/**").removesuffix(":443")) for res in r["res"])):
            continue
        ms = {m for m in r["method"].upper().split(",") if m and m != "-"}
        pth = r["path"] if r["path"] not in ("", "-") else "/**"
        push = ruletable.PUSH_PATH.fullmatch(pth)
        if (pth == "/**" and ms <= {"GET", "HEAD"}) or (_CLONE_PATH.fullmatch(pth) and ms <= {"POST"}):
            read = True
        elif push and ms <= {"POST"}:
            pushes.append(push.group(1))
        else:
            other.append((pth, f"{','.join(sorted(ms))} {shown(pth)}"))
    pushes = sorted(set(pushes))
    # a repo's LFS rule goes with its push
    other = [o for pth, o in other if not any(pth.startswith((f"/{s}.git/info/lfs/", f"/{s}/info/lfs/")) for s in pushes)]
    parts = (["read"] if read else []) + ([f"push to {', '.join(pushes)}"] if pushes else []) + other
    return " · ".join(parts)


def check_hosts(who: str, targets: list[str]) -> int:
    """og net <name>|--all <domain>… --check: sbx's answer for each, a row each
    (the table format): the host, yes or no, and what of it: all, read, push to
    a repo. sbx exits 1 for a no, so its answer is read whatever its exit.
    Allowed for some requests only (a host with only http rules: sbx says
    authorization_required) is a yes, with what its rules give. Beneath, how to
    open what's blocked. Exit 0 when every one is allowed, 3 when one isn't (an
    answer, not a failure), 1 when sbx couldn't say."""
    scope = [] if who == "--all" else ["--sandbox", who]
    rows, unruled, ruled = [], [], []
    rules = None   # read once, only when a host needs it
    for t in targets:
        p = sbx.run("policy", "check", "network", *scope, "--json", t, wait=f"asking sbx about {t}")
        try:
            d = json.loads(p.stdout) if p.returncode in (0, 1) else None
        except ValueError:
            d = None
        if not isinstance(d, dict) or not isinstance(d.get("allowed"), bool):
            if rows:   # the answers sbx did give, before the one it couldn't
                boxes.columns(["HOST", "ALLOWED", "ACCESS"], rows, title=f"net {who} --check")
            log.err(f"og net: sbx couldn't say whether {shown(t)} is allowed")
            return 1
        host = _host(str(d.get("target") or t))
        part = "all" if d["allowed"] else ""
        if not d["allowed"] and d.get("deny_kind") == "authorization_required":
            if rules is None:
                rules = ruletable.read_rules() or []
            part = _partly(who, host, rules)
        if part:   # only with a rule that lets some request through: the proof of an allow
            rows.append([host, "yes", part])
            continue
        rows.append([host, "no", "none"])
        if d.get("deny_kind") == "implicit" or d.get("reason") == _DEFAULT_DENY:
            unruled.append(host)
        else:
            ruled.append(host)
    foot = []
    if unruled:
        foot.append(f"to allow {'it' if len(unruled) == 1 else 'one'}: "
                    + log.cmd(f"og allow {who} {unruled[0] if len(unruled) == 1 else '<host>'} --read-only"))
    if ruled:
        foot.append(f"{', '.join(ruled)}: blocked by a rule; to see it: {log.cmd(f'og net {who}')}")
    boxes.columns(["HOST", "ALLOWED", "ACCESS"], rows, title=f"net {who} --check", foot="\n".join(foot))
    return 3 if unruled or ruled else 0
