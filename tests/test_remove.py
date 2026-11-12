"""remove: og rm, and --if-clean, which removes a sandbox only when nothing would
be lost: unsaved work, or a sandbox that doesn't answer the check, keeps it
(`kept: <why>`, exit 3, sbx rm never run); one already gone has its leftovers
cleaned. og's record of changes (og log), and the check that runs inside
the sandbox (unsafe-probe.sh), run here against real git."""

import json
import os
import re
import shutil
import subprocess

import pytest

from ogun.core import paths
from ogun.exchange import folders
from ogun.sandbox import remove

PROBE = remove.PROBE


@pytest.fixture
def sb(home, fakes, monkeypatch):
    """sbx listing run1 running and stop1 stopped (gone1 never); its exec answering
    the check as given; its rm needing --force past its y/N, refusing a name it
    doesn't know."""
    e = home / "exchange"
    e.mkdir()
    monkeypatch.setenv("SBX_EXCHANGE", str(e))

    def set_(out="", code=0, delay=0, ls_fail=False, marked=False, rm_fail=False, cp=None):
        s = fakes.sbx
        s.clear()
        st = ("● running", "○ stopped") if marked else ("running", "stopped")
        s.answer(["ls"], stdout=f"NAME     STATUS   WORKSPACE\nrun1     {st[0]}  /w\nstop1    {st[1]}  /w\n", code=1 if ls_fail else 0)
        s.answer(["exec"], stdout=out and out + "\n", code=code, delay=delay)
        for n in ("run1", "stop1"):
            if rm_fail:
                s.answer(["rm", n], stdout=f"Removing sandbox {n} (sbx's own words)\n", stderr="error: it is busy\n", code=1)
            s.answer(["rm", n], stdout=f"Removing sandbox {n} (sbx's own words)\n", has="--force")
            s.answer(["rm", n], code=1)
        s.answer(["rm"], stderr="error: sandbox not found\n  try: sbx ls\n", code=1)
        if cp:
            s.answer(["cp"], **cp)
        return s

    set_()
    return e, set_


def box(name):
    assert folders.dirs(name) == ""


def boxed(e, name) -> bool:
    return (e / "boxes" / name).is_dir()


def rms(s) -> list[list[str]]:
    return [c for c in s.calls if c[:1] == ["rm"]]


def checks(s) -> list[list[str]]:
    return [[c[1], c[-1]] for c in s.calls if c[:1] == ["exec"]]


# ── --if-clean ──

def test_clean_is_removed_with_force_and_its_box_goes(og, sb):
    e, set_ = sb
    s = set_()
    box("run1")
    assert og("rm", "run1", "--if-clean")[0] == 0
    assert ["rm", "run1", "--force"] in rms(s) and not boxed(e, "run1") and checks(s) == [["run1", "--idle-ok"]]


def test_unsaved_work_is_kept_the_reasons_on_one_line_exit_3_sbx_rm_never_run(og, sb):
    e, set_ = sb
    s = set_(out="/w: 2 unpushed commit(s)\n/w: 1 uncommitted/untracked file(s)")
    box("run1")
    code, out, err = og("rm", "run1", "--if-clean")
    assert code == 3 and (out + err).strip() == "kept: /w: 2 unpushed commit(s); /w: 1 uncommitted/untracked file(s)"
    assert rms(s) == [] and boxed(e, "run1")


def test_a_sandbox_that_doesnt_answer_the_check_is_kept_never_guessed_clean(og, sb):
    e, set_ = sb
    s = set_(code=1)
    box("run1")
    code, out, err = og("rm", "run1", "--if-clean")
    assert code == 3 and (out + err).startswith("kept: it did not answer") and rms(s) == [] and boxed(e, "run1")


def test_already_gone_no_check_its_box_cleaned_exit_0(og, sb):
    e, set_ = sb
    s = set_()
    box("gone1")
    assert og("rm", "gone1", "--if-clean")[0] == 0 and not boxed(e, "gone1") and checks(s) == []


@pytest.mark.parametrize("args", [["run1", "--force", "--if-clean"], ["run1", "--bogus"]])
def test_force_with_if_clean_or_an_unknown_flag_is_usage_and_removes_nothing(og, sb, args):
    _, set_ = sb
    s = set_()
    assert og("rm", *args)[0] == 1 and s.calls == []


