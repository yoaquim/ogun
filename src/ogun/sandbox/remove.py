"""`og rm`, and --if-clean, which removes a sandbox only when nothing would be lost.
The one removal path (rm_clean) is also what a failed create and an attach's --rm run."""

import re
import subprocess

from ogun.core import boxes, log, naming, paths, records, sbx, settings
from ogun.exchange import folders
from ogun.sandbox import sandboxes

PROBE = paths.SCRIPTS / "unsafe-probe.sh"


def _record_rm(name: str) -> None:
    """The create's record (template, mounts): it describes nothing once the
    sandbox is gone."""
    f = records.record_file(name)
    if naming.name_chars(name) and len(name) <= 61 and f.exists():
        f.unlink(missing_ok=True)
        log.file("removed", f)


def _names(listing: str) -> list[str]:
    return [line.split()[0] for line in listing.splitlines()[1:] if line.split()]


def gone(name: str) -> bool:
    """True only when a list sbx DID give has no such sandbox: with sbx down the
    list fails, and "not in an empty list" must never read as gone — that would
    delete the box of a live sandbox."""
    out = sbx.ls()
    return out is not None and name not in _names(out)


def rm_clean(name: str, force: bool = False, known_gone: bool = False) -> bool:
    """Remove a sandbox, then its folder and create record. The cleanup runs when
    sbx removed it or it's PROVEN already gone, so one that failed can be retried.

    force: only from a caller that has confirmed (og rm --force, a failed create).
    sbx's own --force skips its y/N (which it refuses with no terminal) and its
    in-use check, so a plain og rm keeps both and never cuts an open ssh or
    attach. sbx's words show only for its y/N, or when a forced rm failed.

    known_gone: the caller just saw sbx list no such sandbox, so there's no sbx
    rm to run (and no "not found" from it), only what it left to clean."""
    if known_gone:
        p = subprocess.CompletedProcess(["sbx", "rm", name], 1, "", "")
    elif force:
        p = sbx.run("rm", name, "--force", wait=f"removing {name}")
    else:
        p = sbx.run("rm", name, show=True)
    if p.returncode != 0 and not known_gone and not gone(name):
        if force:
            sbx_said(f"og rm: sbx couldn't remove {name}:", p)
        return False
    if p.returncode != 0 and not folders.leftovers(name):
        # gone, and nothing of it left: what was asked for is already true, but
        # nothing was removed, so no done line and no record
        log.info(f"nothing to remove: no sandbox '{name}', and nothing left of one")
        return True
    b = folders.box_rm(name)   # a folder that couldn't be cleaned is this call's failure: the retry depends on it
    _record_rm(name)
    what = f"{name}" if p.returncode == 0 else f"what {name} left behind"
    if b != "failed":
        log.ok(f"removed {what}", f"shared/{name} and its folder (files in out/) kept" if b == "kept" else f"shared/{name} kept")
    log.record(f"{what} removed" + {"failed": ", but its folder couldn't be", "kept": "; its folder kept (files in out/)"}.get(b, ""))
    return b != "failed"


def unsafe(name: str, mode: str = "", timeout: float | None = None, listing: str | None = None) -> subprocess.CompletedProcess:
    """The check for unsaved work (unsafe-probe.sh), run inside the sandbox: its
    lines are the reasons to keep it, none when nothing would be lost. It is told the
    sandbox's own workspace, from sbx's listing: og may have mounted it from outside
    the places the check looks by default, and work there must never be missed."""
    if listing is None:
        listing = sbx.ls() or ""
    ws = sbx.workspace(name, listing)
    return sbx.run("exec", name, "bash", "-lc", PROBE.read_text(), "_", *(["--root", ws] if ws else []),
                   *([mode] if mode else []), timeout=timeout, cap=65536, wait=f"checking {name} for unsaved work")


def unsafe_reasons(name: str) -> list[str]:
    """Why not to remove it, a line each; none when nothing would be lost. A check
    that didn't run is a reason too: unknown work is never read as none."""
    p = unsafe(name, timeout=probe_timeout(stopped=True))
    if p.returncode == 124:   # what sbx.run gives a call past its time limit
        return [f"{name} didn't answer the check for unsaved work in time"]
    if p.returncode != 0:
        return [f"the check for unsaved work failed (exit {p.returncode})"]
    # the sandbox's own words, paths it chose among them
    return [log.shown(line) for line in p.stdout.splitlines() if line.strip()]


