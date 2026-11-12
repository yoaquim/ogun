"""The repo registry from the terminal: `og project ls` and `og project add`.

The registry (registry.json in og's config folder) is never a file in the
worked-on repo: a hijacked repo must not be able to widen what its own
sandbox can read. A grant names a real checkout of the same owner, or a GitHub
address this repo's sandboxes may push to (docs/sandboxes.md)."""

import os
import re
import subprocess
import sys
from pathlib import Path

from ogun.core import boxes, files, log, paths

PROJECT_USAGE = "ls [--json] | add [<repo>] [--write]"
PROJECT_HELP = dict(
    about="The repo registry: what mounts into this repo's sandboxes, and where they may push.",
    forms=[("og project ls", "every entry, with the repos it grants"),
           ("og project ls --json", "the same, as JSON"),
           ("og project add <repo>", "mount that repo, read-only, into this repo's sandboxes (none: pick from a list)"),
           ("… --write", "its token may also push there; the mount stays read-only"),
           ("og project add https://github.com/<owner>/<repo>", "let this repo's sandboxes push there")],
    notes=["<repo>: <name>, <owner>/<name>, or its folder's path. A mount reaches its sandboxes when they're recreated; a push grant at their next attach."],
    examples=["og project ls", "og project add planner", "og project add https://github.com/acme/widgets"],
)


def usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("project", PROJECT_USAGE, problem=problem, err=err, **PROJECT_HELP)


class Refused(Exception):
    """A grant og will not record; the message says why."""


def entries(d: dict) -> list[dict]:
    """Every entry with its grants, as `og project ls --json` prints them."""
    out = []
    for name, e in (d.get("repos") or {}).items():
        r = e.get("repos") or {}
        out.append({
            "repo": name,
            "owner": e.get("owner"),
            "github": e.get("github"),
            "mcp": e.get("mcp") or [],
            "read": r.get("read") or [],
            "write": r.get("write") or [],
            "push": r.get("push") or [],
        })
    return sorted(out, key=lambda x: x["repo"])


def ls_lines(d: dict) -> list[str]:
    lines = []
    for e in entries(d):
        extras = [f"{k}: " + ", ".join(e[k]) for k in ("read", "write", "push") if e[k]]
        lines.append(e["repo"] + ("  [" + "; ".join(extras) + "]" if extras else ""))
    return lines


_PUSH_RE = re.compile(r"https://github\.com/([A-Za-z0-9-]+/[A-Za-z0-9._-]+)/?")
_GIT_SUFFIX = ".git"


def push_url(target: str) -> str:
    """https://github.com/<owner>/<repo>, without .git or a trailing slash."""
    m = _PUSH_RE.fullmatch(target)
    if not m:
        raise Refused(f"{target} — a push grant is a GitHub repo's address, https://github.com/<owner>/<repo>")
    rid = m.group(1)
    if rid.endswith(_GIT_SUFFIX):
        rid = rid[: -len(_GIT_SUFFIX)]
    return f"https://github.com/{rid}"


def receiver() -> tuple[str, str, str]:
    """(repo root, its owner, its entry name): the repo standing here gets the grant.
    The ROOT, since a subdirectory's basename names no repo."""
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        raise Refused("not inside a git repo — run from the repo that should read the other") from None
    d = paths.real(top)
    if not paths.org_explicit(d):
        raise Refused(f"{d} does not name an owner ({paths.shown_repo()}) — grants need one")
    return d, paths.org_from_path(d), os.path.basename(d)


def pick(org: str, entry: str, mode: str) -> str:
    """A menu of this owner's other checkouts, `select`-style: the list on stderr,
    a number read from stdin. End of input picks nothing."""
    base = Path(paths.projects()) / org
    names = sorted(
        p.name for p in (base.iterdir() if base.is_dir() else [])
        if p.is_dir() and p.name != entry and (p / ".git").exists()
    )
    if not names:
        raise Refused(f"no other checkouts under {log.path(base)}")
    sys.stderr.write(f"mount which {org} repo into {entry}'s sandboxes ({mode})?\n")
    menu = "".join(f"{i}) {n}\n" for i, n in enumerate(names, 1))
    sys.stderr.write(menu)
    while True:
        sys.stderr.write("repo #: ")
        sys.stderr.flush()
        line = sys.stdin.readline()
        if not line:
            sys.stderr.write("\n")
            raise SystemExit(1)
        line = line.strip()
        if not line:
            sys.stderr.write(menu)
        elif line.isdigit() and 1 <= int(line) <= len(names):
            return names[int(line) - 1]