def test_a_stopped_sandbox_is_asked_only_its_git_also_when_a_newer_sbx_marks_its_status(og, sb):
    _, set_ = sb
    for marked in (False, True):
        s = set_(marked=marked)
        n = len(s.calls)
        box("stop1")
        assert og("rm", "stop1", "--if-clean")[0] == 0
        assert [[c[1], c[-1]] for c in s.calls[n:] if c[:1] == ["exec"]] == [["stop1", "--stopped"]]


def test_the_check_is_told_the_sandboxs_workspace_before_its_mode(og, sb):
    _, set_ = sb
    s = set_()
    n = len(s.calls)
    assert og("rm", "run1", "--if-clean")[0] == 0
    assert [c[-3:] for c in s.calls[n:] if c[:1] == ["exec"]] == [["--root", "/w", "--idle-ok"]]


def test_a_plain_rm_tells_the_check_the_workspace_too(sb):
    _, set_ = sb
    s = set_()
    remove.unsafe_reasons("run1")
    assert [c[-2:] for c in s.calls if c[:1] == ["exec"]] == [["--root", "/w"]]


def test_an_sbx_that_cant_list_keeps_it_gone_is_proven_never_assumed(og, sb):
    e, set_ = sb
    s = set_(ls_fail=True)
    box("run1")
    code, out, err = og("rm", "run1", "--if-clean")
    assert code == 3 and (out + err).startswith("kept: sbx ls did not answer") and boxed(e, "run1")
    assert [c for c in s.calls if c[:1] != ["ls"]] == []


def test_a_check_past_its_time_limit_keeps_it_exit_124_sbx_rm_never_run(og, sb, monkeypatch):
    e, set_ = sb
    monkeypatch.setenv("SBX_RM_PROBE_TIMEOUT", "1")
    s = set_(delay=5)
    box("run1")
    code, out, err = og("rm", "run1", "--if-clean")
    assert code == 3 and (out + err).strip() == "kept: it did not answer the check for unsaved work (exit 124)"
    assert rms(s) == [] and boxed(e, "run1")


def test_help_anywhere_in_rm_is_help_and_removes_nothing(og, sb):
    e, set_ = sb
    s = set_()
    box("run1")
    code, out, _ = og("rm", "run1", "--force", "--help")
    assert code == 0 and out.startswith("usage: og rm ") and s.calls == [] and boxed(e, "run1")


# ── a plain rm ──

def test_a_plain_rm_with_unsaved_work_refuses_the_fix_first_each_reason_a_note(og, sb):
    e, set_ = sb
    s = set_(out="/w: 1 unpushed commit(s)")
    box("run1")
    code, out, err = og("rm", "run1")
    o = out + err
    assert code == 1 and re.search(r"'run1' has work that would be lost.*og rm run1 --force", o, re.S)
    assert "  · /w: 1 unpushed commit(s)" in o and "  · to fetch its commits on the host: git fetch sandbox-run1" in o
    assert rms(s) == [] and boxed(e, "run1")


def test_a_plain_rm_whose_check_didnt_run_refuses_too_unknown_work_is_never_none(og, sb):
    e, set_ = sb
    s = set_(code=1)
    box("run1")
    code, out, err = og("rm", "run1")
    assert code == 1 and "has work that would be lost" in out + err and "the check for unsaved work failed (exit 1)" in out + err
    assert rms(s) == [] and boxed(e, "run1")


def test_attachs_rm_gets_a_reason_to_keep_it_from_the_same_failed_check(sb):
    _, set_ = sb
    set_(code=1)
    assert remove.unsafe_reasons("run1") == ["the check for unsaved work failed (exit 1)"]


def test_one_past_its_time_limit_says_the_sandbox_didnt_answer_in_time(og, sb, monkeypatch):
    e, set_ = sb
    monkeypatch.setenv("SBX_RM_BOOT_TIMEOUT", "1")
    set_(delay=5)
    box("run1")
    code, out, err = og("rm", "run1")
    assert code == 1 and "run1 didn't answer the check for unsaved work in time" in out + err and boxed(e, "run1")


def test_one_sbx_proves_gone_has_no_check_its_leftovers_cleaned_said_as_such(og, sb):
    e, set_ = sb
    s = set_(code=1)
    box("gone1")
    code, out, err = og("rm", "gone1")
    assert code == 0 and not boxed(e, "gone1") and checks(s) == [] and rms(s) == []
    assert (out + err).strip().splitlines()[-1] == "✓ removed what gone1 left behind  shared/gone1 kept"
    assert "not found" not in out + err


