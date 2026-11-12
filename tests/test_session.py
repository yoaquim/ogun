"""session: running one of og's scripts in the sandbox, and og attach: the
upkeep every attach refreshes (remotes, push rules, the docker relay), the
default-rules guard that fails closed, and the session itself: clappa where
OpenAPPA protects the sandbox, checked first or no session, plain claude elsewhere."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import FIXTURES
from ogun import cli
from ogun.core import paths, records
from ogun.sandbox import session


def test_the_provision_command_runs_inside_the_sandbox_as_written(fakes, monkeypatch):
    monkeypatch.setenv("SBX_PROVISION", "/opt/setup.sh --quiet")
    p = session.provision("web")
    assert p.returncode == 0
    assert fakes.sbx.calls == [["exec", "web", "bash", "-lc", "/opt/setup.sh --quiet"]]


# ── og attach: upkeep, the default-rules guard, then the session ──

@pytest.fixture
def at(home, registry, fakes, og, real_git, monkeypatch):
    """Sandbox box, listed at its checkout personal/box, whose registry entry mounts
    personal/notes read-only. og attach box, its sbx answered as given; back: the
    default rules sbx has again."""
    ws, notes = home / "Projects/personal/box", home / "Projects/personal/notes"
    notes.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(ws)], check=True)
    subprocess.run(["git", "-C", str(ws), "remote", "add", "origin", "https://github.com/octocat/box.git"], check=True)
    shutil.copy(FIXTURES / "appa.lock", home / ".config/ogun/")
    registry({"box": {"owner": "personal", "repos": {"read": ["personal/notes"]}}})
    monkeypatch.setenv("SBX_EXCHANGE", str(home / "exchange"))
    s = fakes.sbx

    def run(*args, back=(), rm_fail=False, ensure=0, activate=0, listed=True, rc=0, relay=""):
        s.clear()
        s.answer(["ls"], stdout="SANDBOX  AGENT   STATUS   WORKSPACE\n" + (f"box      claude  running  {ws}\n" if listed else ""))
        for r in back:
            s.answer(["policy", "inspect", r])
        s.answer(["policy", "inspect"], code=1)
        if rm_fail:
            s.answer(["policy", "rm"], code=1)
        s.answer(["exec"], code=ensure, has="ensure.sh")
        s.answer(["exec"], code=activate, has="activate.sh")
        if relay:
            s.answer(["exec"], stderr=relay, code=1, has="sandbox-docker.sh")
        s.answer(["run"], code=rc)
        return og(*args) if args else og("attach", "box")

    return run, str(ws), str(notes)


def protect(on: bool = True) -> None:
    f = records.records_dir() / "box.json"
    if on:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('{"sandbox": "box", "appa": {"version": "v0.37.0"}}')
    else:
        f.unlink(missing_ok=True)


def where(calls, pred) -> list[int]:
    return [i for i, c in enumerate(calls) if pred(c)]


def session_of(calls):
    return where(calls, lambda c: c == ["run", "--name", "box", "claude"])


def clappa(calls):
    return where(calls, lambda c: c[:3] == ["exec", "-it", "box"] and "clappa" in " ".join(c))


def test_attach_removes_a_restored_default_rule_before_claude_starts(at, fakes):
    run, _, _ = at
    run(back=["default-package-managers"])
    rm = where(fakes.sbx.calls, lambda c: c == ["policy", "rm", "network", "--id", "default-package-managers", "--force"])
    assert rm and session_of(fakes.sbx.calls) and rm[0] < session_of(fakes.sbx.calls)[0]


def test_when_that_removal_fails_attach_refuses_rather_than_start_claude(at, fakes):
    run, _, _ = at
    code, out, err = run(back=["default-cloud-infrastructure"], rm_fail=True)
    assert code != 0 and not session_of(fakes.sbx.calls)
    assert "by hand:\n    sbx policy rm network --id default-cloud-infrastructure --force" in out + err
    assert "not attaching" in out + err


def test_a_protected_sandbox_checks_openappa_then_starts_clappa_in_its_workspace_never_claude(at, fakes):
    run, ws, _ = at
    protect()
    assert run()[0] == 0
    ensure = where(fakes.sbx.calls, lambda c: "ensure.sh" in " ".join(c))
    assert ensure and clappa(fakes.sbx.calls) and ensure[0] < clappa(fakes.sbx.calls)[0]
    assert not session_of(fakes.sbx.calls)
    assert fakes.sbx.calls[clappa(fakes.sbx.calls)[0]][-1] == ws


def test_when_openappa_isnt_ready_no_session_starts_at_all(at, fakes):
    run, _, _ = at
    protect()
    code, out, err = run(ensure=1)
    assert code != 0 and not clappa(fakes.sbx.calls) and not session_of(fakes.sbx.calls)
    assert "not starting 'box' unprotected" in out + err


def test_one_installed_but_never_on_is_turned_on_with_its_read_only_repos_then_attached(at, fakes):
    run, ws, notes = at
    protect()
    code, out, err = run(ensure=3)
    assert code == 0
    act = where(fakes.sbx.calls, lambda c: "activate.sh" in " ".join(c) and c[-2:] == [ws, notes])
    assert act and clappa(fakes.sbx.calls) and act[0] < clappa(fakes.sbx.calls)[0]
    assert "turning OpenAPPA on in 'box'" in out + err


def test_and_when_that_fails_no_session_starts(at, fakes):
    run, _, _ = at
    protect()
    code, out, err = run(ensure=3, activate=1)
    assert code != 0 and not clappa(fakes.sbx.calls) and not session_of(fakes.sbx.calls)
    assert "OpenAPPA couldn't be turned on" in out + err


def test_an_unprotected_sandbox_attaches_with_plain_claude(at, fakes):
    run, _, _ = at
    protect(False)
    assert run()[0] == 0
    assert session_of(fakes.sbx.calls)
    assert not any("ensure.sh" in " ".join(c) or "clappa" in " ".join(c) for c in fakes.sbx.calls)


def test_every_attach_rewrites_ssh_remotes_and_adds_its_push_rules(at, fakes):
    run, _, _ = at
    run()
    assert any("insteadOf" in " ".join(c) for c in fakes.sbx.calls)
    assert ["policy", "allow", "network", "--sandbox", "box", "github.com", "--method", "POST",
            "--path", "/octocat/box.git/git-receive-pack"] in fakes.sbx.calls


def test_every_attach_runs_the_docker_relay(at, fakes):
    run, _, _ = at
    run()
    c = next(c for c in fakes.sbx.calls if "sandbox-docker.sh" in c)
    assert c[:4] == ["exec", "box", "bash", "-lc"] and c[4] == (paths.SCRIPTS / "sandbox-docker.sh").read_text()
    assert "agent-config" not in " ".join(c)   # sent in as text: a sandbox with no host mount runs it too


def test_a_relay_that_fails_on_attach_says_why(at):
    run, _, _ = at
    _, out, err = run(relay="sandbox-docker: socat is missing\n")
    assert "the docker relay isn't running" in out + err and "sandbox-docker: socat is missing" in out + err


@pytest.mark.parametrize("args", [["attach"], ["attach", "box", "cub"], ["attach", "--sync"]])
def test_no_name_two_or_an_option_is_a_usage_error_and_calls_no_sbx(at, fakes, args):
    run, _, _ = at
    s = fakes.sbx
    n = len(s.calls)
    assert run(*args)[0] == 1
    assert s.calls[n:] == []


def test_attach_help_is_its_help_box_and_calls_no_sbx(og, fakes):
    code, out, _ = og("attach", "box", "--help")
    assert code == 0 and any(line.startswith("Examples:") for line in out.splitlines())
    assert fakes.sbx.calls == []


def test_a_sandbox_sbx_doesnt_list_is_refused_before_anything_runs_in_it(at, fakes):
    run, _, _ = at
    code, out, err = run(listed=False)
    assert code != 0 and (out + err).startswith("og attach: ") and "box" in out + err
    assert not [c for c in fakes.sbx.calls if c[:1] in (["run"], ["exec"])]


def test_og_v_attach_shows_each_sbx_call_the_session_included(at, fakes):
    run, _, _ = at
    code, out, err = run("-v", "attach", "box")
    assert code == 0
    assert "$ sbx run --name box claude" in out + err
    assert "$ sbx policy allow network --sandbox box github.com --method POST" in out + err


# ── leaving: og asks and says nothing more ──

def test_leaving_asks_the_sandbox_nothing_more_and_keeps_the_sessions_exit_status(at, fakes):
    run, _, _ = at
    code, out, err = run(rc=7)
    # nothing on stdout, and on stderr only the notes from before the session: no question, no warning
    assert code == 7 and out == "" and all(line.startswith("  · ") for line in err.splitlines())
    calls = fakes.sbx.calls
    assert calls[[c[0] for c in calls].index("run") + 1:] == []


# the bare og's attach runs the same checks; it runs them in its own order
def _src(module) -> list[str]:
    return Path(module.__file__).read_text().splitlines()


def _after(lines: list[str], text: str, n: int) -> str:
    i = next(i for i, x in enumerate(lines) if text in x)
    return "\n".join(lines[i:i + n + 1])


def test_the_session_attach_guard_runs_after_its_upkeep():
    assert 'if not guard("attach"):' in _after(_src(session), "upkeep(sb, ws, True)", 1)


def test_both_attach_paths_run_the_session_upkeep():
    assert '"attach": session.attach' in "\n".join(_src(cli))
    assert "docker_relay(sb)" in _after(_src(session), "egress.egress_sync(sb, ws)", 1)


# ── the remotes script, run for real ──

def test_ssh_github_remotes_become_https_and_stay_so_when_a_restart_puts_the_hosts_back(tmp_path, monkeypatch):
    b, r = tmp_path / "local-exec", tmp_path / "rr"
    b.mkdir()
    (b / "sbx").write_text('#!/bin/sh\n[ "$1" = exec ] && { shift 2; exec "$@"; }\nexit 0\n')
    (b / "sbx").chmod(0o755)
    monkeypatch.setenv("PATH", f"{b}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

    def git(*a):
        return subprocess.run(["git", "-C", str(r), *a], capture_output=True, text=True).stdout.strip()

    subprocess.run(["git", "init", "-q", str(r)], check=True)
    git("remote", "add", "origin", "git@github.com:octocat/x.git")
    assert session.https_remotes("box", str(r), say=False)
    assert session.https_remotes("box", str(r), say=False)
    assert git("config", "--get", "remote.origin.url") == "https://github.com/octocat/x.git"
    git("config", "remote.origin.url", "git@github.com:octocat/x.git")   # what a sandbox start puts back
    assert git("remote", "get-url", "--push", "origin") == "https://github.com/octocat/x.git"
    assert len(git("config", "--get-all", "url.https://github.com/.insteadOf").splitlines()) == 2
