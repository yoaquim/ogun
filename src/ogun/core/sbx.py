"""Every sbx command og runs goes through here, so `og -v` can show each one:
the command, how it ended and how long it took, and at `-vv` what it printed."""

import shlex
import subprocess
import time

from ogun.core import log


def _short(arg: str) -> str:
    """An argument as -v shows it: a script sent to run inside a sandbox is a
    line count, not its text."""
    return f"<script, {arg.count(chr(10)) + 1} lines>" if "\n" in arg else arg


HIDDEN = "<the value, not shown>"


def redact(text: str, hide: str) -> str:
    """text with a secret in it not shown: the whole value, then each of its
    lines (a multi-line key sbx echoed in part, or split across its own lines).
    Run on a whole stream before it's split into lines, or no line matches."""
    if not hide:
        return text
    text = text.replace(hide, HIDDEN)
    for part in sorted({x.strip() for x in hide.splitlines()}, key=len, reverse=True):
        if len(part) >= 4:   # shorter, and every "-" or "ab" in the output would go
            text = text.replace(part, HIDDEN)
    return text


def run(*args: str, show: bool = False, timeout: float | None = None, cap: int | None = None,
        wait: str = "", input: bytes | None = None, stdin=None, hide: str = "") -> subprocess.CompletedProcess:
    """Run `sbx <args>`. show: sbx's output and prompts go to the terminal.
    Otherwise output is captured, stdin is input/stdin or nothing, and a
    terminal shows a spinner with wait. timeout: seconds, then killed (exit 124,
    as GNU timeout). cap: keep at most that many bytes of stdout. hide: a secret
    in the arguments, which -v shows as not shown."""
    cmd = ["sbx", *args]

    log.detail(f"  $ {shlex.join(HIDDEN if hide and a == hide else _short(a) for a in cmd)}")
    t0 = time.monotonic()
    try:
        # show: sbx gets the terminal's input, as if run by hand; otherwise none,
        # so a question sbx asks ends instead of waiting unseen.
        # Captured as bytes, decoded below: text mode turns \r\n into \n, and
        # the ssh-agent check must see exactly what sbx printed.
        try:
            if show:   # sbx's own words and questions: no spinner over them
                p = subprocess.run(cmd, timeout=timeout)
            else:
                feed = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL if stdin is None else stdin}
                with log.waiting(wait or f"sbx {' '.join(args[:2])}"):
                    p = subprocess.run(cmd, capture_output=True, timeout=timeout, **feed)
        except subprocess.TimeoutExpired as e:   # run() has killed it
            p = subprocess.CompletedProcess(cmd, 124, e.stdout, e.stderr)
        if cap is not None:
            p.stdout = (p.stdout or b"")[:cap]
        p.stdout = (p.stdout or b"").decode("utf-8", "replace")
        p.stderr = (p.stderr or b"").decode("utf-8", "replace")
    except FileNotFoundError:
        p = subprocess.CompletedProcess(cmd, 127, "", "sbx: command not found\n")
        if show:
            log.err("sbx: command not found")
    if p.returncode == 0 and args in (("ls",), ("ls", "--all")):
        _remember(names(p.stdout or ""))
    elif p.returncode == 0 and args[:1] == ("rm",) and len(args) > 1:
        _forget(args[1])
    ms = int((time.monotonic() - t0) * 1000)
    log.detail(f"    ↳ exit {p.returncode} · {ms} ms" + (" (timed out)" if p.returncode == 124 and timeout else ""),
               failed=p.returncode != 0)
    if args[:1] == ("secret",):
        # what sbx says about secrets can hold part of one (a pasted value's first
        # letters, in secret ls): -vv says that it's left out, never what it was
        if p.stdout or p.stderr:
            log.detail("    out│ (sbx secret's output isn't shown: it can hold part of a secret)", level=2)
        return p
    for name, text in (("out", p.stdout), ("err", p.stderr)):
        for line in redact(text or "", hide).splitlines():
            log.detail(f"    {name}│ {line}", level=2)
    return p


# ── the sandbox names tab completion offers: what sbx last listed, kept by og ──

def names_file():
    """Read by tab completion (the shell's _og_comp_names), so a Tab never
    asks the sandbox daemon: what the last `sbx ls` og ran listed, less what og
    removed since."""
    from ogun.core import paths  # here: paths would otherwise load with every sbx call
    return paths.state_dir() / "sandbox-names"


def _remember(names_: list[str]) -> None:
    from ogun.core import files
    f = names_file()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        files.write_text(f, "".join(n + "\n" for n in names_))
    except OSError:
        pass   # completion falls back to asking sbx


def remember_one(name: str) -> None:
    """A sandbox just made, added: a create with --no-attach lists nothing after it.
    No file yet: nothing to add to (completion asks sbx, which has it)."""
    f = names_file()
    try:
        have = f.read_text().splitlines()
    except OSError:
        return
    if name not in have:
        _remember([*have, name])


def _forget(name: str) -> None:
    f = names_file()
    try:
        _remember([n for n in f.read_text().splitlines() if n != name])
    except OSError:
        pass


def ls() -> str | None:
    """`sbx ls`'s table, or None when sbx didn't answer."""
    p = run("ls")
    return p.stdout if p.returncode == 0 else None


def names(listing: str) -> list[str]:
    return [line.split()[0] for line in listing.splitlines()[1:] if line.split()]


def exists(name: str) -> bool | None:
    """Whether sbx has this sandbox; None when sbx didn't answer, which is never
    "no such sandbox"."""
    out = ls()
    return None if out is None else name in names(out)


def workspace(name: str, listing: str) -> str:
    """A sandbox's primary workspace from `sbx ls`: the first field of its row
    that starts with "/" (the PORTS column can hold "/tcp"), without a trailing
    comma."""
    for line in listing.splitlines():
        f = line.split()
        if f and f[0] == name:
            for x in f[1:]:
                if x.startswith("/"):
                    return x.removesuffix(",")
            return ""
    return ""


def said(p: subprocess.CompletedProcess, hide: str = "") -> None:
    """What sbx printed, under og's error for a call that failed: a note a line
    on stderr, both streams, control bytes escaped and a secret in it (hide) not
    shown. Not for `sbx secret` output unless hide covers all it could hold (a
    pasted value): run() keeps that out of -vv for the same reason."""
    for line in redact((p.stdout or "") + (p.stderr or ""), hide).splitlines():
        if line.strip():
            log.note(log.shown(line.strip()), err=True)


def tail(p: subprocess.CompletedProcess, n: int = 3) -> list[str]:
    lines = ((p.stdout or "") + (p.stderr or "")).splitlines()
    return [f"    {line}" for line in lines[-n:]]
