"""`og take`: what a sandbox left in its out/, listed or brought to this Mac, each file
checked first (screen.py)."""

import os
import shutil
import stat
import tempfile
from pathlib import Path

from ogun.core import boxes, log, naming
from ogun.exchange import folders, scan, screen

TAKE_USAGE = "<name> [<file>... | --all]"
TAKE_HELP = dict(
    about="Bring what a sandbox left in its out/ to this Mac, checked first.",
    forms=[
        ("og take <name>", "list what waits in its out/"),
        ("og take <name> <file>…", "take those files"),
        ("og take <name> --all", "take everything"),
    ],
    notes=["Each file is checked before it's delivered: a link, a folder, a program, or an extension that "
           "doesn't match the content is quarantined instead. Files land in ~/Downloads (SBX_TAKE_DEST), "
           "never over one already there."],
    examples=["og take cub", "og take cub report.pdf", "og take cub --all"],
)


def take_usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("take", TAKE_USAGE, problem=problem, err=err, **TAKE_HELP)


def _stranded(ex: Path) -> None:
    """Files an earlier take left in host-only staging, kept on purpose (one it
    couldn't check or deliver) or by a take cut short: they'd vanish from every
    listing, so each folder is reported, never removed while it holds anything."""
    for sd in sorted((ex / ".staging").glob("take.*/")):
        # another take can finish and remove its folder between any two of these
        # lines: a folder gone is one nobody has to collect
        try:
            pid = (sd / ".pid").read_text().strip()
        except OSError:
            pid = ""
        if pid and folders.alive(pid):
            continue   # a take running now
        try:
            held = any(x.name != ".pid" for x in sd.iterdir())
        except OSError:
            continue
        if not held:
            shutil.rmtree(sd, ignore_errors=True)
            continue
        log.warn(f"  {log.WARNING} an earlier og take left files in {log.path(sd)} — move what you want, then delete the folder:",
                 err=True, fix=log.cmd(f"rm -rf {folders.sh_path(sd)}"))


def take(args: list[str], quiet: bool = False) -> int:
    """quiet: each file taken is a note, not a done line, for a command that
    takes a file on its way to its own done line (og ship)."""
    if not args:
        take_usage("og take needs a sandbox name")
        return 1
    name, rest = args[0], args[1:]
    if refused(name, rest):
        return 1
    scan.scan(quiet=True)   # the same upkeep as attach: sweep before collecting
    ex = folders.exchange()
    box = folders.box(name)
    if box is None:
        log.err(f"og take: no sandbox '{name}' has a folder in the exchange; to see yours, run:", fix=log.cmd("og ls"))
        return 1
    out = box / "out"
    if not out.is_dir():
        log.err(f"og take: {name}'s folder has no out/ ({log.path(out)})")
        return 1
    if (ex / ".staging").is_dir():
        _stranded(ex)
    try:
        waiting = sorted(out.iterdir(), key=lambda p: p.name)
    except OSError:
        log.err(f"og take: {name}'s out/ can't be read ({log.path(out)})")
        return 1
    if not rest:
        listing(name, waiting)
        return 0
    targets = chosen(name, out, rest, waiting)
    if targets is None:
        return 1
    return _collect(name, targets, quiet) if targets else 0


def refused(name: str, rest: list[str]) -> bool:
    """A take refused, and said why, before any of the job, the upkeep scan
    included."""
    for a in [name, *rest]:
        if a.startswith("-") and a != "--all":
            take_usage(f"og take has no option {a}")
            return True
    if name == "--all":
        take_usage("og take needs a sandbox name before --all")
        return True
    if "--all" in rest and rest != ["--all"]:
        take_usage("og take takes file names or --all, not both")
        return True
    # the name builds host paths (out/, staging, quarantine): sandbox characters
    # only, or `og take ../victim --all` walks out of the exchange
    if not naming.name_chars(name):
        naming.bad_name("take", name)
        return True
    if naming.reserved(name):
        naming.reserved_name("take", name)
        return True
    for a in rest:
        # "" and "." would name out/ itself: the claim would quarantine the whole outbox
        if not a or a in (".", "..") or "/" in a:
            log.err(f"og take: plain file names only, got '{screen.shown(a)}'")
            return True
    return False


def listing(name: str, waiting: list[Path]) -> None:
    rows = []
    for p in waiting:
        try:
            st = p.lstat()
        except OSError:   # removed by the sandbox since the listing
            continue
        rows.append([screen.shown(p.name) + ("/" if p.is_dir() and not p.is_symlink() else ""),
                     "-" if not stat.S_ISREG(st.st_mode) else log.size(st.st_size), log.when(st.st_mtime)])
    boxes.columns(["FILE", "SIZE", "MODIFIED"], rows, title=f"take {name}",
                  foot=f"take one: {log.cmd(f'og take {name} <file>')} · everything: {log.cmd(f'og take {name} --all')}")


