"""`og allow`: egress to a domain for one sandbox or every one, or a push to a GitHub repo;
--read-only for reading only. Also og net's usage, which og allow shares."""

from ogun.core import boxes, log, sbx
from ogun.net import pushrules, ruletable

ALLOW_USAGE = "<name> <domain>|github.com/<owner>/<repo>... [--read-only]  |  --all <domain>... [--read-only]"
ALLOW_HELP = dict(
    about="Let sandboxes reach more of the internet. Everything else stays blocked.",
    forms=[
        ("og allow <name> <domain>…", "these domains, for that sandbox only"),
        ("og allow <name> github.com/<owner>/<repo>", "a push to that repo, for that sandbox only"),
        ("og allow --all <domain>…", "these domains, for every sandbox"),
        ("… --read-only", "reading only (GET, HEAD): downloads work, uploads and posts don't"),
    ],
    notes=["Every sandbox reads GitHub already, so all of github.com is refused. "
           "A block rule wins over an allow; og allow says when one does."],
    examples=["og allow cub files.example.com --read-only",
              "og allow cub github.com/acme/widgets",
              "og allow --all docs.example.com --read-only"],
)


def allow_usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("allow", ALLOW_USAGE, problem=problem, err=err, **ALLOW_HELP)


_WHOLE_GITHUB = {"github.com", "github.com:443", "www.github.com", "https://github.com", "https://github.com/"}


def stray_arg(args: list[str]) -> str | None:
    """The first argument that reads as an option: a mistyped one (--chec) is
    never a domain, so it's refused before sbx is asked."""
    return next((a for a in args if a.startswith("-")), None)


def github_repo(a: str) -> str | None:
    """The owner/repo a github.com/<owner>/<repo> argument names, "" when it
    names none well; None when it isn't a repo (a domain)."""
    if not a.lower().startswith(("github.com/", "https://github.com/")):
        return None
    slug = a.removeprefix("https://").removeprefix("github.com/").removesuffix("/").removesuffix(".git")
    return slug if pushrules.SLUG.fullmatch(slug) else ""


def allow(argv: list[str], cmd: str = "allow", known: bool = False) -> int:
    """Egress for one sandbox, or every sandbox only when --all says so, so a
    bare `og allow <domain>` can't open a domain to the whole fleet. A GitHub
    repo is a push for that sandbox alone; all of github.com is refused, since
    every sandbox reads it already and a whole-host allow would undo the push
    limit. --read-only (anywhere in the line): GET and HEAD only. known: the
    sandbox is already checked (og net did)."""
    rdonly = "--read-only" in argv
    args = [a for a in argv if a != "--read-only"]
    usage = net_usage if cmd == "net" else allow_usage
    if len(args) < 2:
        usage(f"og {cmd} needs a sandbox (or --all) and at least one domain" if args
              else f"og {cmd} needs a sandbox name (or --all), then what to allow")
        return 1
    who, rest = args[0], args[1:]
    if stray := stray_arg(rest):
        usage(f"og {cmd} has no option {stray}")
        return 1
    sc = scope(cmd, who, known)
    named = None if sc is None else targets(cmd, who, sc, rest)
    if named is None:
        return 1
    hs, repos = named
    if rdonly and repos:
        log.err(f"og {cmd}: --read-only is for domains, not a repo push")
        return 1
    rc = pushes(cmd, who, repos)
    if hs and not hosts(cmd, sc, hs, rdonly):
        return 1
    return rc


def scope(cmd: str, who: str, known: bool) -> list[str] | None:
    """The sbx scope: one sandbox's (checked it's there, unless known), or every
    sandbox's for --all; None, said, when sbx doesn't list it or can't list."""
    if who == "--all":
        return []
    if not known:
        there = sbx.exists(who)
        if there is None:
            log.err(f"og {cmd}: sbx couldn't list its sandboxes, so nothing was allowed")
            return None
        if not there:
            log.err(f"og {cmd}: no sandbox '{who}' — name one, or --all for every sandbox; to see yours, run:", fix=log.cmd("og ls"))
            return None
    return ["--sandbox", who]