def sbx_said(msg: str, p) -> None:
    """A failed sbx call: og's line, then what sbx said, a note a line."""
    log.err(msg)
    for line in ((p.stdout or "") + (p.stderr or "")).splitlines():
        if line.strip():
            log.note(log.shown(line.strip()), err=True)


def probe_timeout(stopped: bool) -> int:
    """How long the check for unsaved work may take: a stopped sandbox boots for it."""
    return settings.seconds("SBX_RM_BOOT_TIMEOUT", 400) if stopped else settings.seconds("SBX_RM_PROBE_TIMEOUT", 120)


def rm_if_clean(name: str) -> int:
    """Remove a sandbox only when nothing would be lost: no unpushed commits, no
    uncommitted work, no Claude session mid-turn or waiting on a person (an idle
    one loses nothing). Kept: `kept: <why>` on stdout and 3, for a program
    to read; a sandbox that doesn't answer in time is kept too, never guessed
    clean. Clean: removed with --force, as sbx's y/N needs a terminal and this
    check is the one --force would skip. Already gone: its box and record are
    cleaned all the same; an sbx that can't list keeps it."""
    listing = sbx.ls()
    if listing is None:
        print("kept: sbx ls did not answer")
        return 3
    if name not in _names(listing):
        return 0 if rm_clean(name, known_gone=True) else 1
    # a stopped sandbox ran nothing: booting it for the check is the cost, so it
    # gets the longer allowance, and only its git is asked
    stopped = any(s["sandbox"] == name and s["status"].lower() == "stopped" for s in sandboxes.as_json(listing))
    mode = "--stopped" if stopped else "--idle-ok"
    secs = probe_timeout(stopped)
    p = unsafe(name, mode, timeout=secs, listing=listing)
    if p.returncode != 0:
        print(f"kept: it did not answer the check for unsaved work (exit {p.returncode})")
        return 3
    why = [re.sub(r"[^\x20-\x7e]", "", line) for line in p.stdout.splitlines()]
    if any(why):
        print("kept: " + "; ".join(w for w in why if w))
        return 3
    return 0 if rm_clean(name, force=True) else 1


RM_USAGE = "<name> [--force | --if-clean]"
RM_HELP = dict(
    about="Remove a sandbox and its folder in the exchange, without losing work.",
    forms=[
        ("og rm <name>", "after a check for unsaved work; sbx asks before it removes"),
        ("og rm <name> --force", "no check and no question, even while it's in use"),
        ("og rm <name> --if-clean", "only when no work or live session would be lost; says why when kept"),
    ],
    notes=["Unsaved work: commits no remote has, uncommitted changes, a Claude session still running. "
           "Files waiting in its out/ keep its folder until taken. shared/<name> always stays."],
    examples=["og rm cub", "og rm cub --if-clean"],
)


def rm_usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("rm", RM_USAGE, problem=problem, err=err, **RM_HELP)


def rm(args: list[str]) -> int:
    force = if_clean = False
    name = ""
    for a in args:
        if a in ("--force", "-f"):
            force = True
        elif a == "--if-clean":
            if_clean = True
        elif a.startswith("-"):
            rm_usage(f"og rm has no option {a}")
            return 1
        elif name:   # one name: `og rm a b` must not quietly remove only b
            rm_usage("og rm takes one sandbox name")
            return 1
        else:
            name = a
    if not name or (force and if_clean):
        rm_usage("og rm needs a sandbox name" if not name else "--force and --if-clean don't go together")
        return 1
    if not naming.name_chars(name):
        naming.bad_name("rm", name)
        return 1
    if naming.reserved(name):
        naming.reserved_name("rm", name)
        return 1
    if if_clean:
        return rm_if_clean(name)
    # one sbx proves gone has nothing to check, only leftovers to clean (rm_clean's
    # retry); with none, there's nothing by that name to remove
    was = gone(name)
    if was and not folders.leftovers(name):
        log.err(f"og rm: no sandbox '{name}'; to see yours, run:", fix=log.cmd("og ls"))
        return 1
    if not force:
        # one that exists but doesn't answer the check stays refused
        why = [] if was else unsafe_reasons(name)
        if why:
            log.err(f"og rm: '{name}' has work that would be lost (below) — save it, or remove it anyway:",
                    fix=log.cmd(f"og rm {name} --force"))
            for line in why:
                log.note(line, err=True)
            log.note(f"to fetch its commits on the host: {log.cmd(f'git fetch sandbox-{name}')}", err=True)
            return 1
    return 0 if rm_clean(name, force, known_gone=was) else 1
