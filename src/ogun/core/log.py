"""One voice for everything og prints: the style guide (docs/appendix/ogun-style.md)
as code. Every color, mark and line lives here, and every box in boxes.py, and
nowhere else in src (tests/sh/python.test.sh fails on Rich or an escape code
anywhere else); `og style` draws each one.

On a terminal: a dim clock, then the line in its kind's color. Anywhere else (a
file, a pipe, the tests): the bare words, byte for byte, so every grep keeps
working; no clock, no color, no table. Errors go to stderr, the rest to stdout
unless a caller says otherwise.

More detail is opt-in, never mixed into the default output: OG_VERBOSE=1
(`og -v`) shows each sbx command og runs and how it ended, OG_VERBOSE=2
(`og -vv`) what it printed too. Those lines go to stderr, so stdout stays data.
The level is an environment variable so it reaches every process a command
starts, og internal among them."""

import os
import sys
import time

from rich.console import Console
from rich.text import Text

# The palette: soft colors, so og's lines read as one set.
# Rich drops to the nearest color a terminal can show.
OG = "#7dc4e4"        # og's own: arrows, borders, command forms
OK = "#a6da95"        # done
WARN = "#eed49f"      # needs a look
ERROR = "#ed8796"     # failed or refused
CALLOUT = "#f5a97f"   # must not scroll past
EXAMPLE = OK          # a line to copy and run

_STYLE = {"ok": OK, "warn": WARN, "error": ERROR, "info": ""}
# State marks: done, failed, waiting, idle, running; and needs a look
DONE, FAILED, WAITING, IDLE, RUNNING = "✓", "✗", "●", "○", "▸"
WARNING = "⚠"
# a state word's mark and color, wherever og lists things that run: a filled dot
# beside a hollow one reads at a glance, as a sandbox is on or off
STATES = {"running": ("●", f"bold {OK}"), "stopped": (IDLE, "dim"),
          # og net --log: a block needs a look; an allow is the quiet case
          "blocked": (FAILED, f"bold {ERROR}"), "allowed": (IDLE, "dim"),
          # og net <name>: a push can write to a repo, so it stands out with a block
          "push": (RUNNING, f"bold {WARN}")}
TAG = "#c6a0f6"       # a label on a row, as OpenAPPA on a protected sandbox: lavender
BOX_WIDTH = 96

_consoles: dict[bool, Console] = {}


def console(err: bool) -> Console:
    if err not in _consoles:
        _consoles[err] = Console(stderr=err, highlight=False, soft_wrap=True)
    return _consoles[err]


def wrapping(err: bool) -> Console:
    """For boxes: inside one, a long line folds, never cuts."""
    return Console(stderr=err, highlight=False)


def pretty(err: bool = False) -> bool:
    stream = sys.stderr if err else sys.stdout
    return stream.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"


def verbosity() -> int:
    v = os.environ.get("OG_VERBOSE", "")
    return int(v) if v.isdigit() else 0


# a command inside a message (cmd()), between two private-use marks no one types
CMD_OPEN, CMD_CLOSE = "\ue000", "\ue001"


def cmd(c: str) -> str:
    """A command inside a message, the part to copy and run: bold, og's color on a
    terminal; elsewhere the bare words, so the line reads as it always did."""
    return f"{CMD_OPEN}{c}{CMD_CLOSE}"


def plain(msg: str) -> str:
    return msg.replace(CMD_OPEN, "").replace(CMD_CLOSE, "")


def _emit(level: str, msg: str, err: bool, clock: str | None = None, detail: str = "") -> None:
    """clock: None, now; a time, when the line happened (og log replays a record);
    "", none, for a line that happened at no time (a read listing). detail: the
    rest of the line, dim, after two spaces (a path)."""
    if not pretty(err):
        print(plain(msg) + (f"  {plain(detail)}" if detail else ""), file=sys.stderr if err else sys.stdout, flush=True)
        return
    line = Text()   # each part styled on its own: a Text's own style would color the whole line
    clock = time.strftime("%H:%M:%S") if clock is None else clock
    if clock:
        line.append(f"[{clock}] ", style="dim")
    if msg.startswith("→ "):
        line.append("→ ", style=f"bold {OG}")
        msg = msg[2:]
    for i, part in enumerate(msg.replace(CMD_CLOSE, CMD_OPEN).split(CMD_OPEN)):
        line.append(part, style=f"bold {OG}" if i % 2 else _STYLE[level])
    if detail:
        line.append("  ")
        for i, part in enumerate(detail.replace(CMD_CLOSE, CMD_OPEN).split(CMD_OPEN)):
            line.append(part, style=f"bold {OG}" if i % 2 else "dim")
    console(err).print(line)


# ── formats: one way to show each kind of value ──

def shown(text: str) -> str:
    """Text a sandbox chose (a name, a line it printed), safe to print: a
    control byte in it would reach the terminal, which acts on it."""
    return "".join(c if c.isprintable() else f"\\x{ord(c):02x}" for c in text)


def path(p) -> str:
    """A path as og shows it: under your home as ~/…, so a line stays short."""
    s, home = str(p), str(os.path.expanduser("~"))
    return "~" + s[len(home):] if s == home or s.startswith(home + os.sep) else s


def size(n: int) -> str:
    """A size in bytes as 7 B, 12 KB, 1.2 MB, 3.4 GB: 1024 a step, one decimal under 10."""
    v = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return f"{int(v)} B" if unit == "B" else f"{v:.1f} {unit}" if v < 10 else f"{v:.0f} {unit}"
        v /= 1024
    return f"{n} B"


