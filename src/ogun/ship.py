"""`og ship`: push a branch a sandbox can't (its token has no workflow
permission: docs/secrets.md), from the repo in the current directory. The
sandbox prints the line (workflow-push-request.sh); everything on
it, and the patch, is the sandbox's, so this is the gate and trusts none of it:
the patch is applied in a throwaway worktree with every git hook off, onto a
base that must already be on the remote; any commit that adds a binary blob or
a submodule is refused, since a diff can't show what either runs; every
commit's own patch (not only the net diff: content added and later removed
still goes up in history) is paged with control bytes escaped; and it pushes
only on your y, only if HEAD is exactly the tree and commit count the sandbox
announced. Your checkout and branches are never touched."""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ogun.core import boxes, log, naming
from ogun.core.log import shown
from ogun.exchange import screen, take

SHIP_USAGE = "<name> <patch> --remote <r> --branch <b> --base <sha> --commits <n> --tree <sha>"
SHIP_HELP = dict(
    about="From your clone: push a branch a sandbox couldn't (a workflow change), after you read every commit.",
    forms=[
        (f"og ship {SHIP_USAGE}", "take the patch, apply it in a throwaway worktree with hooks off, page every commit, push on your y"),
    ],
    notes=["The sandbox prints the whole line (workflow-push-request.sh). A binary or a submodule in any commit "
           "is refused, and so is a patch whose tree or commit count isn't the one the line names."],
    examples=["og ship cub workflow-ci-lint.patch --remote origin --branch ci/lint --base <sha> --commits 1 --tree <sha>"],
)

_OPTS = ("--remote", "--branch", "--base", "--commits", "--tree")
_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_SHA = re.compile(r"[0-9a-f]{40}")
_COUNT = re.compile(r"[1-9][0-9]{0,3}")
_ZEROS = re.compile(r"0+")


def usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("ship", SHIP_USAGE, problem=problem, err=err, **SHIP_HELP)


def escaped(b: bytes) -> bytes:
    """Bytes as `cat -v` shows them: a control byte as ^X, DEL as ^?, a high
    byte as M- and the same, so a file or a subject from the sandbox can't
    drive the terminal. Newline and tab stay."""
    out = bytearray()
    for c in b:
        high = c >= 128
        if high:
            out += b"M-"
            c -= 128
        if c in (9, 10) and not high:
            out.append(c)
        elif c < 32:
            out += b"^" + bytes([c + 64])
        elif c == 127:
            out += b"^?"
        else:
            out.append(c)
    return bytes(out)


def _git(*args: str, cwd=None, out: bool = True) -> subprocess.CompletedProcess:
    # every git call with hooks off: a repo-relative core.hooksPath would run
    # hooks the patch itself adds
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *(["-C", str(cwd)] if cwd else []), *args],
                          stdout=subprocess.PIPE if out else subprocess.DEVNULL, stderr=subprocess.PIPE)


def _said(text: bytes, last: int | None = None) -> None:
    """What git printed (or a list og made of the sandbox's paths), under og's
    error: a note a line on stderr, escaped as the review is; last: only the
    last lines, for a call whose output runs long."""
    lines = [x for x in escaped(text).decode("ascii", "replace").splitlines() if x.strip()]
    for line in lines[-last:] if last else lines:
        log.note(line.strip(), err=True)


def _git_said(p: subprocess.CompletedProcess, last: int | None = None) -> None:
    _said((p.stdout or b"") + (p.stderr or b""), last)


def _answer(prompt: str) -> str:
    """The y/N, from the terminal when there is one: stdin may be the pipe the
    line came in on. The prompt shows only where someone reads it."""
    try:
        # a handle each way: a terminal can't seek, so one opened "r+" fails,
        # and the failure would read as no terminal at all
        with open("/dev/tty") as tin, open("/dev/tty", "w") as tout:
            tout.write(prompt)
            tout.flush()
            return tin.readline().strip()
    except OSError:
        if sys.stdin.isatty():
            sys.stderr.write(prompt)
            sys.stderr.flush()
        return (sys.stdin.readline() or "").strip()


def _page(b: bytes) -> None:
    less = shutil.which("less")
    if less:
        subprocess.run([less], input=b)
    else:
        sys.stdout.buffer.write(b)
        sys.stdout.flush()