@pytest.mark.parametrize("force", [False, True])
def test_a_name_sbx_doesnt_know_with_nothing_left_is_no_sandbox_refused_nothing_run(og, sb, force):
    _, set_ = sb
    s = set_()
    code, out, err = og("rm", "nosuch1", *(["--force"] if force else []))
    assert code == 1 and [c for c in s.calls if c[:1] != ["ls"]] == []
    assert re.search(r"og rm: no sandbox 'nosuch1'; to see yours, run:.*og ls", out + err, re.S) and "removed" not in out + err


def test_if_clean_and_a_forced_removal_still_succeed_there_but_claim_and_record_nothing(og, sb, capfd):
    _, set_ = sb
    set_()
    code, out, err = og("rm", "nosuch1", "--if-clean")
    assert code == 0 and "nothing to remove" in out + err and "removed" not in out + err
    capfd.readouterr()
    assert remove.rm_clean("nosuch1", force=True) and "removed" not in "".join(capfd.readouterr())
    f = paths.state_dir() / "og.log"
    assert not f.exists() or f.read_text() == ""


def test_a_removal_ends_with_one_done_line_whats_gone_and_what_stayed_sbxs_words_kept_out(og, sb):
    e, set_ = sb
    set_()
    box("run1")
    code, out, err = og("rm", "run1", "--force")
    o = out + err
    assert code == 0 and o.strip().splitlines()[-1] == "✓ removed run1  shared/run1 kept" and "  · its folder removed (" in o
    assert "sbx's own words" not in o and not boxed(e, "run1")


def test_a_folder_kept_for_the_files_in_its_out_is_named_among_what_stayed(og, sb):
    e, set_ = sb
    set_()
    box("run1")
    (e / "boxes/run1/out/report.txt").write_text("x\n")
    code, out, err = og("rm", "run1", "--force")
    assert code == 0 and (out + err).strip().splitlines()[-1] == "✓ removed run1  shared/run1 and its folder (files in out/) kept"
    assert "og take run1 --all" in out + err


def test_when_sbx_fails_what_it_said_is_under_ogs_error_and_the_box_stays(og, sb):
    e, set_ = sb
    set_(rm_fail=True)
    box("run1")
    code, out, err = og("rm", "run1", "--force")
    assert code != 0 and re.search(r"sbx couldn't remove run1:.*error: it is busy", out + err, re.S)
    assert "✓" not in out + err and boxed(e, "run1")


def test_og_rm_prints_the_sandboxs_reasons_with_control_bytes_escaped(og, sb):
    _, set_ = sb
    set_(out="/w/\x1b]0;owned\x07\x1b[2J: 1 unpushed commit(s)")
    box("run1")
    code, out, err = og("rm", "run1")
    assert code == 1 and "\\x1b]0;owned\\x07\\x1b[2J" in out + err and "\x1b" not in out + err


def test_v_shows_each_file_og_changes_on_this_mac(og, sb):
    _, set_ = sb
    set_()
    box("run1")
    code, _, err = og("-v", "rm", "run1", "--force")
    assert code == 0 and re.search(r"  file  removed .*/boxes/run1", err)


# ── og log: og's record of changes ──

def test_a_removal_is_recorded_as_typed_og_log_shows_it_to_the_second_plain_and_as_json(og, sb):
    _, set_ = sb
    set_()
    box("run1")
    og("rm", "run1", "--force")
    out = og("log")[1]
    assert re.fullmatch(r"20\d\d-\d\d-\d\d \d\d:\d\d:\d\d  run1 removed  \(og rm run1 --force\)", out.strip().splitlines()[-1])
    assert og("-v", "log")[1] == out
    last = json.loads(og("log", "--json")[1])[-1]
    assert last["cmd"] == "og rm run1 --force" and last["what"] == "run1 removed"


def test_n_picks_how_many_0_for_all(og, sb):
    _, set_ = sb
    for _ in range(3):
        set_()
        box("run1")
        og("rm", "run1", "--force")
    assert len(json.loads(og("log", "-n", "1", "--json")[1])) == 1
    assert len(json.loads(og("log", "-n", "0", "--json")[1])) >= 3


@pytest.mark.parametrize("args", [["--bogus"], ["-n"], ["-n", "abc"]])
def test_an_unknown_option_or_a_bad_count_is_usage(og, sb, args):
    code, _, err = og("log", *args)
    assert code == 1
    if args == ["-n"]:
        assert "usage: og log" in err


