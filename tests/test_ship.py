"""ship: og ship, the Mac-side gate for a branch a sandbox can't push (a workflow
change). It trusts nothing the sandbox made: the patch comes through og take, is
applied in a throwaway worktree with hooks off onto a base already on the
remote, every commit is checked by raw mode and bytes (no binary, no submodule —
even one a later commit removes), every commit's patch is paged with control
bytes escaped, and the push happens only on y and only when the tree and commit
count match the request. The checkout is never touched. The requests come from
the real workflow-push-request.sh; a hostile sandbox is played by hand-made
patches that skip it. A local bare repo stands in for GitHub."""

import errno
import os
import pty
import select
import subprocess
import sys

import pytest

from ogun import ship
from ogun.core import paths

REQUEST = paths.SCRIPTS / "workflow-push-request.sh"   # the sandbox half of og ship
ZERO = "0" * 40


class World:
    """gh: GitHub (bare). work: the sandbox's clone, on ci/lint. mac: the
    Mac's clone, where og ship runs. out: the sandbox's out/."""

    def __init__(self, root, out, downloads, og):
        self.root, self.out, self.downloads, self._og = root, out, downloads, og
        self.gh, self.work, self.mac = root / "gh.git", root / "work", root / "mac"

    def git(self, *a, cwd=None, check=True) -> str:
        p = subprocess.run(["git", "-C", str(cwd or self.work), *a], capture_output=True, text=True)
        assert p.returncode == 0 or not check, p.stderr
        return p.stdout.strip()

    def commit(self, msg: str, rel: str, content: str | bytes) -> None:
        f = self.work / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(content if isinstance(content, bytes) else content.encode())
        self.git("add", "-A")
        self.git("commit", "-qm", msg)

    def req(self) -> list[str]:
        """The og ship arguments the request prints for the work branch as it is."""
        p = subprocess.run(["bash", str(REQUEST)], cwd=self.work, capture_output=True, text=True)
        line = next(x for x in p.stdout.splitlines() if x.startswith("  og ship "))
        return line.removeprefix("  og ship ").split()

    def landed(self) -> None:
        subprocess.run(["bash", str(REQUEST), "--landed"], cwd=self.work, capture_output=True, check=True)

    def push(self, answer: str, *args: str) -> tuple[int, str]:
        code, out, err = self._og("ship", *args, stdin=answer + "\n")
        return code, out + err

    def remote_tip(self, branch="ci/lint") -> str:
        return self.git("rev-parse", "-q", "--verify", f"refs/heads/{branch}", cwd=self.gh, check=False)

    def worktrees(self) -> int:
        return len(self.git("worktree", "list", cwd=self.mac).splitlines())


@pytest.fixture
def gh(home, fakes, stand_in, real_git, og, tmp_path, monkeypatch):
    root = tmp_path / "ship"
    out, downloads = home / "exchange/boxes/cub/out", root / "Downloads"
    out.mkdir(parents=True)
    downloads.mkdir(parents=True)
    for k, v in (("OG_EXCHANGE", home / "exchange"), ("OG_TAKE_DEST", downloads), ("WPR_FETCH_URL", root / "gh.git"),
                 ("WPR_OUT_DIR", out), ("SANDBOX_NAME", "cub"), ("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"),
                 ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(k, str(v))
    fakes.sbx.answer(["ls"], stdout="NAME STATUS WORKSPACE\ncub running /x\n")
    stand_in("file", "echo text/plain")
    w = World(root, out, downloads, og)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(w.gh)], check=True)
    subprocess.run(["git", "clone", "-q", str(w.gh), str(w.work)], check=True, capture_output=True)
    w.commit("init", "README", "base\n")
    w.git("push", "-q", "origin", "main")
    w.git("remote", "set-url", "origin", "git@github.com:acme/widgets.git")
    w.git("switch", "-q", "-c", "ci/lint")
    subprocess.run(["git", "clone", "-q", str(w.gh), str(w.mac)], check=True, capture_output=True)
    monkeypatch.chdir(w.mac)

    # no terminal: the y/N comes from stdin, as it does under a pipe with no
    # controlling terminal (the terminal itself is the last case's)
    real_open = open

    def no_tty(f, *a, **k):
        if f == "/dev/tty":
            raise OSError(errno.ENXIO, "no controlling terminal")
        return real_open(f, *a, **k)

    monkeypatch.setattr(ship, "open", no_tty, raising=False)
    return w