def grant_id(target: str, org: str, entry: str, mode: str) -> tuple[str, str]:
    """(the grant, its list) for a target: a GitHub address goes in `push`; a
    repo, named <name>, <owner>/<name> or by its folder's path, in `read` or `write`."""
    if target.startswith("https://"):
        return push_url(target), "push"
    t = target[:-1] if target.endswith("/") else target
    if t.startswith("~"):
        t = str(Path.home()) + t[1:]
    if t.startswith("/"):
        if not os.path.isdir(t):
            raise Refused(f"{target}: no such directory")
        t = paths.real(t)
        proot = paths.real(paths.projects())
        rel = t[len(proot) + 1:] if t.startswith(proot + os.sep) else ""
        if "/" not in rel:
            raise Refused(f"{target} isn't under {log.path(paths.projects())}/<owner>/<repo> — only a checkout there can be added")
        t = rel
    towner = org
    if not t:
        tname = pick(org, entry, mode)
    elif "/" in t:
        if not re.fullmatch(r"[^/]+/[^/]+", t):
            raise Refused(f"{target}: name a repo as <name>, <owner>/<name>, or its folder's path")
        towner, tname = t.split("/")
    else:
        tname = t
    if tname in (".", ".."):
        raise Refused(f"{target} is not a repo name")
    if towner != org:
        raise Refused(f"{towner}/{tname} belongs to {towner}, this repo to {org} — a repo can only read its own owner's repos")
    rid = f"{towner}/{tname}"
    if rid == f"{org}/{entry}":
        raise Refused(f"{rid} is this repo — nothing to grant")
    checkout = os.path.join(paths.projects(), rid)
    if not os.path.exists(os.path.join(checkout, ".git")):
        raise Refused(f"{log.path(checkout)} is not a git checkout — grants name real checkouts")
    # a symlinked name must stay inside the owner tree, or the mount would skip
    # the grant forever
    rreal, rown = paths.real(checkout), paths.real(os.path.join(paths.projects(), towner))
    if not rreal.startswith(rown + os.sep):
        raise Refused(f"{log.path(checkout)} resolves to {log.path(rreal)}, outside {log.path(rown)} — mounts never leave the owner tree")
    return rid, mode


def record(entry: str, org: str, rid: str, mode: str) -> bool:
    """Add the grant to this repo's entry, seeding one for a repo the registry
    hasn't seen; False when it was already there. A grant lives in exactly one
    of read and write."""
    f = paths.registry_file().resolve()   # through a link: the file it points at, never the link replaced
    d = paths.read_registry()
    if d is None:
        raise Refused(f"{f.name} can't be read as a JSON object — fix it first")
    repos = d.setdefault("repos", {})
    e = repos.get(entry)
    if e is None:
        e = repos[entry] = {"owner": org}
        log.info(f"new entry '{entry}' in {f.name}, owner {org}")
    own = e.get("owner")
    if own is None:
        # basenames collide across owners; an ownerless entry can't prove it is this repo's
        raise Refused(f"entry '{entry}' declares no owner — set \"owner\": \"{org}\" on it in {f.name} first")
    if own != org:
        raise Refused(f"'{entry}' in {f.name} is {own}'s repo, but this checkout is {org}'s — two owners have a repo named {entry}")
    r = e.setdefault("repos", {"read": [], "write": []})
    if rid in (r.get(mode) or []):
        log.info(f"{entry} already has {rid}: nothing to change")
        return False
    r.setdefault(mode, []).append(rid)
    other = {"read": "write", "write": "read"}.get(mode)
    if other and rid in (r.get(other) or []):
        r[other].remove(rid)
    files.write_json(f, d, ascii=False, newline=True)
    log.file("wrote", f)
    log.record(f"registry: {entry} gets {rid} ({mode})")
    log.ok({"read": f"{entry} now reads {rid}", "push": f"{entry} may push to {rid}",
            "write": f"{entry} reads {rid} and may push to it"}[mode])
    return True