def ship(argv: list[str]) -> int:
    req = parse(argv)
    if req is None:
        return 1
    name, patch, remote, branch, base, n, tree = req
    p = _git("rev-parse", "--show-toplevel")
    if p.returncode != 0:
        log.err("og ship: run it inside your clone of the repo")
        return 1
    top = p.stdout.decode().strip()
    if _git("remote", "get-url", remote, out=False).returncode != 0:
        log.err(f"og ship: this repo has no remote '{remote}'")
        return 1
    pf = taken(name, patch)
    if pf is None or not on_remote(top, remote, branch, base):
        return 1
    wt = tempfile.mkdtemp(prefix="ogun-push.")
    try:
        return _apply_and_push(top, wt, pf, remote, branch, base, n, tree)
    finally:
        _git("worktree", "remove", "--force", wt, cwd=top, out=False)
        shutil.rmtree(wt, ignore_errors=True)


def parse(argv: list[str]) -> tuple[str, str, str, str, str, str, str] | None:
    """The request's sandbox, patch, remote, branch, base, commit count and
    tree, each checked for its shape before anything runs; None, said, when one
    is out of it."""
    if len(argv) < 2 or not argv[0] or not argv[1]:
        usage("og ship needs a sandbox, a patch and the line's options")
        return None
    name, patch, rest = argv[0], argv[1], argv[2:]
    opt = dict.fromkeys(_OPTS, "")
    while rest:
        if len(rest) < 2 or rest[0] not in _OPTS:
            usage(f"og ship has no option {rest[0]}" if rest[0] not in _OPTS else f"og ship: {rest[0]} needs a value")
            return None
        opt[rest[0]], rest = rest[1], rest[2:]
    remote, branch, base, n, tree = (opt[o] for o in _OPTS)
    if not naming.name_chars(name):
        naming.bad_name("ship", name)
        return None
    if not (patch.endswith(".patch") and naming.name_chars(patch)):
        log.err(f"og ship: '{shown(patch)}' is not a plain .patch filename")
        return None
    if not naming.name_chars(remote):
        log.err("og ship: --remote needs a remote's name, like origin")
        return None
    if not (_BRANCH.fullmatch(branch) and _git("check-ref-format", "--branch", branch).returncode == 0):
        log.err("og ship: --branch needs a plain branch name: letters, digits, . _ / -")
        return None
    if not (_SHA.fullmatch(base) and _SHA.fullmatch(tree)):
        log.err("og ship: --base and --tree need full 40-character commit ids")
        return None
    if not _COUNT.fullmatch(n):
        log.err("og ship: --commits needs a number, 1 to 9999")
        return None
    return name, patch, remote, branch, base, n, tree


def taken(name: str, patch: str) -> Path | None:
    """The patch in Downloads: taken from the sandbox, unless it was taken
    before; a file of that name from anywhere else would be applied in its
    place, so an existing one must be the one asked for."""
    pf = screen.take_dest() / patch
    if pf.exists() or pf.is_symlink():
        log.note(f"using {log.path(pf)}, taken before; to take a fresh copy, delete it first")
    elif take.take([name, patch], quiet=True) != 0:   # quiet: og ship ends in one done line, the push
        log.err(f"og ship: could not take {patch} from {name}")
        return None
    if not pf.is_file() or pf.is_symlink():
        log.err(f"og ship: {log.path(pf)} is not a regular file")
        return None
    return pf


def on_remote(top: str, remote: str, branch: str, base: str) -> bool:
    """The base is the branch's tip on the remote now, or, for a new branch,
    on a branch the remote has now; said when it isn't."""
    p = _git("fetch", "-q", remote, cwd=top, out=False)
    if p.returncode != 0:
        log.err(f"og ship: git couldn't fetch {remote}:")
        _git_said(p, last=3)
        return False
    if _git("cat-file", "-e", f"{base}^{{commit}}", cwd=top).returncode != 0:
        log.err(f"og ship: base {base[:12]} is not on {remote}")
        return False
    # the base must be on a branch the remote has NOW: a remote-tracking ref
    # outlives its deleted branch (fetch doesn't prune), and a base from that
    # history would push code that was never paged — so ask the remote, not refs/remotes
    p = _git("ls-remote", "--heads", remote, cwd=top)
    if p.returncode != 0:
        log.err(f"og ship: git couldn't list {remote}'s branches:")
        _git_said(p, last=3)
        return False
    live = [line.split() for line in p.stdout.decode().splitlines() if len(line.split()) == 2]
    tip = next((h for h, r in live if r == f"refs/heads/{branch}"), "")
    if tip and tip != base:
        log.err(f"og ship: {remote}/{branch} has moved since the patch was made ({tip[:12]}, not {base[:12]}); ask the sandbox for a new one")
        return False
    if not tip and not any(_git("merge-base", "--is-ancestor", base, h, cwd=top).returncode == 0 for h, _ in live):
        log.err(f"og ship: base {base[:12]} is on no live branch of {remote} — refused")
        return False
    return True