def test_y_pushes_github_holds_the_sandboxs_exact_files_the_patch_is_used_up_the_checkout_untouched(gh):
    gh.commit("Lint workflow", ".github/workflows/lint.yml", "on: push\n")
    code, out = gh.push("y", *gh.req())
    assert code == 0 and "pushed origin/ci/lint" in out
    assert gh.git("rev-parse", "ci/lint^{tree}", cwd=gh.gh) == gh.git("rev-parse", "HEAD^{tree}")
    assert list(gh.downloads.iterdir()) == []
    assert gh.git("symbolic-ref", "--short", "HEAD", cwd=gh.mac) == "main"
    assert gh.git("status", "--porcelain", cwd=gh.mac) == "" and gh.worktrees() == 1
    gh.landed()


def test_anything_but_y_pushes_nothing_and_leaves_no_worktree(gh):
    gh.commit("More", "a.txt", "a\n")
    before = gh.remote_tip()
    code, out = gh.push("n", *gh.req())
    assert code != 0 and "not pushed" in out
    assert gh.remote_tip() == before and gh.worktrees() == 1


def test_the_review_pages_every_commits_own_patch_a_line_added_then_removed_is_shown(gh):
    gh.commit("Step one", "s.sh", "echo hidden-step\n")
    gh.commit("Step two", "s.sh", "echo fine\n")
    _, out = gh.push("n", *gh.req())
    assert "+echo hidden-step" in out and "Step one" in out


def test_control_bytes_from_the_sandbox_reach_the_terminal_escaped_never_raw(gh):
    gh.commit("Esc \033[2J subject", "esc.txt", "x\033]0;spoof\007\033[2J\n")
    _, out = gh.push("n", *gh.req())
    assert "^[[2J" in out and "\033" not in out


HOOKS = ("pre-applypatch", "post-applypatch", "applypatch-msg", "pre-push", "post-checkout", "reference-transaction")


def test_hooks_the_patch_adds_under_a_repo_relative_hooks_path_never_run_and_the_push_still_goes(gh):
    gh.git("config", "core.hooksPath", "hooks", cwd=gh.mac)
    for h in HOOKS:
        gh.commit(f"hook {h}", f"hooks/{h}", f'#!/bin/sh\ntouch "{gh.root}/PWNED-{h}"\n')
        (gh.work / "hooks" / h).chmod(0o755)
    gh.git("add", "-A")
    gh.git("commit", "-qm", "exec bits")
    code, _ = gh.push("y", *gh.req())
    assert code == 0
    assert not list(gh.root.glob("PWNED-*"))
    assert gh.git("log", "-1", "--format=%s", "ci/lint", cwd=gh.gh) == "exec bits"
    gh.landed()


def test_a_push_ends_in_one_done_line_the_take_on_the_way_is_a_note(gh):
    gh.commit("One done line", "d.txt", "d\n")
    code, out = gh.push("y", *gh.req())
    assert code == 0 and out.count("✓") == 1
    assert "· took " in out and " from cub, to " in out and "✓ pushed origin/ci/lint" in out
    gh.landed()


def test_a_fetch_git_cant_do_is_ogs_error_then_gits_last_words_as_notes_nothing_pushed(gh):
    gh.commit("No fetch", "f.txt", "f\n")
    a, before = gh.req(), gh.remote_tip()
    gh.git("remote", "set-url", "origin", str(gh.root / "missing.git"), cwd=gh.mac)
    code, out = gh.push("y", *a)
    assert code == 1 and "og ship: git couldn't fetch origin:\n  · " in out and "repository" in out
    assert gh.remote_tip() == before


# a hostile sandbox skips the script: a hand-made patch with the honest request's
# tree and commit count, hiding what a diff can't show in its first commit

