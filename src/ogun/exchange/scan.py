"""`og scan`: shared/ swept to its rules (text only, no folders), what breaks them
quarantined, and its history committed, a sandbox's changes under its name."""

import subprocess
from pathlib import Path

from ogun.core import boxes, log
from ogun.exchange import folders, screen


def _git(*args: str) -> subprocess.CompletedProcess:
    """git in shared/, with nothing in that sandbox-writable tree able to steer how
    commits are made: no hooks, the identity fixed here."""
    return subprocess.run(["git", "-C", str(folders.exchange() / "shared"), "-c", "core.hooksPath=/dev/null",
                           "-c", "user.name=host", "-c", "user.email=host@sandboxes.local", *args],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)


def scan(quiet: bool = False) -> int | None:
    """Enforce shared/'s rules (flat, .md/.txt/.json, no executable bit), then
    commit its history, each sandbox's folder under its own name (the Mac is the
    only committer). How many changes it made (a file quarantined, a commit), -1
    when another scan is committing; None when there's no exchange. Quarantine
    lines always show; quiet (take and attach's upkeep) hides the rest."""
    ex = folders.exchange()
    if not ex.is_dir():
        return None
    shared = ex / "shared"
    changed = 0
    # each sandbox's own folder; never a hidden one, which is the host's (.git, the
    # history; .approved) and no sandbox's to have checked or quarantined
    subs = sorted(d for d in shared.iterdir() if d.is_dir() and not d.name.startswith(".")) if shared.is_dir() else []
    for d in subs:
        try:
            entries = sorted(d.iterdir())
        except OSError:
            log.warn(f"  {log.WARNING} shared/{screen.shown(d.name)} can't be read — skipped", err=True)
            continue
        for f in entries:
            if f.is_dir() and not f.is_symlink():
                changed += screen.quarantine(f, d.name, "subdirectory (shared is flat)")
                continue
            # NEVER chmod or tag a passing LIVE path, here or in out/: a racing swap
            # to a symlink would aim the change at its target. Only a claimed copy
            # is changed (og take's).
            why = screen.check(f, "shared")
            if why:
                changed += screen.quarantine(f, d.name, why)
    if (shared / ".git").is_dir():
        commits = _commit(ex, subs, quiet)
        if commits is None:
            return -1
        changed += commits
    return changed


def _commit(ex: Path, subs: list[Path], quiet: bool) -> int | None:
    """One committer at a time: two scans at once could commit one sandbox's
    files under another's name. How many commits it made; None when another
    scan holds the lock (skipped, never waited on)."""
    lock = ex / ".scan-lock"
    if not folders.take_lock(lock, tries=1):
        if not quiet:
            log.note("shared: another og scan is committing — skipped")
        return None
    made = 0
    try:
        # a scan that died may have staged files, or left git's index.lock: safe
        # to clear while holding the lock, as only a scan commits here
        (ex / "shared" / ".git" / "index.lock").unlink(missing_ok=True)
        _git("reset", "-q")
        for d in subs:
            _git("add", "-A", "--", d.name)
            if _git("diff", "--cached", "--quiet").returncode != 0:
                if _git("commit", "-q", "--author", f"sbx-{d.name} <sbx-{d.name}@sandboxes.local>", "-m", f"sync {d.name}").returncode == 0:
                    made += 1
                    if not quiet:
                        log.ok(f"committed shared/{screen.shown(d.name)}'s history")
                else:
                    # unstaged, or the next sandbox's commit would carry these under its name
                    _git("reset", "-q")
                    log.warn(f"  {log.WARNING} shared/{screen.shown(d.name)}: commit failed — changes left uncommitted", err=True)
        # only the host's own paths: a bare add -A would stage what a running sandbox
        # wrote since its commit above, as host edits. A removed .approved still
        # stages its deletion, so a revoked approval reaches the history.
        for hp in (".exchange", ".approved"):
            _git("add", "-A", "--", hp)
        if _git("diff", "--cached", "--quiet").returncode != 0:
            if _git("commit", "-q", "-m", "host edits").returncode == 0:
                made += 1
                if not quiet:
                    log.ok("committed the host's edits to shared/")
            else:
                _git("reset", "-q")
                log.warn(f"  {log.WARNING} shared: the host's edits couldn't be committed — left uncommitted", err=True)
    finally:
        folders.drop_lock(lock)
    return made


SCAN_HELP = dict(
    about="Check every sandbox's shared/ folder and commit its history.",
    forms=[("og scan", "quarantine what breaks shared/'s rules (a subfolder, a file not .md, .txt or .json, "
                       "an executable bit), then commit each sandbox's changes under its own name")],
    notes=["og take and every attach run it too, quietly."],
    examples=["og scan"],
)


def scan_usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("scan", "", problem=problem, err=err, **SCAN_HELP)


def scan_cmd(args: list[str]) -> int:
    """og scan: what scan changed, a line each, or that there was nothing to."""
    if args:
        scan_usage("og scan takes no arguments")
        return 1
    ex = folders.exchange()
    changed = scan()
    if changed is None:
        log.err(f"og scan: no exchange at {log.path(ex)}")
        return 1
    if changed == 0:
        log.info("nothing to change in shared/")
    return 0