def _apply_and_push(top: str, wt: str, pf: Path, remote: str, branch: str, base: str, n: str, tree: str) -> int:
    if not applied(top, wt, pf, base, n, tree):
        return 1
    bad = unshowable(wt, base)
    if bad:
        log.err("og ship: a diff can't show what these run, so nothing was pushed:")
        _said("\n".join(bad).encode("utf-8", "surrogateescape"))
        return 1
    if not reviewed(wt, remote, branch, base, n):
        return 1
    p = _git("push", "-q", remote, f"HEAD:refs/heads/{branch}", cwd=wt, out=False)
    if p.returncode != 0:
        log.err(f"og ship: git couldn't push, so nothing changed on {remote}:")
        _git_said(p, last=3)
        return 1
    log.ok(f"pushed {remote}/{branch}", "tell the sandbox, which then runs: workflow-push-request.sh --landed")
    log.record(f"pushed {remote}/{branch}, {n} commit(s) from a sandbox's patch")
    pf.unlink(missing_ok=True)
    return 0


def applied(top: str, wt: str, pf: Path, base: str, n: str, tree: str) -> bool:
    """The patch applied in a worktree at the base, giving the request's commit
    count and tree; said when it doesn't."""
    p = _git("worktree", "add", "-q", "--detach", wt, base, cwd=top)
    if p.returncode != 0:
        log.err("og ship: git couldn't make a worktree at the base:")
        _git_said(p)
        return False
    p = _git("am", "-q", "--empty=keep", str(pf), cwd=wt)
    if p.returncode != 0:
        log.err(f"og ship: the patch doesn't apply onto {base[:12]}; nothing was pushed:")
        _git_said(p)
        _git("am", "--abort", cwd=wt, out=False)
        return False
    got_n = _git("rev-list", "--count", f"{base}..HEAD", cwd=wt).stdout.decode().strip()
    got_tree = _git("rev-parse", "HEAD^{tree}", cwd=wt).stdout.decode().strip()
    if got_n != n or got_tree != tree:
        log.err(f"og ship: the patch gives {got_n} commit(s), tree {got_tree[:12]}; the request said {n}, {tree[:12]} — refused")
        return False
    return True


def unshowable(wt: str, base: str) -> list[str]:
    """Each binary or submodule any commit since the base writes, even one a
    later commit removes: every blob by its raw mode and bytes — never through
    diff attributes, which the patch itself can set (.gitattributes)."""
    raw = _git("log", "--format=", "--raw", "--no-abbrev", "--no-renames", "-r", f"{base}..HEAD", cwd=wt).stdout
    bad, seen = [], set()
    for line in raw.decode("utf-8", "surrogateescape").splitlines():
        meta, _, path = line.removeprefix(":").partition("\t")
        f = meta.split()
        if len(f) < 4:
            continue
        nm, ns = f[1], f[3]
        if nm == "160000":
            bad.append(f"submodule: {path}")
            continue
        if _ZEROS.fullmatch(ns) or ns in seen:
            continue
        seen.add(ns)
        if nm in ("100644", "100755") and b"\0" in _git("cat-file", "blob", ns, cwd=wt).stdout:
            bad.append(f"binary: {path}")
    return bad


def reviewed(wt: str, remote: str, branch: str, base: str, n: str) -> bool:
    """Each commit's own patch paged, oldest first, bytes escaped; then only y
    pushes."""
    head = (f"og ship: {n} commit(s) for {remote}/{branch}, onto {base[:12]}. Read every commit: CI runs\n"
            f"whatever the workflows call, and scripts already on {remote} are not shown here.\n\n").encode()
    review = _git("log", "-p", "--reverse", "--text", "--stat", "--no-color", "--no-ext-diff", "--no-textconv",
                  "--no-renames", "--format=fuller", f"{base}..HEAD", cwd=wt).stdout
    _page(escaped(head + review))
    try:
        ans = _answer(f"push these {n} commit(s) to {remote}/{branch}? [y/N] ")
    except KeyboardInterrupt:   # ^C at the prompt is a no; the worktree still goes
        ans = ""
        print(file=sys.stderr)
    if ans not in ("y", "Y"):
        log.info("og ship: not pushed")
        return False
    return True
