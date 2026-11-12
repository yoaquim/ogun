"""`og net`: a sandbox's network rules, listed, allowed, blocked (--deny) or removed (--rm)."""


from ogun.core import boxes, log, sbx
from ogun.net import allow, blocks, ruletable


def _listing(who: str, own_too: bool = False) -> int:
    """`og net <name>`: the rules that apply to it, one row each (the table
    format): what, how, and whether for it alone or every sandbox. A repo's two
    push rules are one row. A push and a block are marked, as needing a look;
    the rules every sandbox shares are at rest, so its own stand out. own_too
    (--sbx): sbx's own rules as well, marked."""
    rules = ruletable.read_rules()
    if rules is None:
        log.err("og net: sbx policy ls failed — no rules to show")
        return 1
    scopes = {"all"} if who == "--all" else {"all", f"sandbox:{who}"}
    rows, seen, hidden = [], set(), 0
    for r in rules:
        if r["scope"] not in scopes:
            continue
        push = ruletable.push_of(r)
        for res in r["res"]:
            # a rule limited to a path shows it, and to a method says which: the
            # baseline's clone rule must never read like the whole-host allow
            # og policy warns about
            what = res.removesuffix(":443") + (r["path"] if ruletable.narrows(r["path"]) else "")
            only = f" ({r['method']})" if ruletable.has_value(r["method"]) else ""
            if push:
                what, how = f"github.com/{push}", "push"
            elif r["decision"] == "deny":
                how = "blocked" + only
            elif ruletable.has_value(r["method"]) and set(r["method"].split(",")) <= {"GET", "HEAD"}:
                how = "read-only"
            else:
                how = "allowed" + only
            key = (what, how, r["scope"])
            if key in seen:
                continue
            seen.add(key)
            # sbx's own rules (its defaults, and what it gives every sandbox for
            # Claude) are many and never yours to change: counted, shown with --sbx
            own = r["via"] in ("default", "provisioned")
            if own and not own_too:
                hidden += 1
                continue
            rows.append([what, how, "every sandbox" if r["scope"] == "all" else "this sandbox"]
                        + (["sbx's own" if own else ""] if own_too else []))
    order = {"push": 0, "allowed": 1, "read-only": 2, "blocked": 3}
    rows.sort(key=lambda x: (x[2] != "this sandbox", order.get(x[1].split(" (")[0], 9), x[0]))
    boxes.columns(["RULE", "HOW", "FOR"] + (["SOURCE"] if own_too else []), rows, state=1, title=f"net {who}" + (" --sbx" if own_too else ""),
                quiet=(2, 3), marks={"allowed": ("", ""), "read-only": ("", "")},
                rest=lambda r: r[2] == "every sandbox" and who != "--all",
                foot=f"and {hidden} of sbx's own rules: {log.cmd(f'og net {who} --sbx')}" if hidden else "")
    return 0


def _deny(scope: list[str], who: str, hosts: list[str]) -> int:
    if not ruletable.run_quiet("net", f"blocking {', '.join(hosts)}", "policy", "deny", "network", *scope, ",".join(hosts)):
        return 1
    log.ok(f"{who if scope else 'every sandbox'} may not reach {', '.join(hosts)}")
    log.record(f"{who if scope else 'every sandbox'} may not reach {', '.join(hosts)}")
    return 0


def _remove(scope: list[str], who: str, hosts: list[str], repos: list[str]) -> int:
    """--rm: remove the rules set for each domain (allow, read-only or block)
    and each repo's push, by their ids: only those, every other rule as it was."""
    rules = ruletable.read_rules()
    if rules is None:
        log.err("og net: sbx policy ls failed — nothing removed")
        return 1
    want = "all" if not scope else f"sandbox:{who}"
    where = who if scope else "every sandbox"
    rc = 0
    # a rule can hold several of the hosts named (og allow cub a.com b.com is one
    # rule): each rule goes once, keeping only the hosts not named here
    named = {x.lower().removesuffix(":443") for x in hosts}
    done: dict[str, bool] = {}
    for h in hosts:
        hn = h.lower().removesuffix(":443")
        # the host's own rules: over the whole site, never one narrowed to a path
        # (removing github.com leaves the pushes, the clone rule, LFS)
        mine = [r for r in rules if r["scope"] == want and not ruletable.narrows(r["path"])
                and any(x.lower().removesuffix(":443") == hn for x in r["res"])]
        if not mine:
            log.err(f"og net: no rule for {h} on {where} to remove — to see them:", fix=log.cmd(f"og net {who}"))
            rc = 1
            continue
        ok = True
        for r in mine:
            if r["id"] not in done:
                done[r["id"]] = ruletable.rm_rule("net", r, [x for x in r["res"] if x.lower().removesuffix(":443") not in named])
            ok = done[r["id"]] and ok
        if ok:
            log.ok(f"removed the rule for {h} from {where}")
            log.record(f"removed the rule for {h} from {where}")
        rc |= not ok
    for slug in repos:
        mine = [r for r in rules if r["scope"] == want and ruletable.push_of(r) == slug]
        if not mine:
            log.err(f"og net: no push to github.com/{slug} on {who} to remove — to see them:", fix=log.cmd(f"og net {who}"))
            rc = 1
            continue
        ok = all([ruletable.rm_rule("net", r, [x for x in r["res"] if not ruletable.is_github(x)]) for r in mine])  # noqa: C419 every rule is removed, even after one fails
        if ok:
            log.ok(f"removed {who}'s push to github.com/{slug}")
            log.record(f"removed {who}'s push to github.com/{slug}")
        rc |= not ok
    return rc


