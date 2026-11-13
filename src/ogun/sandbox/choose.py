"""What a create uses, from the repo's registry entry: its template (asked when the entry
names none and more than one is built), its runtime egress and its plugin marketplaces."""

import os
import re
from pathlib import Path

from ogun.core import config, log, paths, sbx
from ogun.sandbox import template


def _entry(d: str) -> tuple[str, dict]:
    """The repo's registry entry, by the folder's basename ({} when none)."""
    repo = os.path.basename(d.rstrip("/"))
    e = paths.registry_entry(repo)
    return repo, e if isinstance(e, dict) else {}


def skipped(msg: str) -> None:
    log.warn(f"  {log.WARNING} {msg}", err=True)


def template_project(d: str) -> str:
    """The template the repo's registry entry names, behind the gate every
    per-repo grant takes: the folder IS the repo, and the entry declares the
    path's owner. Each refusal said, on stderr."""
    repo, entry = _entry(d)
    t = entry.get("template")
    if t is None:
        return ""
    owner = paths.org_from_path(d)
    if not isinstance(t, str) or not template.NAME_RE.fullmatch(t):
        skipped(f"template: repo '{repo}' names an invalid template {t!r} (a-z, 0-9, -); skipped")
        return ""
    no = paths.refusal(d, entry)
    if no == "unplaced":
        skipped(f"template: repo '{repo}' asks for '{t}', but this directory is not the repo it describes "
              f"({paths.shown_repo(repo)}, or the entry's `path`); skipped")
    elif no == "ownerless":
        skipped(f"template: repo '{repo}' asks for '{t}' but declares no `owner`; skipped "
              f"(add \"owner\": \"{owner}\" to the entry to enable it)")
    elif no == "foreign":
        skipped(f"template: repo '{repo}' asks for '{t}' for owner '{entry.get('owner')}', but this sandbox's owner is "
              f"'{owner}'; skipped (basename collision across owners)")
    else:
        return t
    return ""


def choose_template(d: str) -> tuple[str, dict]:
    """The image a new sandbox starts from ("" for sbx's default) and the
    decision as the record keeps it: the repo's template, else this Mac's
    og profile, else the default. One not built, or with no recipe, is passed over
    with the command that builds it, never a failed create."""
    p = sbx.run("template", "ls", wait="reading sbx's templates")
    listing = p.stdout if p.returncode == 0 else ""
    cands = []
    want = template_project(d)
    if want:
        cands.append((want, f"the registry.json entry '{os.path.basename(d.rstrip('/'))}'", "project"))
    m = template.machine()
    if m and (not cands or cands[0][0] != m):
        cands.append((m, f"this Mac's profile '{m}'", "profile"))
    passed = []
    for i, (name, why, kind) in enumerate(cands):
        img = template.image(name)
        if template.built(img, listing):
            log.step(f"template {img}:latest ('{name}', from {why})", err=True)
            return f"{img}:latest", _decision(name, f"{img}:latest", kind, d, passed)
        nxt = f"trying '{cands[i + 1][0]}' ({cands[i + 1][1]})" if i + 1 < len(cands) else "using the sbx default"
        if (template.recipes_dir() / f"{name}.sh").is_file():
            # one line, as docs/templates.md shows it: the choice reads on, the build command in it
            skipped(f"template '{name}' ({why}) not built — run: og template {name}; {nxt}")
            passed.append({"name": name, "reason": kind, "why": "not built"})
        else:
            skipped(f"template '{name}' ({why}) has no recipe ({log.path(template.recipes_dir() / (name + '.sh'))}); {nxt}")
            passed.append({"name": name, "reason": kind, "why": "no recipe"})
    log.step("template: the sbx default image", err=True)
    return "", _decision("", "", "default", d, passed)


def _decision(name: str, image: str, reason: str, d: str, passed: list) -> dict:
    return {"name": name, "image": image, "reason": reason,
            "project": os.path.basename(d.rstrip("/")) if reason == "project" else "",
            "profile": config.label(), "passed": passed}


def runtime_egress(decision: dict) -> list[str]:
    """The chosen template's `# runtime-egress:` domains: what a sandbox made from
    it needs at runtime, read from the recipe as it is now. None for the sbx
    default, and none (warned) when a value isn't a domain: it reaches a command."""
    n = (decision or {}).get("name") or ""
    r = template.recipes_dir() / f"{n}.sh"
    if not (n and template.NAME_RE.fullmatch(n) and r.is_file()):
        return []
    out = template.header(r, "runtime-egress")
    for x in out:
        if not template.DOMAIN_RE.fullmatch(x):
            skipped(f"template '{n}' declares runtime egress '{log.shown(x)}' — not a domain; none allowed")
            return []
    return out


_MKT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,60}")


def marketplaces(d: str) -> list[str]:
    """The plugin marketplaces to mount read-only, a host path each: those this
    Mac's og profile asks for (marketplaces.json in og's config folder), and those the repo's
    entry asks for behind the owner gate. A clone that isn't there is skipped,
    said, never a failed create. Each as named: a link on its way is the create's to
    resolve (envfile.linked). Mounted, never baked in: a template never needs
    access to the plugin's repo. Its path in marketplaces.json is ~/-relative, so
    the file works under any home folder."""
    defs = (config.read_json("marketplaces.json") or {}).get("marketplaces", {})
    if not isinstance(defs, dict):
        return []
    machine = config.label()   # the profile's name as it is: a template's stricter rules are the template's own
    asked = {}
    for name, x in defs.items():
        if isinstance(x, dict) and machine in config.profiles_of(x):
            asked.setdefault(name, f"profile '{machine}'")
    repo, entry = _entry(d)
    want = entry.get("marketplaces")
    if want:
        owner, ent, no = paths.org_from_path(d), entry.get("owner"), paths.refusal(d, entry)
        if no == "unplaced":
            skipped(f"marketplaces: repo '{repo}' asks for {want}, but this directory is not the repo it describes; skipped")
        elif no == "ownerless":
            skipped(f"marketplaces: repo '{repo}' asks for {want} but declares no `owner`; skipped "
                  f"(add \"owner\": \"{owner}\" to the entry to enable it)")
        elif no == "foreign":
            skipped(f"marketplaces: repo '{repo}' asks for {want} for owner '{ent}', but this sandbox's owner is "
                  f"'{owner}'; skipped (basename collision across owners)")
        else:
            for n in want if isinstance(want, list) else []:
                asked.setdefault(n, f"registry entry '{repo}'")
    out = []
    for name, why in asked.items():
        x = defs.get(name) if isinstance(name, str) else None
        if not isinstance(x, dict) or not _MKT_RE.fullmatch(name):
            skipped(f"marketplace {name!r} ({why}): not defined in {log.path(config.file('marketplaces.json'))}; skipped")
            continue
        p = x.get("path")
        if not isinstance(p, str) or not p.startswith("~/") or any(c in ("", ".", "..") for c in p[2:].split("/")):
            skipped(f"marketplace '{name}': path must be ~/<dir> (no . or .. segments), got {p!r}; skipped")
            continue
        host = os.path.join(str(Path.home()), p[2:])
        if not os.path.isdir(host):   # a link is followed: mounted at its real path, the link made inside
            skipped(f"marketplace '{name}' ({why}): no clone at {p} — not mounted in this sandbox "
                  "(clone it there, then recreate)")
            continue
        out.append(host)
    return out