def add(target: str, write: bool) -> None:
    mode = "write" if write else "read"
    if target.startswith("https://"):
        push_url(target)   # a bad address is refused before anything else is asked
    d, org, entry = receiver()
    rid, mode = grant_id(target, org, entry, mode)
    if mode != "push" and paths.real(os.path.join(paths.projects(), rid)) == d:
        raise Refused(f"{rid} resolves to this repo — nothing to grant")
    if not record(entry, org, rid, mode):
        return
    # a push rule is set on every attach; a mount only when a sandbox is created
    when = {"push": "get it at their next attach", "read": "get the mount when recreated",
            "write": "may push at their next attach and get the mount when recreated"}[mode]
    log.info(f"next: {entry}'s sandboxes {when} (the change is in {log.path(paths.registry_file().resolve())})")


_PUSH_LIST_RE = re.compile(r"https://github\.com/([A-Za-z0-9-]+/[A-Za-z0-9._-]+?)(\.git)?/?")


def related(d: str, mode: str = "", quiet: bool = False) -> list[str]:
    """What this repo's registry entry grants a sandbox for it, a line each.
    "" — checkouts to mount READ-ONLY: `repos.read` plus `repos.write` (both
    mount read-only: `write` only says its token may push there; a writable
    mount of a live host checkout would let a hijacked sandbox stage code you
    would later commit as your own). "write": that list alone. "push": the
    `push` list's GitHub addresses, never mounted. Only the placed repo whose
    entry declares its owner gets the grants. Skips are said on stderr (quiet:
    not)."""
    got = entry_grants(d, mode, quiet)
    if got is None:
        return []
    name, org, owner, lists = got
    if mode == "push":
        return push_list(name, owner, lists, quiet)
    return mounts(name, org, lists, mode, quiet)


def _skip(msg: str, quiet: bool) -> None:
    if not quiet:
        log.warn(f"  {log.WARNING} {msg}", err=True)


def entry_grants(d: str, mode: str, quiet: bool) -> tuple[str, str, str | None, dict] | None:
    """The entry's name, the checkout's owner, the entry's own owner and its
    `repos` lists, when the entry is an object and this is the repo it
    describes, for its owner; None, a skip said (but for the push list: the
    mounts' own call says why), when it isn't."""
    if not d:
        return None
    name = os.path.basename(d.rstrip("/")) or d
    org = paths.org_from_path(d)
    entry = paths.registry_entry(name)
    if not isinstance(entry, dict) or not isinstance(entry.get("repos") or {}, dict):
        if mode != "push":
            _skip(f"entry '{name}' is not an object with a `repos` object — its grants are skipped", quiet)
        return None
    no = paths.refusal(d, entry)
    if entry.get("repos") and no == "unplaced":
        if mode != "push":
            _skip(f"entry '{name}' has grants, but this directory is not the repo it describes "
                  f"({paths.shown_repo(name)}, or the entry's `path`) — its grants are skipped", quiet)
        return None
    ent_owner = entry.get("owner")
    if entry.get("repos") and no == "foreign":   # an entry without an owner still mounts: only a mismatch is refused
        if mode != "push":
            _skip(f"entry '{name}' is {ent_owner}'s repo, but this sandbox's owner is {org} — its grants are skipped "
                  f"(two owners have a repo named {name})", quiet)
        return None
    return name, org, ent_owner, entry.get("repos") or {}


def push_list(name: str, owner: str | None, lists: dict, quiet: bool) -> list[str]:
    """The `push` list's GitHub addresses, without .git; none for an entry that
    declares no owner."""
    if not owner:
        if lists.get("push"):
            _skip(f"entry '{name}' declares no owner — its push list is skipped", quiet)
        return []
    out = []
    for u in lists.get("push") or []:
        m = _PUSH_LIST_RE.fullmatch(u) if isinstance(u, str) else None
        if m:
            out.append("https://github.com/" + m.group(1))
        else:
            _skip(f"'{name}' may push to '{u}', which isn't a GitHub repo's address (https://github.com/<owner>/<repo>) — skipped", quiet)
    return out


