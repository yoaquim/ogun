"""A sandbox's folders in the exchange: where they are, and removing them once it's gone."""

import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from ogun.core import log, naming, records, settings
from ogun.exchange import screen


def exchange() -> Path:
    return settings.path("exchange", Path.home() / "sandboxes.noindex")


def box(name: str) -> Path | None:
    """A sandbox's box (in/ + out/), boxes/<name>, or None. Kept in step with the
    shell completion's _sbx_exchange_box."""
    b = exchange() / "boxes" / name
    return b if b.is_dir() else None


def has_files(d: Path) -> bool:
    try:
        with os.scandir(d) as it:
            return any(True for _ in it)
    except OSError:
        return False


def sh_path(p) -> str:
    """A path as a command to copy names it: ~/… when that needs no quoting."""
    s = log.path(p)
    return s if re.fullmatch(r"~?[\w./-]+", s) else shlex.quote(str(p))


def box_rm(name: str, b: Path | None = None, say: bool = True) -> str:
    """A sandbox's box dies with it; shared/<name>/ (knowledge) and
    .quarantine/<name>/ (evidence) outlive it. A box with files in out/ is kept
    and reported, never deleted unseen. b: the box, when the caller found it;
    say: a note when it's removed. "removed", "kept", "none" (it had none), or
    "failed": not removed, or the name isn't one a path may be built from."""
    # this ends in a recursive delete of a path built from the name: only the
    # sandbox charset passes, or `og rm ../../shared` (which sbx rm rejects,
    # reading as "already gone") would resolve a traversal here
    if not naming.name_chars(name) or naming.reserved(name):
        return "failed"
    b = b or box(name)
    if b is None:
        return "none"
    if has_files(b / "out"):
        log.warn(f"  {log.WARNING} kept {name}'s folder: files wait in its out/",
                 fix=f"{log.cmd(f'og take {name} --all')}, then {log.cmd('og tidy --rm')}")
        return "kept"
    # "removed" only when it is TRUE: a sandbox can leave entries that can't be
    # unlinked (an unreadable directory it made), and claiming it anyway would
    # hide that in/ and out/ are still on disk
    if b.is_symlink():
        b.unlink(missing_ok=True)
    else:
        shutil.rmtree(b, ignore_errors=True)
    if not os.path.lexists(b):
        log.file("removed", b)
        if say:
            log.note(f"its folder removed ({log.path(b)})")
        return "removed"
    log.warn(f"  {log.WARNING} couldn't remove all of {name}'s folder — remove it by hand:",
             err=True, fix=log.cmd(f"rm -rf {sh_path(b)}"))
    return "failed"


def leftovers(name: str) -> bool:
    """Anything og keeps for a sandbox on this Mac: its folder in the exchange, its
    create record. A sandbox sbx doesn't know with neither was never one, or is gone
    already, fully."""
    return box(name) is not None or (len(name) <= 61 and records.record_file(name).exists())


def alive(pid: str) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def root() -> None:
    """The exchange's own folders, shared/'s history and the marker a read guard, if a
    provision command adds one, anchors on (docs/appendix/exchange.md), each made again
    if missing. shared/'s top is read-only to every
    sandbox, so none can plant or remove the marker."""
    ex = exchange()
    for d in ("inbox", "shared", "boxes"):
        (ex / d).mkdir(parents=True, exist_ok=True)
    if not (ex / "shared" / ".git").is_dir():
        subprocess.run(["git", "-C", str(ex / "shared"), "init", "-q"], capture_output=True)
    marker = ex / "shared" / ".exchange"
    if not marker.is_file():
        marker.write_text("sandbox exchange marker — do not remove\n")


def case_conflict(name: str) -> str | None:
    """A folder already in the exchange whose name differs from name only in
    case: on the Mac's filesystem `Acme` and `acme` are the same folder, so either
    sandbox could replace the other's files."""
    ex, low = exchange(), name.lower()
    for parent in (ex / "shared", ex / "boxes"):
        if not parent.is_dir():
            continue
        for d in parent.iterdir():
            if d.is_dir() and not d.name.startswith(".") and d.name != name and not naming.reserved(d.name) and d.name.lower() == low:
                return d.name
    return None


def take_lock(path: Path, tries: int = 100) -> bool:
    """A lock folder holding its owner's pid; one whose owner is gone (or, with no
    pid, older than a minute) is taken over, renamed first so only one waiter
    wins it. False once held by a live owner through tries tenth-of-a-second
    waits (tries=1: no wait at all)."""
    # a few rounds past the waits: a lock let go or taken over costs a round, not a wait
    for _ in range(tries + 3):
        try:
            path.mkdir()
            (path / "pid").write_text(str(os.getpid()))
            return True
        except FileExistsError:
            pass
        # the holder can release the lock between any two of these lines: a lock
        # gone is free, so the mkdir is tried again
        try:
            pid = (path / "pid").read_text().strip()
        except OSError:
            pid = ""
        try:
            stale = (pid and not alive(pid)) or (not pid and time.time() - path.stat().st_mtime > 60)
        except OSError:
            continue
        if stale:
            grab = path.with_name(f"{path.name}.reclaim.{os.getpid()}")
            try:
                path.rename(grab)
                shutil.rmtree(grab, ignore_errors=True)
            except OSError:
                pass
            continue
        tries -= 1
        if tries <= 0:
            return False
        time.sleep(0.1)
    return False


def drop_lock(path: Path) -> None:
    try:
        mine = (path / "pid").read_text().strip() == str(os.getpid())
    except OSError:
        mine = False
    if mine:
        shutil.rmtree(path, ignore_errors=True)


def dirs(name: str) -> str:
    """A sandbox's shared/ folder and its box, made if missing. A name keeps the
    box it has, in any layout (a sandbox mounts its box's path from its create
    on); a new one gets boxes/<name>. "" when made, else why not: a name that
    isn't one og makes, or is reserved, is refused, as it becomes writable mount
    paths and `--name ../inbox` would reach the inbox."""
    if not naming.name_chars(name):
        return f"'{screen.shown(name)}' can't be a sandbox name — {naming.NAME_RULE}"
    if len(name) > 61:
        return "og makes folders only for a name of at most 61 characters"
    if naming.reserved(name):
        return f"'{name}' is one of the exchange's own folders"
    ex = exchange()
    try:
        ex.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"couldn't make {log.path(ex)}: {e.strerror or e}"
    # the case check and the folders as one step: two terminals making `Acme` and
    # `acme` at once must not both pass the check before either folder exists
    lock = ex / ".reserve-lock"
    if not take_lock(lock):
        return f"another og is making folders in the exchange (it holds {log.path(lock)}) — try again"
    try:
        other = case_conflict(name)
        if other:
            return f"the exchange has a folder '{screen.shown(other)}' already, and this Mac's filesystem reads it as '{name}'"
        own = box(name) or ex / "boxes" / name
        for d in (ex / "shared" / name, own / "out", own / "in"):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return f"couldn't make {log.path(d)}: {e.strerror or e}"
        root()
        return ""
    finally:
        drop_lock(lock)
