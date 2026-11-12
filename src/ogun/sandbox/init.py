"""A workspace that isn't a repo yet: refused when it's too broad (home, ~/Projects), else
a git init offered before the create, with a first commit so the sandbox has a branch."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from ogun.core import log, paths


def real_path(p) -> str:
    return os.path.realpath(p)


def run_git(d: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", d, *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)


# ── a workspace that isn't a repo yet ──

def too_broad(d: str, tl: str = "") -> str:
    """Why d holds more than one project or credentials, or "": / or home or above,
    a project folder or a folder holding one, anything of the file exchange, an
    owner's folder in a per-owner one (a repo right under it, the flat layout, is
    fine), or anything in a hidden home folder or ~/Library unless its
    repo is rooted in there too (a ~/.config-repo is fine; ~/.aws in a repo at ~ isn't)."""
    from ogun.exchange import folders
    h, ex = real_path(Path.home()), real_path(folders.exchange())
    roots = [(real_path(f), owner) for f, owner in paths.roots()]
    if d == "/" or d == h or h.startswith(d + "/"):
        return "it holds your whole home"
    if any(d == p or p.startswith(d + "/") for p, _ in roots):
        return "it holds every project (a project folder: SBX_PROJECTS)"
    if ex and (d == ex or d.startswith(ex + "/") or ex.startswith(d + "/")):
        return "it is the file exchange, or holds it"
    if any(owner is None and os.path.dirname(d) == p for p, owner in roots) and d != tl:
        return "it is an owner's folder (every repo of that owner)"
    top = d.removeprefix(h + "/").split("/", 1)[0]
    if (d.startswith(h + "/") and (top.startswith(".") or top == "Library")
            and not (tl and (tl == f"{h}/{top}" or tl.startswith(f"{h}/{top}/")))):
        return f"it is in ~/{top}, where credentials live"
    return ""


def _ask(q: str) -> bool:
    """A yes at a terminal ($SBX_MENU_IN for tests); no terminal, or anything but
    yes: False, and nothing was changed."""
    menu = os.environ.get("SBX_MENU_IN")
    if not sys.stdin.isatty() and not menu:
        log.err(f"og: {q.removesuffix('?')} — run og at a terminal to be asked, or do it yourself "
                "(git init, then a first commit)")
        return False
    print(f"    {q} [y/N] ", end="", file=sys.stderr, flush=True)
    try:
        with open(menu or "/dev/tty") as f:
            ans = f.readline().strip()
    except OSError:
        ans = ""
    if not ans.startswith(("y", "Y")):
        log.err("og: nothing changed, nothing created")
        return False
    return True


def _first_commit(d: str) -> bool:
    # --only with no paths: empty, whatever is staged stays staged
    return subprocess.run(["git", "-C", d, "commit", "-q", "--allow-empty", "--only", "-m", "Initial commit"]).returncode == 0


def offer_init(d: str) -> bool:
    """A sandbox's workspace is a git repo it clones: sbx mounts anything else
    read-write, and clone mode needs a repo. A folder that isn't in one is offered
    `git init` and an empty first commit (something to clone), at a terminal and
    on a yes only. Files left uncommitted are still readable inside, at
    /run/sandbox/source. Never a folder that holds more than one project or
    credentials, repo or not: the folder, and the root of any repo it is in, are
    both checked, so a repo at ~ makes neither ~/.aws nor ~/Projects/x a
    workspace. True: a repo with a commit. d is a physical path."""
    t = run_git(d, "rev-parse", "--show-toplevel")
    tl = real_path(t.stdout.rstrip("\n")) if t.returncode == 0 and t.stdout.strip() else ""
    why = too_broad(d, tl)
    if not why and tl and tl != d:
        w = too_broad(tl, tl)
        why = f"in the repo at {tl}: {w}" if w else ""
    if why:
        log.err(f"og: {d} can't be a sandbox's workspace — {why}. Make a folder for the project and run og there")
        return False
    if tl:
        if run_git(d, "rev-parse", "-q", "--verify", "HEAD").returncode == 0:
            return True
        # a repo with no commit yet has nothing to clone: offer the first one
        if not _ask(f"{d} is a git repo with no commit yet — make an empty first commit?"):
            return False
        if not _first_commit(d):
            log.err(f"og: the first commit failed in {d} (git config user.name / user.email, signing, a hook?)")
            return False
        return True
    if not _ask(f"{d} is not a git repo — make it one (git init, an empty first commit)?"):
        return False
    # a first commit that fails (identity, signing, a hook) undoes the init it
    # followed: a repo with no commit would read as ready next time
    had = os.path.exists(os.path.join(d, ".git"))
    if subprocess.run(["git", "init", "-q", d]).returncode:
        log.err(f"og: git init failed in {d}")
        return False
    if not _first_commit(d):
        undone = ""
        if not had:
            shutil.rmtree(os.path.join(d, ".git"), ignore_errors=True)
            undone = " — the init was undone"
        log.err(f"og: the first commit failed in {d} (git config user.name / user.email, signing, a hook?){undone}")
        return False
    log.step(f"{d} is a git repo now; files you haven't committed are readable inside at /run/sandbox/source")
    return True