@pytest.mark.parametrize(("kind", "said"), [
    ("binary", "binary: tool.bin"),   # in a commit a later one removes
    ("attr", "binary: tool.bin"),     # its own .gitattributes calls it text: raw bytes, never diff attributes
    ("sub", "submodule: vendor/x"),
])
def test_a_hand_made_patch_hiding_a_binary_or_a_submodule_is_refused_nothing_pushed(gh, kind, said):
    b = gh.git("rev-parse", "HEAD")
    gh.commit("One", "one.txt", "1\n")
    gh.commit("Two", "two.txt", "2\n")
    a = gh.req()
    gh.git("switch", "-q", "-c", f"evil-{kind}", b)
    (gh.work / "one.txt").write_text("1\n")
    gh.git("add", "one.txt")
    if kind == "binary":
        (gh.work / "tool.bin").write_bytes(b"\0\1")
        gh.git("add", "tool.bin")
    elif kind == "attr":
        (gh.work / ".gitattributes").write_text("tool.bin diff\n")
        (gh.work / "tool.bin").write_bytes(b"a\0b\n")
        gh.git("add", ".gitattributes", "tool.bin")
    else:
        gh.git("update-index", "--add", "--cacheinfo", f"160000,{b},vendor/x")
    gh.git("commit", "-qm", "One")
    gh.git("rm", "-q", "--cached", "-r", "--ignore-unmatch", "tool.bin", ".gitattributes", "vendor/x")
    for f in ("tool.bin", ".gitattributes"):
        (gh.work / f).unlink(missing_ok=True)
    (gh.work / "two.txt").write_text("2\n")
    gh.git("add", "-A")
    gh.git("commit", "-qm", "Two")
    (gh.out / a[1]).write_text(gh.git("format-patch", "--stdout", "--binary", f"{b}..HEAD") + "\n")
    gh.git("switch", "-q", "ci/lint")
    assert gh.git("rev-parse", f"evil-{kind}^{{tree}}") == gh.git("rev-parse", "HEAD^{tree}")
    before = gh.remote_tip()
    code, out = gh.push("y", *a)
    # og's error first, then each path as a note under it
    assert code != 0 and "nothing was pushed:\n" in out and f"  · {said}" in out.split("nothing was pushed:\n")[1]
    assert gh.remote_tip() == before


def test_a_base_only_on_a_branch_the_remote_has_since_deleted_is_refused(gh):
    m = gh.git("rev-parse", "main", cwd=gh.gh)
    gh.git("switch", "-q", "-c", "old", m)
    gh.commit("gone", "gone.sh", "gone\n")
    gh.git("push", "-q", str(gh.gh), "old")
    gh.git("switch", "-q", "-c", "ci/new")
    gh.commit("n", "n.txt", "n\n")
    gh.git("fetch", "-q", "origin", cwd=gh.mac)
    gh.git("branch", "-q", "-D", "old", cwd=gh.gh)
    # the Mac's clone still has its tracking ref: only asking the remote catches it
    assert gh.git("rev-parse", "-q", "--verify", "refs/remotes/origin/old", cwd=gh.mac)
    b, t, p = gh.git("rev-parse", "old"), gh.git("rev-parse", "HEAD^{tree}"), "hand-made-ci-new.patch"
    (gh.out / p).write_text(gh.git("format-patch", "--stdout", f"{b}..HEAD") + "\n")
    gh.git("switch", "-q", "ci/lint")
    _, out = gh.push("y", "cub", p, "--remote", "origin", "--branch", "ci/new", "--base", b, "--commits", "1", "--tree", t)
    assert "on no live branch" in out and gh.remote_tip("ci/new") == ""


def test_a_patch_whose_commit_count_is_not_the_requests_is_refused_nothing_pushed(gh):
    gh.commit("Real", "r.txt", "r\n")
    a, before = gh.req(), gh.remote_tip()
    a[a.index("--commits") + 1] = "2"
    code, out = gh.push("y", *a)
    assert code != 0 and "refused" in out and gh.remote_tip() == before


def test_a_patch_whose_tree_is_not_the_requests_is_refused_nothing_pushed(gh):
    gh.commit("Real", "r.txt", "r\n")
    a, before = gh.req(), gh.remote_tip()
    a[a.index("--tree") + 1] = gh.git("rev-parse", "HEAD~1^{tree}")
    code, out = gh.push("y", *a)
    assert code != 0 and "refused" in out and gh.remote_tip() == before


def test_the_remote_branch_moved_since_the_request_is_refused_ask_for_a_fresh_one(gh):
    gh.commit("Real", "r.txt", "r\n")
    a = gh.req()
    gh.git("switch", "-q", "-c", "elsewhere", "main")
    gh.commit("someone else", "e.txt", "e\n")
    gh.git("push", "-q", str(gh.gh), "elsewhere:refs/heads/ci/lint")
    moved = gh.remote_tip()
    _, out = gh.push("y", *a)
    assert "has moved since the patch was made" in out and "ask the sandbox for a new one" in out
    assert gh.remote_tip() == moved


