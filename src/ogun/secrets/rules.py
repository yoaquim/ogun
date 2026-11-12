"""The secret-grant rules: which grant is valid and which a sandbox gets
(docs/secrets.md#secret-grants).

A grant is {env, hosts, item, field?}. Top-level `secrets` grants also carry
`profiles` and reach every sandbox on those Macs; a repo's `secrets` reach only
that repo's sandboxes, behind the gate every per-repo grant takes (the entry
declares `owner`, it matches the path's, and the directory IS the repo). The
sandbox holds a placeholder; the proxy swaps in the value only on `hosts`.

og calls it (approval.py). It decides who gets what, so a change here deserves
a secrets review."""

from __future__ import annotations

import json
import re
import sys

ENV_RE = re.compile(r"[A-Z_][A-Z0-9_]{0,63}")
NAME_RE = re.compile(r"[A-Za-z0-9._-]{1,128}")
LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
HOST_RE = re.compile(rf"{LABEL}(?:\.{LABEL})+")
GITHUB_RE = re.compile(r"(?:.*\.)?(?:github\.com|githubusercontent\.com)")
# gh and git read these as a GitHub credential: a placeholder there is never
# what the caller meant, and the GitHub identity only ever comes from ogun
GITHUB_ENVS = {"GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"}


def stderr(msg):
    print(f"  ! secrets: {msg}", file=sys.stderr)


def load(path):
    with open(path) as f:
        d = json.load(f)
    if not isinstance(d, dict):
        raise ValueError("not an object")
    return d


def check(g, where, warn=stderr):
    """The grant as (env, hosts, item, field), or None with the reason warned."""
    if not isinstance(g, dict):
        warn(f"{where}: a grant must be an object — skipped")
        return None
    env, item, field = g.get("env"), g.get("item"), g.get("field", "credential")
    hosts = g.get("hosts")
    if not (isinstance(env, str) and ENV_RE.fullmatch(env) and isinstance(item, str) and NAME_RE.fullmatch(item)
            and isinstance(field, str) and NAME_RE.fullmatch(field) and isinstance(hosts, list)
            and all(isinstance(h, str) for h in hosts)):
        warn(f"{where}: a malformed grant (env A-Z0-9_, item and field plain names, hosts a list) — skipped")
        return None
    if env in GITHUB_ENVS:
        warn(f"{where}: {env} is what gh and git read as a GitHub credential — refused")
        return None
    if not hosts:
        warn(f"{where}: {env} names no host — refused (the proxy swaps a value in only on named hosts)")
        return None
    out = []
    for h in hosts:
        hl = h.strip().lower()
        if GITHUB_RE.fullmatch(hl):
            warn(f"{where}: {env} names a GitHub host ({h}) — refused (one GitHub identity per sandbox)")
            return None
        if not HOST_RE.fullmatch(hl):
            warn(f"{where}: {env}: '{h}' is not an exact host name — refused (no wildcards)")
            return None
        out.append(hl)
    return env, ",".join(sorted(set(out))), item, field


def resolve(path, repo, owner, placed, machine, warn=stderr, where=None):
    """The grants one sandbox gets, a line each: scope TAB env TAB hosts TAB item
    TAB field. The scope is `owner/repo` for a repo's grant and `*@machine` for a
    top-level one, so an approval of the line holds for that owner or Mac only.
    placed: the directory is the repo its entry describes; where: the folders it
    would be in, as a refusal names them. Refusals and skips are warned."""
    try:
        d = load(path)
    except (OSError, ValueError) as e:
        warn(f"{path} doesn't parse ({e}) — no grants")
        return []
    picked = []   # (scope, grant)
    top = d.get("secrets", [])
    for i, g in enumerate(top if isinstance(top, list) else []):
        ms = g.get("profiles") if isinstance(g, dict) else None
        if not (machine and isinstance(ms, list) and machine in ms):
            continue   # the machine rule fails closed: no profile, nothing
        c = check(g, f"top-level grant #{i + 1}", warn)
        if c:
            picked.append((f"*@{machine}", c))
    entry = d.get("repos", {}).get(repo) if isinstance(d.get("repos"), dict) else None
    rs = entry.get("secrets") if isinstance(entry, dict) else None
    if rs:
        ent = entry.get("owner")
        if not placed:
            where = where or f"a project folder's <owner>/{repo}"
            warn(f"repo '{repo}' grants secrets, but this directory is not the repo it describes "
                 f"({where}, or the entry's `path`) — skipped")
        elif not ent:
            warn(f"repo '{repo}' grants secrets but declares no `owner` — skipped")
        elif ent != owner:
            warn(f"repo '{repo}' grants secrets for owner '{ent}', but this sandbox's owner is '{owner}' — skipped "
                 f"(basename collision across owners)")
        else:
            for i, g in enumerate(rs if isinstance(rs, list) else []):
                c = check(g, f"repo '{repo}' grant #{i + 1}", warn)
                if c:
                    picked.append((f"{owner}/{repo}", c))
    by_env = {}
    for scope, c in picked:
        by_env.setdefault(c[0], []).append((scope, c))
    lines = []
    for env, rows in by_env.items():
        if len({c for _, c in rows}) > 1:
            warn(f"{env} is granted twice, differently ({', '.join('top-level' if s.startswith('*@') else s for s, _ in rows)}) — "
                 f"refused, none applied")
            continue
        scope, c = rows[0]
        lines.append("\t".join((scope, *c)))
    return lines
