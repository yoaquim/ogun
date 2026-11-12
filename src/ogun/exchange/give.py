"""`og give`: files (or the clipboard) into the exchange, for every sandbox (inbox/) or one
(its box's in/), all of them or none."""

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ogun.core import boxes, log, naming, sbx
from ogun.exchange import folders, screen

GIVE_USAGE = "[<name>] <file>...  |  [<name>] --clip"
GIVE_HELP = dict(
    about="Hand files to sandboxes: to every one through the inbox, or to one alone.",
    forms=[
        ("og give <file>…", "into the inbox, which every sandbox reads"),
        ("og give <name> <file>…", "into that sandbox's own in/, which only it reads"),
        ("og give [<name>] --clip", "the image on the clipboard, the same way"),
    ],
    notes=["A name that's also a file here is refused: use ./<name> for the file."],
    examples=["og give notes.pdf", "og give cub spec.md", "og give cub --clip"],
)


def give_usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("give", GIVE_USAGE, problem=problem, err=err, **GIVE_HELP)


def give(args: list[str]) -> int:
    if not args:
        give_usage("og give needs a file, or --clip")
        return 1
    if refused(args):
        return 1
    ex = folders.exchange()
    to = target(ex, args)
    if to is None:
        return 1
    dest, who, args = to
    if not args:
        give_usage("og give needs a file, or --clip")
        return 1
    if "--clip" in args and args != ["--clip"]:
        give_usage("og give takes files or --clip, not both")
        return 1
    dest.mkdir(parents=True, exist_ok=True)
    (ex / ".staging").mkdir(parents=True, exist_ok=True)
    if args[0] == "--clip":
        return clip(ex, dest, who)
    return files(ex, args, dest, who)


def refused(args: list[str]) -> bool:
    """Every word checked before anything is made: a refusal does none of the
    job first."""
    for a in args:
        if a.startswith("-") and a != "--clip":
            give_usage(f"og give has no option {a}")
            return True
    if "--clip" in args and args not in (["--clip"], [args[0], "--clip"]):
        give_usage("og give takes files or --clip, not both")
        return True
    return False


def target(ex: Path, args: list[str]) -> tuple[Path, str, list[str]] | None:
    """Where the give lands, who it's for, and the words left: the inbox every
    sandbox reads, or a named sandbox's own in/ (its box made when it has none
    yet). None when that can't be told or made, said."""
    first = args[0]
    # a first word naming a sandbox sends to its own in/ alone. Known by its
    # characters, not og's 61 limit: a longer one made with plain sbx must reach
    # its box or the refusals here, never the inbox everyone reads
    if first == "--clip" or not naming.name_chars(first) or naming.reserved(first):
        return ex / "inbox", "every sandbox", args
    box = folders.box(first)
    known = True if box else sbx.exists(first)
    if known is None:   # can't tell a sandbox from a file: the inbox every sandbox reads is no guess
        log.err(f"og give: sbx couldn't list its sandboxes, so og can't tell whether '{first}' is one; nothing was given")
        return None
    if not known:
        return ex / "inbox", "every sandbox", args
    if Path(first).exists():
        log.err(f"og give: '{first}' is both a file here and a sandbox — ./{first} for the file, "
                "or name the sandbox from another folder")
        return None
    if box is None:
        why = folders.dirs(first)
        if why:
            log.err(f"og give: couldn't make {first}'s folders in the exchange: {why}")
            return None
        box = folders.box(first)
    return box / "in", first, args[1:]


def clip(ex: Path, dest: Path, who: str) -> int:
    """The image on the clipboard, given as a dated png."""
    if not shutil.which("pngpaste"):
        log.err("og give: pngpaste is missing", fix=log.cmd("brew install pngpaste"))
        return 1
    fd, tmp = tempfile.mkstemp(prefix=".clip.", dir=ex / ".staging")
    os.close(fd)
    if subprocess.run(["pngpaste", tmp], capture_output=True).returncode != 0:
        Path(tmp).unlink(missing_ok=True)
        log.err("og give: there's no image on the clipboard")
        return 1
    return _hand(Path(tmp), dest, f"clip-{time.strftime('%Y%m%d-%H%M%S')}.png", who)


def files(ex: Path, args: list[str], dest: Path, who: str) -> int:
    """Each file given, every one checked before any is: a refusal does none of
    the job first."""
    for a in args:
        f = Path(a)
        if not (f.exists() or f.is_symlink()):
            log.err(f"og give: no file '{a}'")
            return 1
        if f.is_symlink() or not f.is_file():
            log.err(f"og give: {a} is a folder or a link — give files one at a time")
            return 1
    for a in args:
        f = Path(a)
        # staged in private, then moved in: a copy dying midway (disk full) must
        # never leave a partial file a sandbox can see
        fd, tmp = tempfile.mkstemp(prefix=".give.", dir=ex / ".staging")
        os.close(fd)
        try:
            shutil.copyfile(f, tmp)
            shutil.copymode(f, tmp)
        except OSError:
            Path(tmp).unlink(missing_ok=True)
            log.err(f"og give: couldn't copy {a}")
            return 1
        if _hand(Path(tmp), dest, f.name, who):
            return 1
    return 0


def _hand(staged: Path, dest: Path, name: str, who: str) -> int:
    got = screen.place(staged, dest, name)
    if not got:
        staged.unlink(missing_ok=True)
        log.err(f"og give: couldn't put {name} in {log.path(dest)}")
        return 1
    log.file("wrote", got)
    log.ok(f"gave {got.name} to {who}", log.path(got))
    log.record(f"gave {got.name} to {who}")
    return 0
