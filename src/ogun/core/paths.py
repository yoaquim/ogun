"""Where things are: the checkout this code runs from, the registry it
reads, ~/Projects, and who owns a directory.

The owner rules go by physical paths only: a symlink
~/Projects/personal/x -> ~/Projects/acme/x is acme's, or a work sandbox
would get the personal token. They pick a sandbox's GitHub token owner
(github.py), so a change here deserves a secrets review."""

import os
import re
from pathlib import Path

from ogun.core import config, log, settings

OGUN = Path(__file__).resolve().parents[3]   # og's own folder: the repo's root
SCRIPTS = OGUN / "sandbox-scripts"   # what og sends into a sandbox, found beside og, never through a mount


def state_dir() -> Path:
    """og's own state on this Mac: create records, token records, approvals, the
    record of changes. $XDG_STATE_HOME/ogun, else ~/.local/state/ogun."""
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "ogun"


def registry_file() -> Path:
    return config.file("registry.json")


def read_registry() -> dict | None:
    """The registry, parsed: the one place it's read. None when it's missing;
    one that isn't a JSON object stops og (config.read_json)."""
    return config.read_json("registry.json")


def registry_entry(name: str):
    """The registry's entry for a repo name, as written (the caller checks its
    shape); {} when there is none or nothing readable to look in."""
    repos = (read_registry() or {}).get("repos")
    return repos.get(name, {}) if isinstance(repos, dict) else {}


def roots() -> list[tuple[str, str | None]]:
    """The folders projects live in (projects), colon-separated like PATH:
    a folder alone is per-owner (<folder>/<owner>/<repo>), folder=owner is
    fixed-owner (<folder>/<repo>, every repo that owner's). Unset: ~/Projects,
    per-owner. A list og can't read stops og: a misread folder would hand a
    repo another owner's token."""
    v = settings.get("projects")
    if not v:
        return [(str(Path.home() / "Projects"), None)]
    out = []
    for part in v.split(":"):
        folder, eq, owner = part.rpartition("=") if "=" in part else (part, "", "")
        if not folder:
            raise settings.Unreadable(f"projects ({v}) names an empty folder; folders go colon-separated, "
                                      "a fixed owner as folder=owner")
        f = os.path.expanduser(folder)
        if not os.path.isabs(f):
            raise settings.Unreadable(f"projects: {folder} isn't a full path (/… or ~/…)")
        if eq and not _OWNER_RE.fullmatch(owner):
            raise settings.Unreadable(f"projects: '{owner}' in {part} isn't an owner (a GitHub owner's name)")
        out.append((f, owner if eq else None))
    # one folder inside another would make two rules answer for the same folders (a
    # repo in the inner one, the inner one where an outer repo would be, inside one):
    # never which wins, refused. Compared physically, so a link can't hide it
    real_of = [(os.path.realpath(f), f) for f, _ in out]
    for i, (a, fa) in enumerate(real_of):
        for b, fb in real_of[i + 1:]:
            if a == b or b.startswith(a + os.sep) or a.startswith(b + os.sep):
                inner, outer = (fa, fb) if len(a) >= len(b) else (fb, fa)
                how = f"{fa} and {fb} are the same folder" if a == b else f"{inner} is inside {outer}"
                raise settings.Unreadable(f"projects: {how}; project folders can't nest, "
                                          "so one rule names each folder's owner")
    return out


def projects() -> str:
    """The projects folder a command that makes or finds <owner>/<repo> uses: the
    first per-owner one, else ~/Projects."""
    return next((f for f, owner in roots() if owner is None), str(Path.home() / "Projects"))


def shown_projects() -> str:
    """The project folders og reads, as a message names them: ~/Projects unset."""
    try:
        return " or ".join(log.path(f) for f, _ in roots())
    except settings.Unreadable:
        return "a project folder (projects)"


def shown_repo(repo: str = "<repo>") -> str:
    """Where a repo's folder goes, as a message names it: <folder>/<owner>/<repo> in
    a per-owner folder, <folder>/<repo> in a fixed-owner one."""
    try:
        return " or ".join(log.path(f) + ("/<owner>" if owner is None else "") + f"/{repo}" for f, owner in roots())
    except settings.Unreadable:
        return f"a project folder's <owner>/{repo} (projects)"


def real(p: str) -> str:
    return os.path.realpath(p)


def _in_root(d: str) -> tuple[str, bool] | None:
    """(owner, placed) from the project folder holding d, compared physically
    (folders never nest: roots). A per-owner folder names the owner of
    <owner>/<repo> and below, placed only at <owner>/<repo>; a fixed-owner one
    names its owner for <repo> alone. None: no folder names d's owner."""
    r = real(d)
    for folder, owner in roots():
        root = real(folder)
        if not r.startswith(root + os.sep):
            continue
        rel = r[len(root) + 1:]
        if owner is None:
            return (rel.split("/", 1)[0], rel.count("/") == 1) if "/" in rel else None
        return (owner, True) if "/" not in rel else None
    return None


_OWNER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,60}")


def path_owner(d: str) -> str | None:
    """The owner a registry entry declares for exactly this directory (`path`),
    for a repo outside every project folder. Only an entry with an owner, keyed
    by the path's basename, whose path lies outside them all."""
    if not os.path.isdir(d):
        return None
    r = real(d)
    repos = (read_registry() or {}).get("repos", {})
    folders = [real(f) for f, _ in roots()]
    for key, e in repos.items() if isinstance(repos, dict) else ():
        p, owner = (e.get("path"), e.get("owner")) if isinstance(e, dict) else (None, None)
        if not isinstance(p, str) or not isinstance(owner, str) or not _OWNER_RE.fullmatch(owner):
            continue
        if p.startswith("~/"):
            p = os.path.join(str(Path.home()), p[2:])
        if not os.path.isabs(p):
            continue
        rp = real(p)
        if any(rp == root or rp.startswith(root + os.sep) for root in folders):
            continue
        if rp == r and os.path.basename(rp) == key:
            return owner
    return None


def org_from_path(d: str) -> str:
    """The project folder holding it names the token owner (roots); a repo the
    registry places by exact path, its declared owner; anything else, personal."""
    got = _in_root(d)
    if got:
        return got[0]
    return path_owner(d) or "personal"


def org_explicit(d: str) -> bool:
    """Did the path itself name the owner? False where "personal" is a guess."""
    return _in_root(d) is not None or path_owner(d) is not None


def placed(d: str) -> bool:
    """Is this directory exactly the repo a registry entry describes:
    a repo right in a project folder (roots), or a path an entry declares? A
    same-named folder elsewhere, or inside another checkout, gets none of the
    entry's capabilities (mounts, MCP, the token override)."""
    if not os.path.isdir(d):
        return False
    got = _in_root(d)
    if got and got[1]:
        return True
    return path_owner(d) is not None


def refusal(d: str, entry: dict) -> str:
    """The gate every per-repo capability takes: "" when d is exactly the repo the
    entry describes and the entry declares d's owner; otherwise why not:
    "unplaced" (d isn't that repo), "ownerless" (the entry names no owner) or
    "foreign" (it names another). Each caller says it in its own words."""
    if not placed(d):
        return "unplaced"
    owner = entry.get("owner") if isinstance(entry, dict) else None
    if not owner:
        return "ownerless"
    return "" if owner == org_from_path(d) else "foreign"