def when(t: float) -> str:
    """A moment as og shows it: local time, 2026-10-28 14:05."""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


class waiting:
    """`with log.waiting("checking cub for unsaved work"):` — a spinner with what
    og is waiting on, on a terminal's stderr, gone when the step ends. Nothing
    anywhere else: a pipe or a file gets the lines around it, not a frame a
    second."""

    def __init__(self, what: str):
        self.what, self.status = what, None

    def __enter__(self):
        if pretty(True):
            self.status = console(True).status(Text(f"{self.what}…", style="dim"), spinner="dots", spinner_style=OG)
            self.status.start()
        return self

    def __exit__(self, *exc):
        if self.status:
            self.status.stop()
        return False


# ── the kinds of line ──

def step(msg: str, err: bool = False, clock: str | None = None) -> None:
    """What og is doing now, as the heading of one stage of a command that has
    several (og policy's `→ baseline egress: …`). Never a result: that's ok()."""
    _emit("info", f"→ {msg}", err, clock)


def note(msg: str, err: bool = False, clock: str | None = None) -> None:
    """A fact under a step, worth seeing every time: `  · removed …`."""
    _emit("info", f"  · {msg}", err, clock)


def ok(summary: str, detail: str = "", err: bool = False) -> None:
    """What was asked for is done: `✓ gave note.txt to workshop`, the mark and the
    short summary green, any detail (a path, a hint) dim after it. One a completed
    change, when it happens; never a fact along the way (a note), a listing or a
    replay (og log), which are plain."""
    _emit("ok", f"{DONE} {summary}", err, None, detail)


def _fix(msg: str, fix: str, err: bool) -> None:
    """The command that fixes what the line above says, on its own line beneath,
    where that line's text starts: the part to copy, easy to select."""
    lead = len(msg) - len(msg.lstrip(" ")) + (2 if msg.lstrip(" ")[:1] in (WARNING, DONE, FAILED) else 0)
    if not pretty(err):
        print(" " * lead + plain(fix), file=sys.stderr if err else sys.stdout, flush=True)
        return
    line = Text(" " * (len("[00:00:00] ") + lead))
    for i, part in enumerate(fix.replace(CMD_CLOSE, CMD_OPEN).split(CMD_OPEN)):
        line.append(part, style=f"bold {OG}" if i % 2 else "")
    console(err).print(line)


def warn(msg: str, err: bool = False, fix: str = "") -> None:
    """Needs a look: yellow, `  ⚠ …` under a step; fix, the command that sorts it,
    on its own line beneath."""
    _emit("warn", msg, err)
    if fix:
        _fix(msg, fix, err)


def err(msg: str, fix: str = "") -> None:
    """Failed or refused: red, on stderr, `og <cmd>: why`; fix, the command to run
    instead or next, on its own line beneath."""
    _emit("error", msg, True)
    if fix:
        _fix(msg, fix, True)


def info(msg: str, err: bool = False, clock: str | None = None) -> None:
    _emit("info", msg, err, clock)


_sections = 0   # sections drawn this run: the first needs no blank line above it


def section(title: str) -> None:
    """A heading over the lines below it (a day in og log, a repo in og project
    ls): bold, og's color, a blank line above all but the first; plain, the bare
    title."""
    global _sections
    if not pretty():
        print(title, flush=True)
        return
    console(False).print(Text(("\n" if _sections else "") + title, style=f"bold {OG}"))
    _sections += 1


def aside(msg: str, under: str = "") -> None:
    """A dim line beneath the one above, where that line's text starts (past its
    clock and its mark, under): the command under a change in og log."""
    if not pretty():
        print(" " * len(under) + msg, flush=True)
        return
    console(False).print(Text(" " * (len("[00:00:00] ") + len(under)) + msg, style="dim"))


def detail(msg: str, level: int = 1, failed: bool = False) -> None:
    """A line shown only at this verbosity or more, dim, on stderr; failed: red,
    as an sbx call that exited non-zero."""
    if verbosity() < level:
        return
    if pretty(True):
        console(True).print(Text(msg, style=ERROR if failed else "dim"))
    else:
        print(msg, file=sys.stderr, flush=True)


def file(what: str, p) -> None:
    """-v: a file og changed on this Mac (`  file  removed ~/…`), as `$ sbx …` is
    each sbx call."""
    detail(f"  file  {what} {path(p)}")


# ── the record: what og changed on this Mac, for `og log` ──

COMMAND = ""        # the og command line this run serves (cli.main sets it)
RECORD_MAX = 1 << 20   # past this many bytes, og.log moves to og.log.1 and starts over


def record_file():
    from ogun.core import paths  # here, not at the top: paths is imported by what log serves
    return paths.state_dir() / "og.log"


def record(what: str) -> None:
    """One line in og's record of changes: when, the command, what changed. JSON
    a line, appended. A record that can't be written never fails the change it
    records: -v says so."""
    import json
    f = record_file()
    line = json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "cmd": COMMAND, "what": plain(what)}, ensure_ascii=False)
    import fcntl
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        # the size check, the rotation and the append under one lock: two og
        # commands at once must not both rotate, the second over the first's
        # og.log.1, losing the history before it
        with open(f.with_name(f.name + ".lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if f.exists() and f.stat().st_size > RECORD_MAX:
                os.replace(f, f.with_name(f.name + ".1"))
            with open(f, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except OSError as e:
        detail(f"  record not written ({path(f)}): {e.strerror}", failed=True)