def test_a_record_that_cant_be_written_never_fails_the_removal_it_records(og, sb, home, monkeypatch):
    e, set_ = sb
    set_()
    box("run1")
    (home / "not-a-dir").write_text("")
    monkeypatch.setenv("SBX_OGUN_DIR", str(home / "not-a-dir"))
    assert og("rm", "run1", "--force")[0] == 0 and not boxed(e, "run1")


# ── the check inside the sandbox, run here ──

PS = r"""echo "    1     0 ?        /sbin/init"
echo "  100     1 ?        claude bg-pty-host --bg-pty-host /tmp/cc/spare/a.pty.sock 200 50 -- claude"
echo "  101   100 pts/2    claude bg-spare --bg-spare /tmp/cc/spare/a.claim.sock"
echo "  110     1 ?        claude bg-pty-host --bg-pty-host /tmp/cc/pty/b.sock 200 50 -- claude"
echo "  111   110 pts/3    claude --session-id 0707f627 --agent helper"
echo "  112   111 pts/3    bash -c git status"
[ -n "$PS_TTY" ] && echo "  200     0 $PS_TTY    claude --dangerously-skip-permissions"
exit 0"""


@pytest.fixture
def probe(tmp_path, stand_in, real_git, monkeypatch):
    """The check as og rm sends it, against a pushed checkout with a Claude Code worktree
    (under SBX_PROBE_ROOTS, never this machine's own), a fake HOME for the jobs,
    and ps listing Claude's own ptys (and PS_TTY, a person's terminal, when set)."""
    stand_in("ps", PS)
    for k in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{k}_NAME", "t")
        monkeypatch.setenv(f"GIT_{k}_EMAIL", "t@t")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    roots, origin, h = tmp_path / "roots", tmp_path / "origin.git", tmp_path / "phome"
    r = roots / "repo"

    def git(*a, at=r):
        subprocess.run(["git", "-C", str(at), *a], check=True, capture_output=True)

    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    (r / "a").write_text("a\n")
    git("add", "a")
    git("commit", "-qm", "a")
    subprocess.run(["git", "clone", "-q", "--bare", str(r), str(origin)], check=True)
    git("remote", "add", "origin", str(origin))
    git("fetch", "-q", "origin")
    wt = r / ".claude/worktrees/r1"
    git("worktree", "add", "-q", "-b", "r1", str(wt))
    git("push", "-q", "origin", "r1")

    def run(*mode, jobs=(), tty=""):
        if h.exists():
            shutil.rmtree(h)
        for i, state in enumerate(jobs, 1):
            (h / f".claude/jobs/j{i}").mkdir(parents=True)
            (h / f".claude/jobs/j{i}/state.json").write_text(json.dumps({"state": state}))
        h.mkdir(exist_ok=True)
        env = {**os.environ, "HOME": str(h), "SBX_PROBE_ROOTS": str(roots), "PS_TTY": tty}
        return subprocess.run(["bash", "-c", PROBE.read_text(), "_", *mode], capture_output=True, text=True, env=env).stdout.strip()

    return run, r, wt, git


def test_each_of_several_space_separated_roots_is_looked_in(probe, tmp_path):
    _, r, _, _ = probe
    subprocess.run(["git", "init", "-q", str(tmp_path / "second/repo")], check=True)
    (tmp_path / "second/repo/new.txt").write_text("n\n")
    env = {**os.environ, "HOME": str(tmp_path / "phome"), "PS_TTY": "", "SBX_PROBE_ROOTS": f"{r.parent} {tmp_path / 'second'}"}
    out = subprocess.run(["bash", "-c", PROBE.read_text(), "_", "--stopped"], capture_output=True, text=True, env=env).stdout
    assert "/second/repo: 1 uncommitted/untracked file(s)" in out


def test_the_sandboxs_own_workspace_is_looked_in_wherever_it_lives(probe, tmp_path):
    # a workspace og mounted from outside the usual roots: its work is never missed
    ws = tmp_path / "elsewhere/proj"
    subprocess.run(["git", "init", "-q", str(ws)], check=True)
    (ws / "new.txt").write_text("n\n")
    env = {**os.environ, "HOME": str(tmp_path / "phome"), "PS_TTY": "", "SBX_PROBE_ROOTS": str(tmp_path / "roots")}
    out = subprocess.run(["bash", "-c", PROBE.read_text(), "_", "--root", str(ws), "--stopped"],
                         capture_output=True, text=True, env=env).stdout
    assert f"{ws}: 1 uncommitted/untracked file(s)" in out