def mounts(name: str, org: str, lists: dict, mode: str, quiet: bool) -> list[str]:
    """The checkouts to mount read-only, each the real path of the owner's own
    <owner>/<repo>: `read` plus `write`, or `write` alone for mode "write"."""
    reads = list(lists.get("read") or [])
    wanted = reads + [r for r in (lists.get("write") or []) if r not in reads]
    if mode == "write":
        wanted = list(lists.get("write") or [])
    root = paths.projects()
    out = []
    for r in wanted:
        # component-wise: a repo NAMED foo..bar is legal; a ".." path segment is not
        parts = r.split("/") if isinstance(r, str) else []
        if len(parts) != 2 or any(p in ("", ".", "..") for p in parts):
            _skip(f"'{name}' reads '{r}', which isn't <owner>/<repo> (a folder under {log.path(root)}) — skipped", quiet)
            continue
        if parts[0] != org:
            _skip(f"'{name}' reads '{r}', which belongs to another owner ({org} here) — skipped", quiet)
            continue
        p = os.path.join(root, r)
        if not os.path.isdir(p):
            _skip(f"'{name}' reads '{r}', which isn't checked out at {log.path(p)} — skipped", quiet)
            continue
        # a symlink named like an owner's checkout but pointing elsewhere must
        # not widen the mount: the real path stays under the owner's real folder
        real, owner_dir = os.path.realpath(p), os.path.realpath(os.path.join(root, org))
        if not real.startswith(owner_dir + os.sep):
            _skip(f"'{name}' reads '{r}', which resolves to {log.path(real)}, outside {log.path(owner_dir)} — skipped", quiet)
            continue
        out.append(real)
    return out


_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
# an exact host, or every subdomain of one (*.example.com), as template runtime egress takes
_EGRESS_HOST_RE = re.compile(rf"(?:\*\.)?{_LABEL}(?:\.{_LABEL})+")


def egress(d: str, quiet: bool = False) -> list[dict]:
    """The domains this repo's sandboxes may reach, from its entry's `egress`
    list: each grant {hosts, write?, for?}, returned a host each as {host,
    write, for, scope}. Read-only (GET and HEAD) unless `write` is true. Behind
    the gate every per-repo grant takes: the entry declares `owner`, it matches
    the path's, and the directory IS the repo. GitHub is refused: its reads are
    the baseline's and its pushes are `og project add`'s. Skips are said on
    stderr (quiet: not)."""
    def skip(msg: str) -> None:
        if not quiet:
            log.warn(f"  {log.WARNING} {msg}", err=True)

    if not d:
        return []
    name = os.path.basename(d.rstrip("/")) or d
    entry = paths.registry_entry(name)
    grants = entry.get("egress") if isinstance(entry, dict) else None
    if not grants:
        return []
    owner, org, no = entry.get("owner"), paths.org_from_path(d), paths.refusal(d, entry)
    if no == "unplaced":
        skip(f"entry '{name}' lists domains, but this directory is not the repo it describes "
             f"({paths.shown_repo(name)}, or the entry's `path`) — none allowed")
        return []
    if no == "ownerless":
        skip(f"entry '{name}' lists domains but no `owner` — none allowed")
        return []
    if no == "foreign":
        skip(f"entry '{name}' is for owner '{owner}', but this sandbox's owner is '{org}' — none of its domains allowed "
             f"(two owners have a repo named {name})")
        return []
    from ogun.net import ruletable  # net reads the registry: imported here, not at the top
    out: dict[str, dict] = {}
    for i, g in enumerate(grants if isinstance(grants, list) else [grants]):
        where = f"'{name}' egress #{i + 1}"
        hosts, write, why = (g.get("hosts"), g.get("write", False), g.get("for", "")) if isinstance(g, dict) else (None, None, None)
        if not (isinstance(hosts, list) and hosts and all(isinstance(h, str) for h in hosts)
                and isinstance(write, bool) and isinstance(why, str)):
            skip(f"{where}: each is {{hosts: [domains], write: true|false, for: \"why\"}} — skipped")
            continue
        for h in hosts:
            hl = h.strip().lower()
            if ruletable.covers_github(hl):
                skip(f"{where}: '{h}' covers github.com, which every sandbox already reads — skipped (to push to a repo: og project add)")
            elif not _EGRESS_HOST_RE.fullmatch(hl):
                skip(f"{where}: '{h}' is not a domain (example.com, or *.example.com) — skipped")
            else:
                # a host granted twice: write wins, so read-only never narrows a write grant
                was = out.get(hl)
                out[hl] = {"host": hl, "write": write or bool(was and was["write"]), "for": why or (was or {}).get("for", ""),
                           "scope": f"{owner}/{name}"}
    return list(out.values())