def chosen(name: str, out: Path, rest: list[str], waiting: list[Path]) -> list[Path] | None:
    """The files to take: everything waiting for --all (none is said, not an
    error), else each one named, or None when one isn't there."""
    if rest == ["--all"]:
        if not waiting:
            log.info(f"nothing in {name}'s out/ to take")
        return waiting
    targets = []
    for a in rest:
        if not screen.taken(out / a):
            log.err(f"og take: no '{screen.shown(a)}' in {name}'s out/ — this lists what's there:", fix=log.cmd(f"og take {name}"))
            return None
        targets.append(out / a)
    return targets


def _collect(name: str, targets: list[Path], quiet: bool = False) -> int:
    """Two steps, since the sandbox may still be RUNNING. Claim: rename each entry
    into host-only staging, so its name and type can't be swapped under us, and
    whatever the sandbox writes to the old name later is a different file. Detach:
    the claimed file may still be open for writing inside the sandbox, so its copy
    is checked, tagged and delivered, never the claim itself."""
    ex, dest = folders.exchange(), screen.take_dest()
    dest.mkdir(parents=True, exist_ok=True)
    (ex / ".staging").mkdir(parents=True, exist_ok=True)
    try:
        staging = Path(tempfile.mkdtemp(prefix="take.", dir=ex / ".staging"))
    except OSError:
        log.err(f"og take: couldn't make a folder to check files in, under {log.path(ex / '.staging')}")
        return 1
    (staging / ".pid").write_text(str(os.getpid()))   # a take cut short leaves this, and the next one reports what it held
    rc = 0
    for f in targets:
        claimed = claim(name, f, staging)
        made = claimed and detach(f.name, claimed, staging)
        if not made:
            rc = 1
            continue
        chk, copy = made
        if not deliver(name, f.name, claimed, copy, dest, quiet):
            rc = 1
        shutil.rmtree(chk, ignore_errors=True)
    (staging / ".pid").unlink(missing_ok=True)
    try:
        staging.rmdir()   # only when empty: what's kept is reported by the next take
    except OSError:
        pass
    return rc


def claim(name: str, f: Path, staging: Path) -> Path | None:
    """f renamed into staging, or None: it couldn't be moved, or isn't a plain
    file of its own, and is quarantined."""
    claimed = staging / screen.dedupe(staging, f.name)
    try:
        os.rename(f, claimed)
    except OSError:
        log.warn(f"  {log.WARNING} couldn't move {screen.shown(f.name)} out of {name}'s out/ — skipped", err=True)
        return None
    why = ("symlink" if claimed.is_symlink() else "subdirectory (out is flat)" if claimed.is_dir()
           else "not a regular file" if not claimed.is_file()
           # the link count on the claim: the copy below is a fresh inode with one
           else "hardlinked elsewhere" if claimed.lstat().st_nlink > 1 else None)
    if why:
        screen.quarantine(claimed, name, why)
        return None
    return claimed


def detach(base: str, claimed: Path, staging: Path) -> tuple[Path, Path] | None:
    """A copy of the claim, in a private folder under staging, as (folder, copy);
    None when it can't be made, the claim kept where it is and said."""
    # the copy keeps the real name (in a private folder), so the name rule
    # judges the sandbox's name, not a temporary one
    try:
        chk = Path(tempfile.mkdtemp(prefix=".chk.", dir=staging))
    except OSError:
        # NEVER back into out/: it's the sandbox's to write, and a folder made
        # under the same name would take the claim straight back
        log.warn(f"  {log.WARNING} couldn't check {screen.shown(base)} — it's kept at {screen.shown(log.path(claimed))}", err=True)
        return None
    copy = chk / base
    try:
        shutil.copyfile(claimed, copy)
        shutil.copymode(claimed, copy)
    except OSError:
        shutil.rmtree(chk, ignore_errors=True)
        log.warn(f"  {log.WARNING} couldn't check {screen.shown(base)} — it's kept at {screen.shown(log.path(claimed))}", err=True)
        return None
    return chk, copy


def deliver(name: str, base: str, claimed: Path, copy: Path, dest: Path, quiet: bool) -> bool:
    """The copy checked, tagged and placed in dest, the claim then removed; a
    copy that breaks a rule or loses its tag quarantines the claim instead."""
    why = screen.check(copy, "out")
    if why:
        screen.quarantine(claimed, name, why)
        return False
    if not screen.tag(copy):
        screen.quarantine(claimed, name, "Gatekeeper's mark couldn't be set")
        return False
    got = screen.place(copy, dest, base)
    if got and not screen.tagged(got):
        # the mark was lost on the way (a copy across disks): fail closed, never
        # an unmarked file in Downloads; the claim stays, quarantined
        got.unlink(missing_ok=True)
        screen.quarantine(claimed, name, "it lost Gatekeeper's mark on the way to Downloads")
        return False
    if not got:
        log.warn(f"  {log.WARNING} couldn't put {screen.shown(base)} in {log.path(dest)} — it's kept at {screen.shown(log.path(claimed))}", err=True)
        return False
    claimed.unlink(missing_ok=True)
    log.file("wrote", screen.shown(str(got)))
    if quiet:
        log.note(f"took {screen.shown(base)} from {name}, to {screen.shown(log.path(got))}")
    else:
        log.ok(f"took {screen.shown(base)} from {name}", screen.shown(log.path(got)))
    log.record(f"took {screen.shown(base)} from {name} to {screen.shown(log.path(got))}")
    return True
