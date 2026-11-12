"""The fakes every other test stands on: each external program og runs is replaced
on PATH, records what it was called with, and answers as the test configured."""

import subprocess

import pytest


def test_sbx_records_calls_and_answers_as_configured(fakes):
    fakes.sbx.answer(["ls"], stdout="NAME  STATUS\nweb   running\n")
    fakes.sbx.answer(["rm"], stderr="no such sandbox\n", code=2)

    ls = subprocess.run(["sbx", "ls", "--json"], capture_output=True, text=True)
    rm = subprocess.run(["sbx", "rm", "ghost"], capture_output=True, text=True)

    assert (ls.returncode, ls.stdout) == (0, "NAME  STATUS\nweb   running\n")
    assert (rm.returncode, rm.stderr) == (2, "no such sandbox\n")
    assert fakes.sbx.calls == [["ls", "--json"], ["rm", "ghost"]]


def test_an_unconfigured_call_succeeds_silently(fakes):
    p = subprocess.run(["sbx", "version"], capture_output=True, text=True)
    assert (p.returncode, p.stdout, p.stderr) == (0, "", "")


def test_the_first_matching_answer_wins(fakes):
    fakes.git.answer(["remote", "get-url"], stdout="https://github.com/me/x.git\n")
    fakes.git.answer(["remote"], stdout="origin\n")
    p = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True)
    assert p.stdout == "https://github.com/me/x.git\n"


def test_stdin_is_recorded(fakes):
    subprocess.run(["op", "item", "create"], input="secret body", text=True)
    assert fakes.op.stdin == ["secret body"]


@pytest.mark.parametrize("program", ["sbx", "op", "curl", "git", "ssh"])
def test_every_external_program_is_faked(fakes, program):
    subprocess.run([program, "--probe"], capture_output=True)
    assert getattr(fakes, program).calls == [["--probe"]]


def test_an_answer_given_once_answers_one_call_then_the_next_takes_over(fakes):
    fakes.sbx.answer(["secret", "ls"], code=1, once=True)
    fakes.sbx.answer(["secret", "ls"], stdout="row\n")
    first = subprocess.run(["sbx", "secret", "ls"], capture_output=True, text=True)
    second = subprocess.run(["sbx", "secret", "ls"], capture_output=True, text=True)
    assert (first.returncode, first.stdout) == (1, "")
    assert (second.returncode, second.stdout) == (0, "row\n")


def test_clear_drops_every_answer_but_keeps_the_calls(fakes):
    fakes.sbx.answer(["ls"], stdout="web\n")
    subprocess.run(["sbx", "ls"], capture_output=True)
    fakes.sbx.clear()
    p = subprocess.run(["sbx", "ls"], capture_output=True, text=True)
    assert p.stdout == ""
    assert fakes.sbx.calls == [["ls"], ["ls"]]


# these two run in file order: the second sees what the first left behind
def test_a_verbose_og_leaves_no_verbosity_behind(og, fakes):
    og("-vv", "ls")


def test_the_next_og_runs_quiet():
    import os
    assert os.environ.get("OGUN_VERBOSE", "") == ""


def test_an_answer_can_ask_for_text_anywhere_in_the_call(fakes):
    fakes.sbx.answer(["exec"], stdout="updated\n", has="claude update")
    fakes.sbx.answer(["exec"], stdout="other\n")
    hit = subprocess.run(["sbx", "exec", "box", "bash", "-lc", "x; claude update; y"], capture_output=True, text=True)
    miss = subprocess.run(["sbx", "exec", "box", "bash", "-lc", "true"], capture_output=True, text=True)
    assert (hit.stdout, miss.stdout) == ("updated\n", "other\n")


def test_an_answer_can_wait_before_answering(fakes):
    import time
    fakes.sbx.answer(["exec"], delay=0.5)
    t = time.monotonic()
    subprocess.run(["sbx", "exec"], capture_output=True)
    assert time.monotonic() - t >= 0.5


def test_real_git_puts_the_real_git_ahead_of_the_fake_and_nothing_else(fakes, real_git, tmp_path):
    p = subprocess.run(["git", "init", "-q", str(tmp_path / "r")], capture_output=True)
    assert p.returncode == 0 and (tmp_path / "r/.git").is_dir()
    assert fakes.git.calls == []
    subprocess.run(["sbx", "ls"], capture_output=True)
    assert fakes.sbx.calls == [["ls"]]


@pytest.mark.skipif(not __import__("os").path.isdir("/proc/self/fd"), reason="reads /proc")
def test_each_call_records_the_files_it_inherited_open(fakes, tmp_path):
    import os
    f = tmp_path / "held.lock"
    fd = os.open(f, os.O_CREAT | os.O_RDWR)
    try:
        os.set_inheritable(fd, True)
        subprocess.run(["sbx", "one"], close_fds=False)
        os.set_inheritable(fd, False)
        subprocess.run(["sbx", "two"], close_fds=False)
    finally:
        os.close(fd)
    assert str(f) in fakes.sbx.fds[0] and str(f) not in fakes.sbx.fds[1]


def test_a_stand_in_program_is_put_first_on_path_with_the_script_given(stand_in):
    stand_in("file", 'echo "type of $1"')
    p = subprocess.run(["file", "x"], capture_output=True, text=True)
    assert p.stdout == "type of x\n"