def net(argv: list[str]) -> int:
    """`og net`: list a sandbox's rules, or allow (the default), block or remove
    domains and repo pushes, for one sandbox or --all."""
    flags = {a for a in argv if a in ("--read-only", "--deny", "--rm", "--check", "--log", "--sbx")}
    args = [a for a in argv if a not in flags]
    if not args:
        allow.net_usage("og net needs a sandbox name (or --all)")
        return 1
    if len(flags) > 1:
        allow.net_usage(f"og net takes one of --read-only, --deny, --rm, --check, --log and --sbx, not {' and '.join(sorted(flags))}")
        return 1
    who, targets = args[0], args[1:]
    if not listed(who):
        return 1
    if "--log" in flags:
        return blocks.show_log(who, targets)
    if "--sbx" in flags:
        if targets:
            allow.net_usage("--sbx goes with og net <name> alone")
            return 1
        return _listing(who, own_too=True)
    if stray := allow.stray_arg(targets):
        allow.net_usage(f"og net has no option {stray}")
        return 1
    if "--check" in flags:
        if not targets:
            allow.net_usage("--check goes with the domains to check")
            return 1
        return blocks.check_hosts(who, targets)
    if not targets:
        if flags:
            allow.net_usage(f"{next(iter(flags))} goes with the domains it's for")
            return 1
        return _listing(who)
    if not flags or flags == {"--read-only"}:
        return allow.allow(argv, cmd="net", known=True)   # allowing is og allow's, refusals and notes included
    got = named(who, "--deny" in flags, targets)
    if got is None:
        return 1
    hosts, repos = got
    scope = [] if who == "--all" else ["--sandbox", who]
    if "--deny" in flags:
        return _deny(scope, who, hosts)
    return _remove(scope, who, hosts, repos)


def listed(who: str) -> bool:
    """--all, or a sandbox sbx lists; said when it isn't, or sbx can't list."""
    if who == "--all":
        return True
    listing = sbx.ls()
    if listing is None:   # a failed list is no answer, never "no such sandbox"
        log.err("og net: sbx couldn't list its sandboxes, so nothing was done")
        return False
    if who not in [line.split()[0] for line in listing.splitlines()[1:] if line.split()]:
        log.err(f"og net: no sandbox '{who}' — name one, or --all for every sandbox; to see yours, run:", fix=log.cmd("og ls"))
        return False
    return True


def named(who: str, deny: bool, targets: list[str]) -> tuple[list[str], list[str]] | None:
    """What's named to block (deny) or remove, as (domains, repo pushes); None,
    said, for a block over github.com, a repo named badly, a push blocked, or a
    push for every sandbox."""
    hosts, repos = [], []
    for a in targets:
        # removing a rule over all of github.com is what og policy asks for; only
        # blocking one is refused (allowing one is og allow's, which refuses it too)
        if ruletable.covers_github(a) and deny:
            log.err(f"og net: blocking {a} would block github.com too, which every sandbox reads from — name narrower domains")
            return None
        slug = allow.github_repo(a)
        if slug is None:
            hosts.append(a)
            continue
        if not slug:
            log.err(f"og net: {a} — name a repo as github.com/<owner>/<repo>")
            return None
        if deny:
            log.err("og net: a repo push can't be blocked, only removed:",
                    fix=log.cmd(f"og net {who if who != '--all' else '<name>'} github.com/{slug} --rm"))
            return None
        if who == "--all":
            log.err("og net: a push is per sandbox — name it:", fix=log.cmd(f"og net <name> github.com/{slug} --rm"))
            return None
        repos.append(slug)
    return hosts, repos