def test_a_root_with_no_folder_after_it_ends_rather_than_hangs(probe, tmp_path):
    env = {**os.environ, "HOME": str(tmp_path / "phome"), "PS_TTY": "", "SBX_PROBE_ROOTS": str(tmp_path / "roots")}
    for args in (["--root"], ["--stopped", "--root"]):
        p = subprocess.run(["bash", "-c", PROBE.read_text(), "_", *args], capture_output=True, text=True, env=env, timeout=10)
        assert p.returncode == 0 and p.stdout == ""


def test_a_workspace_under_a_usual_root_is_reported_once(probe, tmp_path):
    _, r, _, _ = probe
    (r / "loose.txt").write_text("x\n")
    env = {**os.environ, "HOME": str(tmp_path / "phome"), "PS_TTY": "", "SBX_PROBE_ROOTS": str(r.parent)}
    out = subprocess.run(["bash", "-c", PROBE.read_text(), "_", "--root", str(r), "--stopped"],
                         capture_output=True, text=True, env=env).stdout
    assert out.count(f"{r}: ") == 1


def test_a_pushed_checkout_with_only_a_claude_code_worktree_untracked_is_clean(probe):
    run, *_ = probe
    assert run("--idle-ok") == ""


def test_a_hidden_folder_is_untracked_work_like_any_other(probe):
    run, r, _, _ = probe
    (r / ".tool").mkdir(parents=True)
    (r / ".tool/notes.md").write_text("s\n")
    assert "/roots/repo: 1 uncommitted/untracked file(s)" in run("--idle-ok")


def test_but_a_real_untracked_file_beside_them_even_under_claude_is_work(probe):
    run, r, _, _ = probe
    (r / ".claude/notes.md").write_text("n\n")
    assert "/roots/repo: 1 uncommitted/untracked file(s)" in run("--idle-ok")


def test_an_edit_inside_the_worktree_is_found(probe):
    run, _, wt, _ = probe
    with open(wt / "a", "a") as f:
        f.write("edit\n")
    assert "/roots/repo/.claude/worktrees/r1: 1 uncommitted/untracked file(s)" in run("--idle-ok")


def test_a_commit_the_worktrees_branch_has_and_no_remote_does_is_found(probe):
    run, _, wt, git = probe
    (wt / "c").write_text("c\n")
    git("add", "c", at=wt)
    git("commit", "-qm", "c", at=wt)
    assert "/roots/repo: 1 unpushed commit(s)" in run("--idle-ok")


@pytest.mark.parametrize(("jobs", "tty", "want"), [
    (("idle", "completed"), "", ""),                                  # an idle or finished session is no reason
    (("idle", "working", "needs_input", "blocked"), "", "3 background Claude job(s)"),   # mid-turn or waiting on a person is
    (("idle",), "", ""),                                              # Claude's own ptys are no one
    ((), "pts/0", "a terminal is open in it"),                        # an open terminal is
])
def test_idle_ok_counts_sessions_at_work_or_a_person_never_an_idle_one(probe, jobs, tty, want):
    run, *_ = probe
    out = run("--idle-ok", jobs=jobs, tty=tty)
    assert out.startswith(want) if want else out == ""


def test_stopped_asks_only_git(probe):
    run, _, wt, _ = probe
    with open(wt / "a", "a") as f:
        f.write("edit\n")
    out = run("--stopped", jobs=("working",), tty="pts/0")
    assert "uncommitted" in out and "background" not in out and "terminal" not in out


def test_without_either_mode_an_idle_session_still_counts(probe):
    run, *_ = probe
    assert run(jobs=("idle", "completed")).startswith("1 background Claude job(s)")


def test_a_commit_on_a_detached_head_or_a_stash_counts_as_unpushed(probe):
    run, r, _, git = probe
    git("checkout", "-q", "--detach")
    (r / "d").write_text("d\n")
    git("add", "d")
    git("commit", "-qm", "d")
    assert "/roots/repo: 1 unpushed commit(s)" in run("--idle-ok")


def test_a_stash_counts_as_unpushed(probe):
    run, r, _, git = probe
    with open(r / "a", "a") as f:
        f.write("s\n")
    git("stash", "-q")
    assert re.search(r"/roots/repo:.*unpushed commit\(s\)", run("--idle-ok"))


def test_a_checkout_git_cant_read_keeps_the_sandbox(probe):
    run, r, _, _ = probe
    assert run("--idle-ok") == ""
    (r / ".git/index").write_bytes(b"not an index")
    assert "/roots/repo: git status failed" in run("--idle-ok")
