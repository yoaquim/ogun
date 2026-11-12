"""og's boxes, in the style log.py sets: a callout, a table, columns of rows, a command's
usage box, and `og style`'s preview of every kind of line and box."""

import os
import sys

from rich.console import Group
from rich.padding import Padding
from rich.text import Text

from ogun.core import log


def callout(title: str, lines: list[str], err: bool = False) -> None:
    """A warning that must not scroll past unseen: a block between two rules, its
    title in capitals; on a terminal, bold and orange. Elsewhere the same lines,
    plain."""
    rule = "─" * 60
    if not log.pretty(err):
        out = sys.stderr if err else sys.stdout
        print(f"{rule}\n {log.WARNING} {title}\n{rule}", file=out)
        for line in lines:
            print(f" {line}", file=out)
        print(rule, file=out, flush=True)
        return
    c = log.console(err)
    c.print(Text(f"{rule}\n {log.WARNING} {title}\n{rule}", style=f"bold {log.CALLOUT}"))
    for line in lines:
        c.print(Text(f" {line}", style=log.CALLOUT))
    c.print(Text(rule, style=f"bold {log.CALLOUT}"))


def _box(title: str, body, err: bool = False) -> None:
    """The one box og draws on a terminal, for a usage, a summary or a list:
    rounded, og's color, its title (`og <cmd>`) in the top border, as wide as
    what's in it, never wider than BOX_WIDTH or the terminal. (usage() draws it at
    a fixed width, so its text wraps to a steady measure.)"""
    from rich.panel import Panel
    from rich.theme import Theme
    c = log.wrapping(err)
    c.width = min(c.width, log.BOX_WIDTH)
    with c.use_theme(Theme({"ok": log.OK, "warn": log.WARN, "error": log.ERROR})):
        c.print(Panel(body, title=Text(title, style="bold") if title else None, title_align="left",
                      border_style=log.OG, padding=(1, 2), expand=False))


def table(title: str, rows: list[tuple[str, str]]) -> None:
    """A two-column summary at the end of a command of several steps, in og's
    box, on a terminal only: elsewhere the lines above it already said the same
    thing, and a table would break their greps. A value may start with a state
    mark and use the marks' colors: [ok]✓ applied[/], [warn]…[/], [error]…[/]."""
    if not log.pretty() or not rows:
        return
    from rich.table import Table
    t = Table(show_header=False, box=None, padding=(0, 3, 0, 0), pad_edge=False)
    t.add_column(style=f"bold {log.OG}", no_wrap=True)
    t.add_column()
    for k, v in rows:
        t.add_row(k, Text.from_markup(v) if "[" in v else Text(v))
    log.console(False).print()   # set apart from the steps above: the summary is read on its own
    _box(title, t)


def columns(headers: list[str], rows: list[list[str]], state: int | None = None, title: str = "",
            quiet: tuple[int, ...] = (), tags: tuple[int, ...] = (), foot: str = "",
            marks: dict[str, tuple[str, str]] | None = None, rest=None) -> None:
    """The table format (`og ls`), on stdout. On a terminal: a box like a
    command's usage, titled `og <title>`, with a rule under the column names, the
    first column bold, the state column (that index) with its mark and color
    (STATES), the quiet columns dim (the same on every row, or background), the
    tags columns lavender, a row at rest dim, below how many are in each state,
    and foot, a line the table needs read with it. No rows: the box says so.
    A state is its first word (`blocked (POST)` is blocked); marks overrides
    STATES for this table (("", "") leaves a state plain); rest(row) says a row
    is at rest, where a stopped one always is.
    Elsewhere: the same words, aligned by spaces, no marks and no box, so
    `awk '{print $3}'` reads the state, then foot."""
    if not log.pretty():
        if rows:
            w = [max(len(r[i]) for r in [headers, *rows]) for i in range(len(headers))]
            for r in [headers, *rows]:
                print("  ".join(c.ljust(w[i]) for i, c in enumerate(r)).rstrip())
        if foot:
            print(log.plain(foot))
        sys.stdout.flush()
        return
    from rich import box
    from rich.table import Table
    t = Table(box=box.SIMPLE_HEAD, padding=(0, 3, 0, 0), pad_edge=False, show_edge=False,
              header_style=f"bold {log.OG}", border_style=log.OG)
    for i, h in enumerate(headers):
        t.add_column(h, style="dim" if i in quiet else "bold" if i == 0 else log.TAG if i in tags else "", no_wrap=True)
    states = log.STATES | (marks or {})
    counts: dict[str, int] = {}
    for r in rows:
        cells, at_rest = [Text(c) for c in r], bool(rest and rest(r))
        if state is not None:
            word = r[state].lower().split(" (")[0]
            counts[word] = counts.get(word, 0) + 1
            if word in states:
                mark, style = states[word]
                cells[state] = Text(f"{mark} {r[state]}".lstrip(), style=style)
                at_rest |= word == "stopped"
        t.add_row(*cells, style="dim" if at_rest else None)
    parts = [t]
    if counts:
        tally = Text()
        for n, (word, k) in enumerate(sorted(counts.items(), key=lambda x: -x[1] if x[0] != "running" else -10**9)):
            mark, style = states.get(word, ("", ""))
            tally.append(" · " if n else "", style="dim")
            tally.append(f"{mark} {k} {word}".strip(), style=style)
        parts += [Text(""), tally]
    if not rows:
        parts = [Text("nothing here", style="dim")]
    if foot:
        line = Text()
        for i, part in enumerate(foot.replace(log.CMD_CLOSE, log.CMD_OPEN).split(log.CMD_OPEN)):
            line.append(part, style=f"bold {log.OG}" if i % 2 else "dim")
        parts += [Text(""), line]
    _box(f"og {title}" if title else "", Group(*parts))