def targets(cmd: str, who: str, sc: list[str], rest: list[str]) -> tuple[list[str], list[str]] | None:
    """What's named, as (domains, repos to push to); None, said, for one that
    would reach too far: all of github.com, a pattern covering it, a repo named
    badly, or a push for every sandbox."""
    # a push is per sandbox: with --all, the fix names one
    one, them = ("<name>", "one sandbox") if who == "--all" else (who, who)
    hs, repos = [], []
    for a in rest:
        if a.lower() in _WHOLE_GITHUB:
            log.err(f"og {cmd}: not all of github.com — every sandbox reads it already; to let {them} push to a repo:",
                    fix=log.cmd(f"og allow {one} github.com/<owner>/<repo>"))
            return None
        if ruletable.covers_github(a):
            log.err(f"og {cmd}: {a} would also cover github.com, which would let {who if sc else 'every sandbox'} push to any of your repos — "
                    f"name the domains it needs; to let {them} push to a repo:",
                    fix=log.cmd(f"og allow {one} github.com/<owner>/<repo>"))
            return None
        slug = github_repo(a)
        if slug is None:
            hs.append(a)
            continue
        if not slug:
            log.err(f"og {cmd}: {a} — name a repo as github.com/<owner>/<repo>")
            return None
        if not sc:
            log.err(f"og {cmd}: a push is allowed per sandbox — name one, not --all; for every future sandbox of a repo:",
                    fix=log.cmd("og project add <address>"))
            return None
        repos.append(slug)
    return hs, repos


def pushes(cmd: str, who: str, repos: list[str]) -> int:
    """Each push allowed for the sandbox; 1 when one couldn't be, the rest still tried."""
    rc = 0
    for slug in repos:
        if pushrules.push_allow(who, slug):
            log.ok(f"{who} may push to github.com/{slug}", f"this sandbox only; for future sandboxes of this repo too: {log.cmd(f"og project add https://github.com/{slug}")}")
            log.record(f"{who} may push to github.com/{slug}")
        else:
            log.err(f"og {cmd}: could not allow the push to {slug}")
            rc = 1
    return rc


def hosts(cmd: str, sc: list[str], hs: list[str], rdonly: bool) -> bool:
    """The domains allowed as one rule, then a line for each a block or (read
    only) a whole-host allow still decides."""
    # no upload or post, though a GET's own address can still carry data (docs/network.md)
    how = ["--method", "GET,HEAD"] if rdonly else []
    sb = sc[1] if sc else ""
    if not ruletable.run_quiet(cmd, f"allowing {', '.join(hs)}", "policy", "allow", "network", *sc, ",".join(hs), *how):
        return False
    log.ok(f"{sb or 'every sandbox'} may reach {', '.join(hs)}{' (reading only)' if rdonly else ''}")
    log.record(f"{sb or 'every sandbox'} may reach {', '.join(hs)}{' (reading only)' if rdonly else ''}")
    ruletable.rule_notes("blocked", sb, hs)
    if rdonly:
        ruletable.rule_notes("full", sb, hs)
    return True


# ── og net: every network rule for a sandbox, in one command ──

NET_USAGE = "<name>|--all [--sbx | <domain>|github.com/<owner>/<repo>... [--read-only | --deny | --rm | --check]] | <name>|--all --log [-n <count>]"
NET_HELP = dict(
    about="What a sandbox may reach on the internet: list its rules, allow, block, or remove one.",
    forms=[
        ("og net <name>", "its rules: what it may reach or push to, and what's blocked"),
        ("og net <name> --sbx", "the same, with the rules sbx sets itself"),
        ("og net <name> <domain>…", "allow these, for that sandbox only (og allow does the same)"),
        ("og net <name> github.com/<owner>/<repo>", "allow a push to that repo, for that sandbox only"),
        ("… --read-only", "allow reading only (GET, HEAD): downloads work, uploads and posts don't"),
        ("… --deny", "block these; a block wins over any allow"),
        ("… --rm", "remove the rule you set for each, allow or block"),
        ("… --check", "would these be allowed? Yes or no, and how much (all, read, a push)"),
        ("og net <name> --log", "what it tried to reach, blocked and allowed, newest first"),
        ("og net --all …", "the same, for every sandbox"),
    ],
    notes=["Every sandbox reads GitHub already, so all of github.com is refused, to allow or block. "
           "--check says yes to a host allowed in any way; ACCESS says how much."],
    examples=["og net cub", "og net cub docs.example.com --read-only", "og net cub docs.example.com --rm",
              "og net --all tracker.example.com --deny", "og net cub --log", "og net cub example.com --check"],
)


def net_usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("net", NET_USAGE, problem=problem, err=err, **NET_HELP)