@pytest.mark.parametrize(("args", "said"), [
    (["cub", "x.patch", "--remote", "origin", "--branch", "a$(id)"], "--branch needs a plain branch name"),   # git takes it
    (["cub", "../x.patch", "--remote", "origin", "--branch", "b"], "'../x.patch' is not a plain .patch filename"),
])
def test_a_branch_the_shell_would_expand_or_a_patch_path_is_refused_before_anything_runs(gh, fakes, args, said):
    code, out = gh.push("y", *args, "--base", ZERO, "--commits", "1", "--tree", ZERO)
    assert code == 1 and f"og ship: {said}" in out
    assert fakes.sbx.calls == [] and list(gh.downloads.iterdir()) == []


def test_help_is_its_usage_and_takes_nothing_an_unknown_option_or_one_with_no_value_is_usage_exit_1(gh, og):
    gh.commit("Asked about", "h.txt", "h\n")
    a, before = gh.req(), gh.remote_tip()
    code, out, _ = og("ship", *a, "--help")
    assert code == 0 and out.startswith("usage: og ship ") and "Examples:" in out
    assert list(gh.downloads.iterdir()) == []
    for bad in ([*a, "--force", "x"], ["cub", "x.patch", "--remote"]):
        code, _, err = og("ship", *bad, stdin="y\n")
        assert code == 1 and err.startswith("usage: og ship ")
    assert gh.remote_tip() == before and list(gh.downloads.iterdir()) == []