def usage(cmd: str, line: str, about: str, forms: list[tuple[str, str]],
          notes: list[str] = (), examples: list[str] = (), problem: str = "", err: bool = True) -> None:
    """A command's usage. On a terminal: what went wrong (problem), then a box with
    what the command is for, each form beside what it does, and real examples.
    Elsewhere: the one `usage: og <cmd> …` line a wrong call prints, or
    (asked for help, no problem) the same content as plain lines."""
    if not log.pretty(err):
        out = sys.stderr if err else sys.stdout
        if problem:
            print(f"usage: og {cmd} {line}".rstrip(), file=out, flush=True)
            return
        print(f"usage: og {cmd} {line}".rstrip() + f"\n\n{about}\n", file=out)
        for f, what in forms:
            print(f"  {f}\n      {what}", file=out)
        for n in notes:
            print(f"\n{n}", file=out)
        if examples:
            print("\nExamples:", file=out)
            for e in examples:
                print(f"  {e}", file=out)
        out.flush()
        return
    from rich.panel import Panel
    from rich.table import Table
    c = log.wrapping(err)
    if problem:
        c.print(Text(f"{log.FAILED} ", style=f"bold {log.ERROR}") + Text(problem, style=log.ERROR))
        c.print()   # a line between what went wrong and the box, so each reads on its own
    width = min(c.width, log.BOX_WIDTH)
    # two columns only when the forms fit with room for what each does (borders and
    # padding take 6); narrower, as in a split pane, each form above what it does,
    # so a description never ends up with no width
    if width - 6 >= max(len(f) for f, _ in forms) + 3 + 20:
        grid = Table.grid(padding=(0, 3))
        grid.add_column(style=f"bold {log.OG}", no_wrap=True)
        grid.add_column(style="")
        for f, what in forms:
            grid.add_row(f, what)
    else:
        grid = Group(*[Group(Text(f, style=f"bold {log.OG}", overflow="fold"), Padding(Text(what), (0, 0, 0, 4))) for f, what in forms])
    parts = [Text(about), Text(""), grid]
    for n in notes:
        parts += [Text(""), Text(n, style="dim")]
    if examples:
        parts += [Text(""), Text("Examples", style="bold")]
        parts += [Text("  " + e, style=log.EXAMPLE, overflow="fold") for e in examples]
    c.print(Panel(Group(*parts), title=Text(f"og {cmd}", style="bold"), title_align="left",
                  border_style=log.OG, padding=(1, 2), width=width))


def preview() -> None:
    """`og style`: every pattern above, drawn, for checking a change to the look."""
    log.step("a step: what og is doing now")
    log.note("a fact under it, worth seeing every time")
    log.ok("done: what you asked for, finished", "a detail, dim")
    log.warn(f"  {log.WARNING} needs a look: yellow, saying what's wrong", fix=f"{log.cmd('og net cub docs.example.com --rm')}   ← the fix, on its own line")
    log.err("og style: failed or refused — red, on stderr, the reason and then the fix")
    old = os.environ.get("OG_VERBOSE")
    os.environ["OG_VERBOSE"] = "2"
    log.detail("  $ sbx policy ls --wide --type network")
    log.detail("    ↳ exit 0 · 41 ms")
    log.detail("    out│ what sbx printed (-vv)", level=2)
    if old is None:
        os.environ.pop("OG_VERBOSE")
    else:
        os.environ["OG_VERBOSE"] = old
    callout("A CALLOUT", ["a warning that must not scroll past unseen", "each line in orange"])
    table("og style", [("done", f"[ok]{log.DONE} applied[/]"), ("needs a look", f"[warn]{log.WARNING} 1 to remove[/] (above)"),
                        ("failed", f"[error]{log.FAILED} not off yet[/] (above)"), ("plain", "3 sandboxes")])
    columns(["SANDBOX", "AGENT", "STATUS"], [["cub", "claude", "running"], ["web", "-", "stopped"]], state=2, title="ls")
    log.section("a section: a heading over the lines below it")
    log.info("a line replayed with the time it happened (og log): plain, no mark", clock="14:07:51")
    log.aside("og rm web --force    ← an aside: dim, beneath, where the line's text starts")
    usage("style", "", "What every og command looks like (docs/appendix/ogun-style.md).",
          [("og style", "draws each pattern, as on a terminal"), ("og style | cat", "the same, as a pipe sees it")],
          notes=["A note: dim, below the forms."], examples=["og style"], err=False)