def test_with_a_terminal_the_answer_is_read_there_and_the_prompt_shown_there_never_a_piped_y():
    # a fresh process, never a fork of this one: a test worker has threads, and a
    # forked child of a threaded process can deadlock
    master, slave = pty.openpty()
    child = """import fcntl, sys, termios
fcntl.ioctl(1, termios.TIOCSCTTY, 0)   # the terminal its own: /dev/tty is it
sys.path.insert(0, sys.argv[1])
from ogun import ship
print(f"GOT={ship._answer('push? ')!r}", flush=True)
"""
    p = subprocess.Popen([sys.executable, "-I", "-c", child, str(paths.OGUN / "src")], stdin=subprocess.PIPE,
                         stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    p.stdin.write(b"y\n")   # a y piped in, as a sandbox's line might be
    p.stdin.close()
    os.write(master, b"n\n")
    seen = b""
    while select.select([master], [], [], 10)[0]:
        try:
            chunk = os.read(master, 1024)
        except OSError:   # the child is gone: Linux says EIO
            break
        if not chunk:
            break
        seen += chunk
    p.wait(timeout=10)
    os.close(master)
    text = seen.decode(errors="replace").replace("\r", "")
    assert "push? " in text and "GOT='n'" in text


# ── og ship's parts: its options, the patch, the base, applying, what a diff
#    can't show, and the review ──

SHA, TREE = "a" * 40, "b" * 40
GOOD = ["cub", "x.patch", "--remote", "origin", "--branch", "ci/lint", "--base", SHA, "--commits", "2", "--tree", TREE]


def test_a_requests_options_are_read_in_any_order(gh):
    assert ship.parse(GOOD) == ("cub", "x.patch", "origin", "ci/lint", SHA, "2", TREE)
    assert ship.parse(["cub", "x.patch", *GOOD[10:], *GOOD[2:10]]) == ("cub", "x.patch", "origin", "ci/lint", SHA, "2", TREE)


@pytest.mark.parametrize(("at", "to", "said"), [
    (0, "../cub", "og ship: "), (1, "x.txt", "is not a plain .patch filename"), (3, "a b", "--remote needs a remote's name"),
    (5, "-x", "--branch needs a plain branch name"), (5, "a..b", "--branch needs a plain branch name"),
    (7, "a" * 39, "--base and --tree need full 40-character commit ids"), (11, "B" * 40, "--base and --tree need full"),
    (9, "0", "--commits needs a number, 1 to 9999"), (9, "10000", "--commits needs a number"),
])
def test_each_option_out_of_shape_is_refused_and_said(gh, capfd, at, to, said):
    a = list(GOOD)
    a[at] = to
    assert ship.parse(a) is None and said in "".join(capfd.readouterr())


@pytest.mark.parametrize("args", [GOOD[:3], [*GOOD, "--force", "x"], GOOD[:1]])
def test_an_option_with_no_value_or_none_known_is_usage(gh, capfd, args):
    assert ship.parse(args) is None and "usage: og ship" in "".join(capfd.readouterr())


def test_a_patch_taken_before_is_used_never_taken_again(gh, capfd):
    (gh.downloads / "x.patch").write_text("before\n")
    (gh.out / "x.patch").write_text("new\n")
    assert ship.taken("cub", "x.patch") == gh.downloads / "x.patch"
    assert (gh.out / "x.patch").is_file() and "taken before" in "".join(capfd.readouterr())


def test_a_patch_is_taken_from_the_sandbox_one_not_there_or_a_link_is_refused(gh, capfd):
    (gh.out / "x.patch").write_text("p\n")
    assert ship.taken("cub", "x.patch") == gh.downloads / "x.patch" and not (gh.out / "x.patch").exists()
    assert ship.taken("cub", "none.patch") is None and "could not take none.patch from cub" in "".join(capfd.readouterr())
    (gh.downloads / "l.patch").symlink_to(gh.downloads / "x.patch")
    assert ship.taken("cub", "l.patch") is None and "is not a regular file" in "".join(capfd.readouterr())


def test_a_base_on_the_branch_or_a_live_one_is_on_the_remote_one_it_never_had_isnt(gh, capfd):
    m = gh.git("rev-parse", "main", cwd=gh.gh)
    assert ship.on_remote(str(gh.mac), "origin", "ci/lint", m) is True
    assert ship.on_remote(str(gh.mac), "origin", "main", m) is True
    assert ship.on_remote(str(gh.mac), "origin", "ci/lint", SHA) is False and "is not on origin" in "".join(capfd.readouterr())


@pytest.fixture
def wt(gh, tmp_path):
    """A worktree path for applied() to make, removed after."""
    w = tmp_path / "wt"
    yield str(w)
    gh.git("worktree", "remove", "--force", str(w), cwd=gh.mac, check=False)


def test_a_patch_applied_onto_its_base_matches_the_request_or_is_refused(gh, wt, capfd):
    gh.commit("One", "one.txt", "1\n")
    a = gh.req()
    pf = gh.root / "x.patch"
    pf.write_bytes((gh.out / a[1]).read_bytes())
    _, _, _, _, base, n, tree = ship.parse(a)
    assert ship.applied(str(gh.mac), wt, pf, base, n, tree) is True
    gh.git("worktree", "remove", "--force", wt, cwd=gh.mac)
    assert ship.applied(str(gh.mac), wt, pf, base, "2", tree) is False and "— refused" in "".join(capfd.readouterr())


def test_a_binary_or_a_submodule_any_commit_writes_is_what_a_diff_cant_show(gh):
    b = gh.git("rev-parse", "HEAD")
    gh.commit("Text", "t.txt", "t\n")
    assert ship.unshowable(str(gh.work), b) == []
    gh.commit("Bin", "tool.bin", b"\0\1")
    gh.git("update-index", "--add", "--cacheinfo", f"160000,{b},vendor/x")
    gh.git("commit", "-qm", "Sub")
    gh.git("rm", "-q", "--cached", "tool.bin", "vendor/x")
    gh.git("commit", "-qm", "Gone again")
    assert sorted(ship.unshowable(str(gh.work), b)) == ["binary: tool.bin", "submodule: vendor/x"]


@pytest.mark.parametrize(("said", "pushes"), [("y", True), ("Y", True), ("n", False), ("", False), ("^C", False)])
def test_the_review_pages_the_commits_and_only_y_says_push(gh, monkeypatch, capfd, said, pushes):
    gh.commit("Paged", "p.txt", "p\n")
    paged = []
    monkeypatch.setattr(ship, "_page", paged.append)

    def answer(_):
        if said == "^C":
            raise KeyboardInterrupt
        return said

    monkeypatch.setattr(ship, "_answer", answer)
    assert ship.reviewed(str(gh.work), "origin", "ci/lint", gh.git("rev-parse", "HEAD~1"), "1") is pushes
    assert b"og ship: 1 commit(s) for origin/ci/lint" in paged[0] and b"+p" in paged[0]
    assert ("not pushed" in "".join(capfd.readouterr())) is not pushes


def test_a_broken_link_by_the_patchs_name_is_refused_nothing_taken_on_the_way(gh, capfd):
    (gh.downloads / "x.patch").symlink_to(gh.root / "nowhere")
    (gh.out / "x.patch").write_text("p\n")
    assert ship.taken("cub", "x.patch") is None and "is not a regular file" in "".join(capfd.readouterr())
    assert (gh.out / "x.patch").is_file() and [p.name for p in gh.downloads.iterdir()] == ["x.patch"]
