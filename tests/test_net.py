"""net: the sandbox-name rule, allowing one rule with a single retry, the ssh-agent
guard, og policy (the baseline every sandbox gets, sbx's default rules, the
GitHub-wide allows it names but never removes) each sandbox's push rules, and the registry's
egress: what a repo's entry lets its sandboxes reach."""

import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REAL_GIT
from ogun.core import naming
from ogun.net import allow, baseline, egress, netcmd, policy, pushrules, ruletable
from ogun.sandbox import create, session


@pytest.mark.parametrize("name", ["fern", "a", "a.b_c-1", "Fern9", "a" * 61])
def test_a_sandbox_name_og_makes(name):
    assert naming.name_ok(name) is True


@pytest.mark.parametrize("name", ["", ".hidden", "-dash", "_under", "has space", "a/b", "a" * 62, "café"])
def test_not_a_sandbox_name(name):
    assert naming.name_ok(name) is False


def test_allow_twice_succeeds_first_time_with_one_call(fakes):
    assert ruletable.allow_twice("policy", "allow", "network", "example.com") is True
    assert fakes.sbx.calls == [["policy", "allow", "network", "example.com"]]


def test_allow_twice_retries_once_then_says_it_failed(fakes, capsys):
    fakes.sbx.answer(["policy"], stderr="daemon restarting\n", code=1)
    assert ruletable.allow_twice("policy", "allow", "network", "example.com") is False
    assert fakes.sbx.calls == [["policy", "allow", "network", "example.com"]] * 2
    assert "sbx policy allow network example.com" in capsys.readouterr().err


# ── ssh-agent forwarding: off, or create refuses ──
# sbx forwards the Mac's ssh-agent into every sandbox by default, and that agent may hold
# the Mac's signing key. og turns it off itself, refuses until it
# reads off, and never restarts the daemon: that stops running sandboxes.

def agent(fakes, get="false\n", get_code=0, set_fail=False):
    fakes.sbx.clear()
    fakes.sbx.answer(["settings", "get"], stdout=get, code=get_code)
    if set_fail:
        fakes.sbx.answer(["settings", "set"], stderr="unknown setting\n", code=1)
    return fakes.sbx


SET_OFF = ["settings", "set", "ssh.agentForwardingEnabled", "false"]


@pytest.mark.parametrize("get", ["false\n", "ssh.agentForwardingEnabled: false", "ssh.agentForwardingEnabled=false",
                                 "KEY  VALUE  SOURCE\nssh.agentForwardingEnabled  false  user\n"],
                         ids=["bare false, as sbx prints it", "key: false", "key=false", "a table row"])
def test_off_passes_silently_and_sets_nothing(fakes, capfd, get):
    s = agent(fakes, get)
    assert baseline.ssh_agent_off() is True
    assert "".join(capfd.readouterr()) == ""
    assert s.calls == [["settings", "get", "ssh.agentForwardingEnabled"]]


@pytest.mark.parametrize(("get", "code"), [
    ("true\n", 0), ("ssh.agentForwardingEnabled: true", 0), ("true (default: false)", 0),
    ("", 0),               # nothing said counts as on
    ("false", 1),          # a failing get (sbx < 0.42.1, an unknown key)
    ("falsey", 0),         # only starts with false
    ("false\r\n", 0), ("false\u00a0", 0), ("true\x1cfalse", 0), ("true\u2028false", 0),   # breaks only Python counts
], ids=["true", "key: true", "true then a default", "empty", "get failed", "falsey", "carriage return", "nbsp",
        "\\x1c", "\\u2028"])
def test_on_or_unknown_is_turned_off_refused_naming_the_restart_never_restarting(fakes, capfd, get, code):
    s = agent(fakes, get, code)
    assert baseline.ssh_agent_off() is False
    assert SET_OFF in s.calls
    assert "sbx daemon restart" in capfd.readouterr().err
    assert not [c for c in s.calls if c[:2] == ["daemon", "restart"]]


def test_a_failing_set_refuses_naming_the_sbx_version_it_needs(fakes, capfd):
    s = agent(fakes, "true\n", set_fail=True)
    assert baseline.ssh_agent_off() is False
    assert "0.42.1" in capfd.readouterr().err
    assert not [c for c in s.calls if c[:1] == ["daemon"]]


@pytest.mark.parametrize("cmd", ["template", "cub"])
def test_each_refusal_names_the_og_command_that_ran_it_and_says_to_run_it_again(fakes, capfd, cmd):
    agent(fakes, "true\n")
    baseline.ssh_agent_off(cmd)
    err = capfd.readouterr().err
    assert err.startswith(f"og {cmd}: ") and "then run your og command again:" in err
    assert f"then og {cmd} again" not in err


def test_a_refusal_with_no_command_named_is_og_policys(fakes, capfd):
    agent(fakes, "true\n", set_fail=True)
    baseline.ssh_agent_off()
    err = capfd.readouterr().err
    assert err.startswith("og policy: ") and "0.42.1" in err


# ── og policy: the baseline, each sandbox's pushes, sbx's default rules, the agent ──

# sbx's real `policy ls --wide` layout
LS_HEAD = "SOURCE   CREATED VIA   APPLIES TO   POLICY   POLICY_ID   RULE   RULE_ID   TYPE   METHOD   PATH   DECISION   PROTOCOLS   RESOURCES"
LS_ROW = "  -  -  network  -  -  allow  tcp"


def rule(scope: str, res: str, via: str = "added", row: str = LS_ROW) -> str:
    return f"local    {via}  {scope}  -  pol  -  id{row}  {res}"


def policy_sbx(fakes, *, get="false\n", rules="", listing="", back=None, rm_fail=False):
    """sbx as og policy reads it. back: the default rules sbx still has (None: every one)."""
    s = agent(fakes, get)
    s.answer(["policy", "ls"], stdout=rules)
    s.answer(["ls"], stdout=listing)
    if back is not None:
        for r in back:
            s.answer(["policy", "inspect", r])
        s.answer(["policy", "inspect"], code=1)
    if rm_fail:
        s.answer(["policy", "rm"], code=1)
    return s


def allows(s) -> list[list[str]]:
    return [c[3:] for c in s.calls if c[:3] == ["policy", "allow", "network"]]


def test_og_policy_applies_the_baseline_and_turns_forwarding_off_failing_until_the_restart(og, fakes):
    s = policy_sbx(fakes, get="true\n")
    assert og("policy")[0] == 1
    assert allows(s) and SET_OFF in s.calls
    assert not [c for c in s.calls if c[:1] == ["daemon"]]


def test_og_policy_passes_once_forwarding_reads_off(og, fakes):
    s = policy_sbx(fakes)
    assert og("policy")[0] == 0
    assert ["settings", "get", "ssh.agentForwardingEnabled"] in s.calls and SET_OFF not in s.calls


def test_the_baseline_leaves_out_npm_and_aws(home):
    domains = baseline.baseline_lists()["SBX_BASELINE_DOMAINS"].split(",")
    assert "registry.npmjs.org" not in domains and "*.amazonaws.com" not in domains


def test_og_internal_baseline_prints_the_lists_og_applies_as_it_applies_them(og):
    code, out, _ = og("internal", "baseline")
    assert code == 0 and [line.split("=")[0] for line in out.splitlines()] == list(baseline.LISTS)



@pytest.mark.parametrize("hosts", [
    ["registry.npmjs.org"],
    ["pypi.org", "files.pythonhosted.org"],
    ["download.docker.com"],                                   # the image's Docker apt source
    ["registry-1.docker.io", "auth.docker.io", "production.cloudfront.docker.com",
     "production.cloudflare.docker.com"],                      # pulls, never pushes
    ["cli.github.com"],                                        # GitHub CLI's apt source
], ids=["npm", "pypi", "docker apt", "docker hub", "gh cli apt"])
def test_registries_are_read_only_for_every_sandbox_never_whole_hosts(og, fakes, hosts):
    s = policy_sbx(fakes)
    og("policy")
    for h in hosts:
        assert [h, "--method", "GET,HEAD"] in allows(s)
        assert not any(h in a.split(",") for c in allows(s) if "--method" not in c for a in c)
    assert not any("upload.pypi.org" in a for c in s.calls for a in c)


def test_github_is_read_only_for_every_sandbox_reads_and_the_clone_post_never_whole(og, fakes):
    s = policy_sbx(fakes)
    og("policy")
    assert ["github.com", "--method", "GET,HEAD"] in allows(s)
    assert ["github.com", "--method", "POST", "--path", "/*/*/git-upload-pack"] in allows(s)
    assert not any("github.com" in a.split(",") for c in allows(s) if "--method" not in c for a in c)
    assert "github.com" not in baseline.baseline_lists()["SBX_BASELINE_DOMAINS"].split(",")


def test_og_policy_names_every_allow_covering_github_with_its_removal_and_removes_none(og, fakes):
    s = policy_sbx(fakes, rules="\n".join([LS_HEAD, rule("sandbox:box", "*.com"), rule("all", "**"),
                                        rule("sandbox:box", "api.github.com")]))
    out = "".join(og("policy")[1:])
    assert ("*.com covers all of github.com for box, so box can push to any of your repos — to remove it:\n"
            "    og net box '*.com' --rm, then og policy") in out
    assert ("** covers all of github.com for every sandbox, so any sandbox can push to any of your repos — to remove it:\n"
            "    og net --all '**' --rm, then og policy") in out
    assert "api.github.com covers" not in out
    assert not [c for c in s.calls if c[:3] == ["policy", "rm", "network"] and c[3] in ("--resource", "--sandbox")]


def test_all_of_github_for_every_sandbox_is_named_as_such_and_never_removed(og, fakes):
    s = policy_sbx(fakes, rules="\n".join([LS_HEAD, rule("all", "github.com:443")]))
    out = "".join(og("policy")[1:])
    assert ("all of github.com is allowed for every sandbox, so any sandbox can push to any of your repos — to remove it:\n"
            "    og net --all github.com:443 --rm, then og policy") in out
    assert not [c for c in s.calls if c[:4] == ["policy", "rm", "network", "--resource"]]


def test_all_of_github_for_one_sandbox_is_named_as_such(og, fakes):
    policy_sbx(fakes, rules="\n".join([LS_HEAD, rule("sandbox:box", "github.com")]))
    out = "".join(og("policy")[1:])
    assert ("all of github.com is allowed for box, so box can push to any of your repos — to remove it:\n"
            "    og net box github.com --rm, then og policy") in out
    assert "covers all of github.com" not in out


def test_the_summary_counts_a_whole_host_allow_for_every_sandbox_never_only_per_repo_pushes(og, fakes, monkeypatch):
    from ogun.core import boxes
    policy_sbx(fakes, rules="\n".join([LS_HEAD, rule("all", "github.com")]))
    rows = []
    monkeypatch.setattr(boxes, "table", lambda title, r: rows.extend(r))
    policy.policy([])
    assert "1 rule covers it" in dict(rows)["github.com"] and "only per-repo" not in dict(rows)["github.com"]
    assert "retired" not in dict(rows)


DEFAULTS_OFF = ["default-ai-services", "default-cloud-infrastructure", "default-code-and-containers", "default-package-managers"]


def test_og_policy_removes_sbxs_whole_category_defaults_and_keeps_the_os_mirrors_and_cert_checks(og, fakes):
    s = policy_sbx(fakes)
    og("policy")
    removed = [c[4] for c in s.calls if c[:4] == ["policy", "rm", "network", "--id"]]
    assert set(DEFAULTS_OFF) <= set(removed)
    assert not any(r.startswith(("default-os-packages", "default-cert-validation")) for r in removed)
    assert all(c[-1] == "--force" for c in s.calls if c[:4] == ["policy", "rm", "network", "--id"])


def test_a_default_rule_an_sbx_upgrade_restored_is_removed_naming_why(fakes, capfd):
    s = policy_sbx(fakes, back=["default-cloud-infrastructure"])
    assert baseline.default_rules_off("an sbx upgrade restored it")
    assert [c for c in s.calls if c[:2] == ["policy", "rm"]] == [
        ["policy", "rm", "network", "--id", "default-cloud-infrastructure", "--force"]]
    assert "removed sbx's default rule default-cloud-infrastructure (an sbx upgrade restored it)" in capfd.readouterr().err


def test_none_back_says_and_removes_nothing(fakes, capfd):
    s = policy_sbx(fakes, back=[])
    assert baseline.default_rules_off("x")
    assert "".join(capfd.readouterr()) == ""
    assert not [c for c in s.calls if c[:2] == ["policy", "rm"]]


def test_a_removal_that_fails_says_how_by_hand_and_fails(fakes, capfd):
    policy_sbx(fakes, back=["default-cloud-infrastructure"], rm_fail=True)
    assert baseline.default_rules_off("x") is False
    assert "sbx policy rm network --id default-cloud-infrastructure --force" in capfd.readouterr().err


# ── GitHub pushes: each sandbox only to its own repos ──

def git(*args):
    subprocess.run(["git", *args], check=True, capture_output=True)


@pytest.fixture
def remotes(tmp_path, fakes, real_git):
    """A checkout with GitHub remotes in every form, one off GitHub, one with glob characters."""
    r = tmp_path / "pw"
    git("init", "-q", str(r))
    for name, url in (("origin", "git@github.com:me/app.git"), ("fork", "https://github.com/me/app-fork"),
                      ("up", "ssh://git@github.com/org/app.git"), ("other", "https://gitlab.com/me/app.git"),
                      ("odd", "https://github.com/me/*")):
        git("-C", str(r), "remote", "add", name, url)
    git("-C", str(r), "config", "--add", "remote.origin.pushurl", "https://github.com/me/mirror.git")
    return str(r)


def test_push_repos_every_github_remote_push_urls_too_nothing_off_github_nothing_with_a_glob(remotes):
    assert pushrules.push_repos(remotes) == ["me/app", "me/app-fork", "me/mirror", "org/app"]


@pytest.fixture
def placed(home, registry, fakes, real_git):
    """A placed repo (~/Projects/<owner>/<repo>) whose entry grants a write repo, a read
    repo, and a push address."""
    p = home / "Projects/me"
    for repo in ("app", "lib", "docs"):
        git("init", "-q", str(p / repo))
        git("-C", str(p / repo), "remote", "add", "origin", f"https://github.com/me/{repo}.git")
    registry({"app": {"owner": "me", "repos": {"read": ["me/docs"], "write": ["me/lib"], "push": ["https://github.com/me/extra"]}}})
    return str(p / "app")


def test_push_repos_add_each_registry_write_repo_never_a_read_one_and_each_push_address(placed):
    got = pushrules.push_repos(placed)
    assert "me/lib" in got and "me/app" in got and "me/extra" in got
    assert "me/docs" not in got


def test_a_malformed_registry_entry_costs_its_grants_never_the_push_to_its_own_repo(placed, registry):
    registry({"app": {"owner": "me", "repos": ["me/lib"]}})
    assert pushrules.push_repos(placed) == ["me/app"]


def test_no_workspace_no_push_rules_never_the_folder_og_runs_in(remotes, fakes, monkeypatch, capfd):
    monkeypatch.chdir(remotes)
    assert pushrules.push_rules("box", "")
    assert "".join(capfd.readouterr()) == ""
    assert not any("git-receive-pack" in a for c in fakes.sbx.calls for a in c)


def test_push_rules_for_that_sandbox_only_each_repo_with_and_without_git(remotes, fakes):
    assert pushrules.push_rules("box", remotes)
    pushes = [c for c in fakes.sbx.calls if any("git-receive-pack" in a for a in c)]
    assert ["policy", "allow", "network", "--sandbox", "box", "github.com", "--method", "POST",
            "--path", "/me/app.git/git-receive-pack"] in pushes
    assert ["policy", "allow", "network", "--sandbox", "box", "github.com", "--method", "POST",
            "--path", "/me/app/git-receive-pack"] in pushes
    assert len(pushes) == 8
    assert all(c[3:5] == ["--sandbox", "box"] for c in pushes)
    assert not any("gitlab" in a or "/me/*" in a for c in fakes.sbx.calls for a in c)


def test_og_policy_gives_every_listed_sandbox_its_own_push_rules(og, remotes, fakes):
    s = policy_sbx(fakes, listing=f"SANDBOX  AGENT  STATUS  WORKSPACE\nbox  claude  stopped  {remotes}\n")
    og("policy")
    assert ["policy", "allow", "network", "--sandbox", "box", "github.com", "--method", "POST",
            "--path", "/me/app.git/git-receive-pack"] in s.calls


def test_og_policy_removes_only_sbxs_own_default_rules_never_an_allow_or_a_sandboxs_rule(og, fakes):
    s = policy_sbx(fakes)
    out = "".join(og("policy")[1:])
    assert "sbx policy rm" not in out and "ogun allow" not in out
    assert all(c[3] == "--id" and c[4].startswith("default-") for c in s.calls if c[:2] == ["policy", "rm"])


def test_og_policy_refuses_a_sandbox_name_pointing_at_og_allow_before_applying_anything(og, fakes):
    s = policy_sbx(fakes)
    n = len(s.calls)
    code, out, err = og("policy", "some-box")
    assert code == 1 and "og allow <name> <domain>" in out + err
    assert s.calls[n:] == []


# ── the registry's egress: what a repo's entry lets its sandboxes reach ──
# Read-only unless a grant writes, and a write waits for this Mac's approval. A create,
# every attach and og policy bring each sandbox in line: what's granted is allowed, what
# the registry no longer grants (or now grants read-only) is removed.

@pytest.fixture
def web(home, registry, fakes, monkeypatch):
    """Sandbox box for personal/web, its record as given; sbx lists rules as given.
    No terminal: stdin a pipe that would say yes."""
    from ogun.core import paths
    w = home / "Projects/personal/web"
    w.mkdir(parents=True)
    monkeypatch.setattr(sys, "stdin", io.StringIO("y\n" * 4))
    state = paths.state_dir()
    (state / "sandboxes").mkdir(parents=True)

    def setup(egress, owner="personal", rec=None, rules="", approved=None, listing=""):
        registry({"web": {"egress": egress, **({"owner": owner} if owner else {})}})
        f = state / "sandboxes/box.json"
        if rec is False:
            f.unlink(missing_ok=True)
        else:
            f.write_text(json.dumps(rec or {"sandbox": "box", "egress": [], "secrets": []}))
        a = state / "approved-egress"
        if approved is None:
            a.unlink(missing_ok=True)
        else:
            a.write_text(approved)
        s = fakes.sbx
        s.clear()
        s.answer(["policy", "ls"], stdout=rules)
        s.answer(["ls"], stdout=listing)
        s.answer(["settings", "get"], stdout="false\n")
        s.answer(["policy", "inspect"], code=1)
        return s

    return setup, str(w), state


def sync(web, *args, **kw):
    setup, w, _ = web
    s = setup(*args, **kw)
    n = len(s.calls)
    ok = egress.egress_sync("box", w)
    return ok, s.calls[n:]


def allowed(calls, *rest) -> bool:
    return ["policy", "allow", "network", "--sandbox", "box", *rest] in calls


def no_allow(calls) -> bool:
    return not [c for c in calls if c[:2] == ["policy", "allow"]]


def egress_rec(web) -> list:
    return json.loads((web[2] / "sandboxes/box.json").read_text()).get("registry_egress", [])


def recorded(web, host, write) -> bool:
    return len([e for e in egress_rec(web) if e["host"] == host and e["write"] is write]) == 1


def erule(id_, type_, method, path, host, decision="allow", scope="sandbox:box") -> str:
    return f"{LS_HEAD}\nlocal  added  {scope}  -  p1  -  {id_}  {type_}  {method}  {path}  {decision}  -  {host}\n"


def rm_id(id_) -> list[str]:
    return ["policy", "rm", "network", "--id", id_, "--sandbox", "box", "--force"]


def test_a_grant_without_write_is_allowed_for_that_sandbox_reading_only_and_recorded(web):
    ok, calls = sync(web, [{"hosts": ["api.example.com"], "for": "the API"}])
    assert ok and allowed(calls, "api.example.com", "--method", "GET,HEAD") and recorded(web, "api.example.com", False)


def test_the_next_sync_with_nothing_changed_allows_nothing_again(web):
    sync(web, [{"hosts": ["api.example.com"]}])
    rec = json.loads((web[2] / "sandboxes/box.json").read_text())
    ok, calls = sync(web, [{"hosts": ["api.example.com"]}], rec=rec)
    assert ok and no_allow(calls)


def test_every_subdomain_of_a_domain_is_a_host_a_grant_may_name(web):
    ok, calls = sync(web, [{"hosts": ["*.cdn.example.com"]}])
    assert ok and allowed(calls, "*.cdn.example.com", "--method", "GET,HEAD")


def test_a_write_grant_not_yet_approved_with_no_terminal_reads_only_for_now_and_says_so(web, capfd):
    _, calls = sync(web, [{"hosts": ["up.example.com"], "write": True, "for": "uploads"}])
    out = "".join(capfd.readouterr())
    assert allowed(calls, "up.example.com", "--method", "GET,HEAD") and recorded(web, "up.example.com", False)
    a = out.find("SENDING DATA TO A DOMAIN, NOT YET APPROVED ON THIS MAC")
    assert -1 < a < out.find("Why: uploads") < out.find("no terminal to ask at, so up.example.com is reading only")
    assert "og policy" in out[a:]


def test_approved_it_is_allowed_whole_and_recorded_as_writing(web):
    ok, calls = sync(web, [{"hosts": ["up.example.com"], "write": True}], approved="personal/web\tup.example.com\n")
    assert ok and allowed(calls, "up.example.com") and recorded(web, "up.example.com", True)


def test_declined_it_reads_only_and_isnt_asked_again(web):
    ok, calls = sync(web, [{"hosts": ["up.example.com"], "write": True}], approved="personal/web\tup.example.com\tdeclined\n")
    assert ok and allowed(calls, "up.example.com", "--method", "GET,HEAD") and recorded(web, "up.example.com", False)


def reg_rec(*hosts, egress=(), secrets=()):
    return {"sandbox": "box", "egress": list(egress), "secrets": list(secrets),
            "registry_egress": [{"host": h, "write": w} for h, w in hosts]}


def test_a_host_no_longer_granted_has_its_rule_removed_by_id_and_leaves_the_record(web):
    ok, calls = sync(web, [{"hosts": ["keep.example.com"]}],
                     rec=reg_rec(("keep.example.com", False), ("old.example.com", False)),
                     rules=erule("id9", "http", "GET,HEAD", "/**", "old.example.com"))
    assert ok and rm_id("id9") in calls and no_allow(calls)
    assert not [e for e in egress_rec(web) if e["host"] == "old.example.com"]


def test_a_rule_holding_several_leaving_hosts_is_removed_once_putting_back_only_the_one_that_stays(web):
    rules = (f"{LS_HEAD}\nlocal  added  sandbox:box  -  p1  -  id3  network  -  -  allow  -  a.example.com\n"
             "                                                       b.example.com\n"
             "                                                       c.example.com\n")
    ok, calls = sync(web, [], rec=reg_rec(("a.example.com", True), ("b.example.com", True)), rules=rules)
    assert ok and [c for c in calls if c[:5] == ["policy", "rm", "network", "--id", "id3"]] == [rm_id("id3")]
    assert [c for c in calls if c[:2] == ["policy", "allow"]] == [["policy", "allow", "network", "--sandbox", "box", "c.example.com"]]


def test_one_whose_rule_is_already_gone_just_leaves_the_record_never_said_as_removed(web, capfd):
    ok, calls = sync(web, [], rec=reg_rec(("old.example.com", False)), rules=LS_HEAD + "\n")
    assert ok and not [c for c in calls if c[:2] == ["policy", "rm"]]
    assert "removed" not in "".join(capfd.readouterr()) and egress_rec(web) == []


def test_a_grant_that_no_longer_writes_has_its_whole_host_rule_removed_then_reads_only(web):
    ok, calls = sync(web, [{"hosts": ["up.example.com"]}], rec=reg_rec(("up.example.com", True)),
                     rules=erule("id7", "network", "-", "-", "up.example.com"))
    assert ok and rm_id("id7") in calls and allowed(calls, "up.example.com", "--method", "GET,HEAD")
    assert recorded(web, "up.example.com", False)


def test_a_grant_that_now_writes_approved_loses_its_read_only_rule_then_is_allowed_whole(web):
    ok, calls = sync(web, [{"hosts": ["up.example.com"], "write": True}], rec=reg_rec(("up.example.com", False)),
                     rules=erule("id6", "http", "GET,HEAD", "/**", "up.example.com"), approved="personal/web\tup.example.com\n")
    assert ok and rm_id("id6") in calls and allowed(calls, "up.example.com") and recorded(web, "up.example.com", True)


def test_not_yet_approved_it_keeps_reading_untouched_until_this_mac_says_yes(web):
    ok, calls = sync(web, [{"hosts": ["up.example.com"], "write": True}], rec=reg_rec(("up.example.com", False)))
    assert ok and not [c for c in calls if c[:2] == ["policy", "rm"]] and no_allow(calls)
    assert recorded(web, "up.example.com", False)


def test_a_block_you_set_is_never_removed_only_allows_are(web):
    _, calls = sync(web, [], rec=reg_rec(("old.example.com", False)),
                     rules=erule("id8", "network", "-", "-", "old.example.com", decision="deny"))
    assert not [c for c in calls if c[:2] == ["policy", "rm"]]


def test_a_host_its_template_or_a_secret_grant_also_needs_stays_allowed_only_the_record_lets_go(web):
    _, calls = sync(web, [], rec=reg_rec(("shared.example.com", False), ("sec.example.com", False),
                                          egress=["shared.example.com"], secrets=[{"hosts": ["sec.example.com"]}]),
                     rules=erule("id5", "network", "-", "-", "shared.example.com"))
    assert not [c for c in calls if c[:2] == ["policy", "rm"]] and egress_rec(web) == []


def test_a_rule_og_didnt_apply_from_the_registry_is_never_removed(web):
    _, calls = sync(web, [], rules=erule("id4", "network", "-", "-", "byhand.example.com"))
    assert not [c for c in calls if c[:2] == ["policy", "rm"]]


def test_when_the_record_cant_be_saved_nothing_is_allowed(web):
    setup, w, state = web
    s = setup([{"hosts": ["api.example.com"]}])
    (state / "sandboxes").chmod(0o500)
    try:
        ok = egress.egress_sync("box", w)
    finally:
        (state / "sandboxes").chmod(0o700)
    assert not ok and no_allow(s.calls)


def test_a_secret_dropped_from_a_host_a_grant_only_reads_loses_its_whole_host_allow_and_reads_again(web):
    from ogun.secrets import grants
    setup, w, _ = web
    s = setup([{"hosts": ["api.example.com"]}, {"hosts": ["up.example.com"], "write": True}],
              rec=reg_rec(("api.example.com", False), ("up.example.com", True)), approved="personal/web\tup.example.com\n")
    grants.egress_drop("box", [], ["api.example.com", "up.example.com"])   # the secret on both hosts is gone
    assert ["policy", "rm", "network", "--sandbox", "box", "--resource", "api.example.com"] in s.calls
    assert not any("up.example.com" in c for c in s.calls if c[:2] == ["policy", "rm"])
    n = len(s.calls)
    egress.egress_sync("box", w)   # and the registry's sync sets the read-only rule again
    assert allowed(s.calls[n:], "api.example.com", "--method", "GET,HEAD")
    assert not allowed(s.calls[n:], "up.example.com")


@pytest.mark.parametrize(("grant", "says"), [
    ({"hosts": ["github.com"]}, "covers github.com"),            # reads are the baseline's, pushes og project add's
    ({"hosts": ["*.com"]}, "covers github.com"),
    ({"hosts": ["https://x.example.com/path"]}, "not a domain"),
    ({"hosts": ["a.example.com"], "write": "yes"}, "write: true|false"),
], ids=["github.com", "a pattern covering it", "not a domain", "write not a boolean"])
def test_refused_grants_allow_nothing_and_say_why(web, capfd, grant, says):
    _, calls = sync(web, [grant])
    assert no_allow(calls) and says in "".join(capfd.readouterr())


@pytest.mark.parametrize(("owner", "where"), [("", "web"), ("work", "web"), ("personal", "elsewhere")],
                         ids=["no owner", "another owner", "not the repo"])
def test_the_owner_gate_holds_for_egress(web, owner, where):
    setup, w, _ = web
    d = w if where == "web" else str(Path(w).parents[2] / "elsewhere/web")
    Path(d).mkdir(parents=True, exist_ok=True)
    s = setup([{"hosts": ["api.example.com"]}], owner=owner)
    egress.egress_sync("box", d)
    assert no_allow(s.calls)


def test_a_sandbox_with_no_create_record_changes_nothing_and_says_so_with_an_og_fix(web, capfd):
    _, calls = sync(web, [{"hosts": ["api.example.com"]}], rec=False)
    out = "".join(capfd.readouterr())
    assert no_allow(calls)
    assert "has no create record of og's (made outside og?)" in out and "og allow box api.example.com --read-only" in out
    assert "sbx " not in out and "ogun " not in out


def test_ogs_style_notes_on_stdout_the_approval_a_callout_and_no_grant_or_egress_in_its_words(web, capfd):
    sync(web, [{"hosts": ["new.example.com"]}, {"hosts": ["up.example.com"], "write": True, "for": "uploads"}],
         rec=reg_rec(("old.example.com", False)), rules=erule("id2", "network", "-", "-", "old.example.com"))
    out, err = capfd.readouterr()
    lines = out.splitlines()
    assert "  · box may reach new.example.com (reading only), as its registry entry lists" in lines
    assert "  · box: old.example.com removed (its registry entry no longer lists it)" in lines
    assert "────────────────────" in out + err and "SENDING DATA TO A DOMAIN" in out + err
    assert not re.search(r"(?i)grant|egress", out + err)


def test_og_policy_has_its_github_pushes_step_and_a_domains_step_and_brings_every_sandbox_in_line(og, web):
    setup, w, _ = web
    s = setup([{"hosts": ["api.example.com"]}], listing=f"SANDBOX  AGENT  STATUS  WORKSPACE\nbox  claude  stopped  {w}\n")
    _, out, err = og("policy")
    lines = (out + err).splitlines()
    assert "→ GitHub pushes: each sandbox to its own repos" in lines
    assert "→ Domains: each sandbox to the ones its repo's registry entry lists" in lines
    assert allowed(s.calls, "api.example.com", "--method", "GET,HEAD")


def test_create_and_both_attach_paths_run_it():
    assert Path(create.__file__).read_text().count("egress.egress_sync(name, d)") == 1
    assert "        egress.egress_sync(sb, ws)" in Path(session.__file__).read_text().splitlines()


# ── og allow: one sandbox unless --all says every sandbox ──

CHECKS = {   # what sbx's policy check answers, in its shape; it exits 1 for a no
    "api.github.com": ('{"action": "net:connect:tcp", "allowed": true, "target": "api.github.com:443", "type": "network"}', 0),
    "denied.example": ('{"allowed": false, "deny_kind": "explicit", "reason": "Blocked by local rule", "target": "denied.example:443"}', 1),
    "docs.docker.com": ('{"action": "net:connect:tcp", "allowed": false, "context": "sandbox:cub", "deny_kind": "authorization_required", '
                        '"reason": "Authorization required by policy", "target": "docs.docker.com:443", "type": "network"}', 1),
    "github.com": ('{"action": "net:connect:tcp", "allowed": false, "context": "sandbox:cub", "deny_kind": "authorization_required", '
                   '"reason": "Authorization required by policy", "target": "github.com:443", "type": "network"}', 1),
    "broken.example": ("", 1),
    "example.com": ('{"allowed": false, "deny_kind": "implicit", "reason": "No matching allow rule (default deny)", '
                    '"target": "example.com:443"}', 1),
}


@pytest.fixture
def cub(fakes, home):
    """sbx listing cub and fern; rules, the proxy log and check answers as given."""
    def set_(rules="", plog="", ls_fail=False, pls_fail=False, deny_fail=False, rm_fail=False, gone=False, fail_once=False):
        s = fakes.sbx
        s.clear()
        s.answer(["ls"], stdout="SANDBOX  AGENT  STATUS\ncub  claude  running\nfern  claude  stopped\n", code=1 if ls_fail else 0)
        s.answer(["policy", "log"], stdout=plog)
        for host, (out, code) in CHECKS.items():
            for scope in (["--sandbox", "cub"], []):
                s.answer(["policy", "check", "network", *scope, "--json", host], stdout=out, code=code)
        s.answer(["policy", "check"], stdout='{"allowed": false, "deny_kind": "implicit", '
                                             '"reason": "No matching allow rule (default deny)", "target": "x:443"}', code=1)
        s.answer(["policy", "ls"], stdout=rules, code=1 if pls_fail else 0)
        s.answer(["policy", "deny"], code=1 if deny_fail else 0)
        s.answer(["policy", "inspect"], code=1 if gone else 0)
        s.answer(["policy", "rm"], code=1 if rm_fail else 0)
        s.answer(["settings", "get"], stdout="false\n")
        if fail_once:
            s.answer(["policy", "allow"], code=1, once=True)
        return s
    return set_


def acted(s) -> list[list[str]]:
    """The calls that change something: every call but the reads."""
    reads = (["ls"], ["policy", "ls"], ["policy", "log"], ["policy", "check"], ["policy", "inspect"], ["settings", "get"])
    return [c for c in s.calls if not any(c[:len(r)] == r for r in reads)]


@pytest.mark.parametrize(("args", "call"), [
    (["cub", "example.com"], ["policy", "allow", "network", "--sandbox", "cub", "example.com"]),
    (["fern", "a.example", "b.example"], ["policy", "allow", "network", "--sandbox", "fern", "a.example,b.example"]),
    (["--all", "example.com"], ["policy", "allow", "network", "example.com"]),                 # only when asked for
    (["cub", "api.github.com", "*.example.com"], ["policy", "allow", "network", "--sandbox", "cub", "api.github.com,*.example.com"]),
    (["cub", "docs.example", "--read-only"], ["policy", "allow", "network", "--sandbox", "cub", "docs.example", "--method", "GET,HEAD"]),
    (["--read-only", "cub", "docs.example"], ["policy", "allow", "network", "--sandbox", "cub", "docs.example", "--method", "GET,HEAD"]),
    (["--all", "--read-only", "a.example", "b.example"], ["policy", "allow", "network", "a.example,b.example", "--method", "GET,HEAD"]),
], ids=["one sandbox", "several domains, one list", "--all", "a GitHub subdomain and a wildcard elsewhere",
        "--read-only", "--read-only first", "--read-only with --all"])
def test_og_allow_makes_exactly_this_rule(og, cub, args, call):
    s = cub()
    assert og("allow", *args)[0] == 0
    assert acted(s) == [call]


def test_a_github_repo_is_a_push_for_that_sandbox_in_both_address_forms(og, cub):
    s = cub()
    og("allow", "cub", "github.com/me/app")
    assert acted(s) == [["policy", "allow", "network", "--sandbox", "cub", "github.com", "--method", "POST", "--path", p]
                        for p in ("/me/app.git/git-receive-pack", "/me/app/git-receive-pack")]


def test_a_full_address_and_dot_git_are_the_same_repo_other_domains_still_one_list(og, cub):
    s = cub()
    og("allow", "cub", "https://github.com/me/app.git", "example.com")
    assert ["policy", "allow", "network", "--sandbox", "cub", "github.com", "--method", "POST",
            "--path", "/me/app.git/git-receive-pack"] in acted(s)
    assert ["policy", "allow", "network", "--sandbox", "cub", "example.com"] in acted(s)


@pytest.mark.parametrize(("args", "says"), [
    (["example.com", "api.example.com"], "no sandbox 'example.com'"),   # the old global form, naming --all
    (["example.com"], "usage: og allow"),
    (["cub", "example.com", "github.com"], "github.com/<owner>/<repo>"),
    (["cub"], "usage: og allow"),
    (["cub", "github.com/me/app", "--read-only"], ""),                   # a push can't be read-only
    (["cub", "--read-only"], ""),
    (["--all", "github.com/me/app"], ""),                                # a push is per sandbox
    (["cub", "github.com/me/*"], ""),                                    # glob characters in a repo
    (["--", "cub", "example.com"], ""),
    (["cub", "example.com", "--chec"], "usage: og allow "),
    (["--all", "-x", "example.com"], ""),
], ids=["old global form", "a domain alone", "all of github.com", "no domain", "a push read-only", "--read-only alone",
        "a push for --all", "a glob in a repo", "--", "a mistyped option", "an unknown option"])
def test_og_allow_refuses_allowing_nothing(og, cub, args, says):
    s = cub()
    code, out, err = og("allow", *args)
    assert code == 1 and says in out + err and acted(s) == []
    if args[0] == "example.com" and len(args) == 2:
        assert "--all" in out + err


@pytest.mark.parametrize("pattern", ["*github.com", "*.com", "**", "git*", "http://github.com", "GitHub.com:443", "*hub.com/"])
def test_any_pattern_covering_github_is_refused_for_one_sandbox_or_all(og, cub, pattern):
    s = cub()
    code, out, err = og("allow", "cub", "example.com", pattern)
    assert code == 1 and ("would also cover github.com" in out + err or "not all of github.com" in out + err)
    assert og("allow", "--all", pattern)[0] == 1
    assert acted(s) == []


def test_allow_all_github_names_one_sandbox_in_its_fix_never_all(og, cub):
    cub()
    code, out, err = og("allow", "--all", "github.com")
    assert code == 1 and any(re.fullmatch(r" *og allow <name> github.com/<owner>/<repo>", x) for x in (out + err).splitlines())


H_ = LS_HEAD


def test_a_domain_a_block_also_covers_is_allowed_with_a_line_saying_the_block_wins(og, cub):
    cub(rules=f"{H_}\nlocal  added  all  -  local-policy  -  id1  network  -  -  deny  tcp  *.example.com\n")
    code, out, err = og("allow", "cub", "api.example.com")
    assert code == 0 and "api.example.com is also blocked" in out + err and "og net --all '*.example.com' --rm" in out + err


def test_one_for_that_sandbox_names_it_another_sandboxs_block_says_nothing(og, cub):
    cub(rules=f"{H_}\nlocal  added  sandbox:cub  -  ff  -  id1  network  -  -  deny  tcp  example.com\n"
              "local  added  sandbox:fern  -  ff  -  id2  network  -  -  deny  tcp  other.example\n")
    code, out, err = og("allow", "cub", "example.com", "other.example")
    assert code == 0 and "og net cub example.com --rm" in out + err and "other.example is also" not in out + err


def test_no_block_no_line(og, cub):
    cub(rules=f"{H_}\nlocal  added  all  -  local-policy  -  id1  network  -  -  allow  tcp  example.com\n")
    assert "blocked" not in "".join(og("allow", "cub", "example.com")[1:])


def test_read_only_over_a_whole_host_allow_for_that_sandbox_says_it_has_no_effect_and_how(og, cub):
    cub(rules=f"{H_}\nlocal  added  sandbox:cub  -  ff  -  id1  network  -  -  allow  tcp  cloud.example\n")
    out = "".join(og("allow", "cub", "cloud.example", "--read-only")[1:])
    assert "cloud.example is also allowed for everything for cub, so reading only has no effect" in out
    assert "og net cub cloud.example --rm, then og net cub cloud.example --read-only" in out


def test_not_for_another_sandboxs_a_global_one_or_its_own_read_only_rule(og, cub):
    cub(rules=f"{H_}\nlocal  added  sandbox:fern  -  ff  -  id1  network  -  -  allow  tcp  cloud.example\n"
              "local  added  all  -  local-policy  -  id2  network  -  -  allow  tcp  cloud.example\n"
              "local  added  sandbox:cub  -  ff  -  id3  http  GET,HEAD  /**  allow  -  cloud.example\n")
    assert "allowed for everything" not in "".join(og("allow", "cub", "cloud.example", "--read-only")[1:])


def test_og_v_allow_shows_each_sbx_command_on_stderr(og, cub):
    s = cub()
    code, _, err = og("-v", "allow", "cub", "example.com")
    assert code == 0 and "$ sbx policy allow network --sandbox cub example.com" in err
    assert acted(s) == [["policy", "allow", "network", "--sandbox", "cub", "example.com"]]


@pytest.mark.parametrize("args", [["cub", "github.com/me/app", "--help"], ["-h", "cub", "example.com"], ["cub", "example.com", "--help"]])
def test_help_anywhere_in_og_allow_is_help_with_each_form_and_examples_and_allows_nothing(og, cub, args):
    s = cub()
    code, out, _ = og("allow", *args)
    assert code == 0 and "usage: og allow" in out and acted(s) == []
    if args[-1] == "--help" and "example.com" in args:
        assert "Examples:" in out and "--read-only" in out


def test_og_allow_alone_piped_is_its_one_usage_line(og, cub):
    code, out, err = og("allow")
    assert code == 1 and (out + err).strip() == f"usage: og allow {allow.ALLOW_USAGE}"


# ── og allow's parts: who it's for, what's named, the pushes, the domains ──

def test_one_sandbox_is_its_scope_every_sandbox_none_and_known_asks_sbx_nothing(cub):
    s = cub()
    assert allow.scope("allow", "--all", False) == [] and s.calls == []
    assert allow.scope("allow", "zed", True) == ["--sandbox", "zed"] and s.calls == []
    assert allow.scope("allow", "cub", False) == ["--sandbox", "cub"] and s.calls == [["ls"]]


def test_a_sandbox_sbx_doesnt_list_or_cant_list_is_no_scope(cub, capfd):
    cub()
    assert allow.scope("allow", "nobody", False) is None and "no sandbox 'nobody'" in "".join(capfd.readouterr())
    cub(ls_fail=True)
    assert allow.scope("net", "cub", False) is None and "og net: sbx couldn't list" in "".join(capfd.readouterr())


def test_whats_named_sorts_into_domains_and_repos(cub):
    assert allow.targets("allow", "cub", ["--sandbox", "cub"], ["a.example", "github.com/me/app", "https://github.com/me/b.git"]) \
        == (["a.example"], ["me/app", "me/b"])
    assert allow.targets("allow", "--all", [], ["a.example", "b.example"]) == (["a.example", "b.example"], [])


@pytest.mark.parametrize(("who", "scope", "named", "says"), [
    ("cub", ["--sandbox", "cub"], ["a.example", "github.com"], "not all of github.com"),
    ("cub", ["--sandbox", "cub"], ["*.com"], "would let cub push"),
    ("--all", [], ["git*"], "would let every sandbox push"),
    ("cub", ["--sandbox", "cub"], ["github.com/me/*"], "name a repo as github.com/<owner>/<repo>"),
    ("--all", [], ["github.com/me/app"], "a push is allowed per sandbox"),
])
def test_what_would_reach_too_far_is_none_and_said(cub, capfd, who, scope, named, says):
    assert allow.targets("allow", who, scope, named) is None and says in "".join(capfd.readouterr())


def test_each_push_is_allowed_one_that_fails_is_said_the_rest_still_go(cub, capfd, monkeypatch):
    s = cub()
    assert allow.pushes("allow", "cub", ["me/app"]) == 0 and "cub may push to github.com/me/app" in "".join(capfd.readouterr())
    assert any(c[:6] == ["policy", "allow", "network", "--sandbox", "cub", "github.com"] for c in acted(s))
    tried = []
    monkeypatch.setattr(allow.pushrules, "push_allow", lambda who, slug: tried.append(slug) or slug != "me/bad")
    assert allow.pushes("allow", "cub", ["me/bad", "me/ok"]) == 1 and tried == ["me/bad", "me/ok"]
    assert "could not allow the push to me/bad" in "".join(capfd.readouterr())


def test_domains_are_one_rule_read_only_its_methods_and_sbx_failing_is_false(cub):
    s = cub()
    assert allow.hosts("allow", ["--sandbox", "cub"], ["a.example", "b.example"], True) is True
    assert acted(s) == [["policy", "allow", "network", "--sandbox", "cub", "a.example,b.example", "--method", "GET,HEAD"]]
    s = cub()
    s.answer(["policy", "allow"], code=1)
    assert allow.hosts("allow", [], ["a.example"], False) is False


def boxed(monkeypatch, capfd, columns=None) -> str:
    """og allow with nothing, drawn as on a terminal."""
    from ogun.core import log
    if columns:
        monkeypatch.setenv("COLUMNS", str(columns))
    log._consoles.clear()
    monkeypatch.setattr(log, "pretty", lambda err=False: True)
    allow.allow([])
    log._consoles.clear()
    return re.sub(r"\x1b\[[0-9;]*m", "", "".join(capfd.readouterr()))


def test_on_a_terminal_what_is_missing_then_a_box_with_every_form_and_real_examples(home, monkeypatch, capfd):
    box = boxed(monkeypatch, capfd)
    for want in ("✗ og allow needs a sandbox name", "╭─ og allow", "og allow cub files.example.com --read-only", "og allow --all <domain>"):
        assert want in box


@pytest.mark.parametrize("width", [40, 50])
def test_in_a_narrow_pane_every_form_keeps_what_it_does(home, monkeypatch, capfd, width):
    box = boxed(monkeypatch, capfd, width)
    assert "for every" in box and "a push to that repo" in box and "reading only" in box


def test_og_allow_when_sbx_cant_list_its_sandboxes_says_so_never_no_such_sandbox(og, cub):
    s = cub(ls_fail=True)
    code, out, err = og("allow", "cub", "x.example")
    assert code == 1 and "couldn't list its sandboxes" in out + err and "no sandbox" not in out + err and acted(s) == []


def test_without_sbx_og_allow_says_sbx_is_missing(og, home, monkeypatch):
    monkeypatch.setenv("PATH", f"{os.path.dirname(REAL_GIT)}:/usr/bin:/bin")
    code, out, err = og("allow", "--all", "example.com")
    assert code != 0 and "sbx: command not found" in out + err


# ── the baseline ──

def test_the_baseline_takes_out_a_default_rule_thats_there_and_leaves_one_thats_gone(cub, capfd):
    s = cub()
    assert baseline.baseline()
    assert ["policy", "rm", "network", "--id", "default-ai-services", "--force"] in s.calls
    assert "removed sbx" in capfd.readouterr().err
    s = cub(gone=True)
    n = len(s.calls)
    assert baseline.baseline() and not [c for c in s.calls[n:] if c[:2] == ["policy", "rm"]]


def test_a_default_rule_removal_that_fails_fails_the_baseline_with_the_command(cub, capfd):
    cub(rm_fail=True)
    assert not baseline.baseline()
    assert "sbx policy rm network --id default-ai-services --force" in capfd.readouterr().err


def test_a_baseline_call_sbx_refuses_once_is_tried_again_and_the_baseline_holds(cub):
    s = cub(gone=True, fail_once=True)
    assert baseline.baseline()
    assert len([c for c in s.calls if c[:3] == ["policy", "allow", "network"] and c[3].startswith("deb.debian.org")]) == 2
    assert ["policy", "allow", "network", "github.com", "--method", "GET,HEAD"] in s.calls


# ── og policy's errors ──

def test_og_policy_with_rules_sbx_couldnt_list_is_not_all_clear_exit_1(og, cub):
    cub(pls_fail=True)
    code, out, err = og("policy")
    assert code == 1 and "couldn't list its rules" in out + err
    assert "none left" not in out + err and "only per-repo pushes" not in out + err


def test_og_policy_with_sandboxes_sbx_couldnt_list_is_an_error_never_no_sandboxes(og, cub):
    cub(ls_fail=True)
    code, out, err = og("policy")
    assert code == 1 and "couldn't list its sandboxes" in out + err and "no sandboxes" not in out + err


def test_og_policy_names_each_sandboxs_pushes_allowed_and_a_failed_one_apart(monkeypatch, capfd):
    monkeypatch.setattr(pushrules, "push_repos", lambda d: ["me/app", "me/site"])
    monkeypatch.setattr(pushrules, "push_allow", lambda sb, slug: slug != "me/site")
    assert pushrules.push_rules("cub", "/w", say=False) is False
    out = "".join(capfd.readouterr())
    assert re.search(r"cub may push to me/app$", out, re.M) and "couldn't allow cub to push to me/site" in out


@pytest.mark.parametrize(("args", "says", "code"), [(["--"], "takes no arguments", 1), (["-h"], "safety settings", 0)])
def test_og_policy_dashdash_is_refused_and_h_is_its_help_applying_nothing(og, cub, args, says, code):
    s = cub()
    c, out, err = og("policy", *args)
    assert c == code and says in out + err and acted(s) == []


# ── og net: list, allow (the default), block, take back ──

NET_RULES = f"""{LS_HEAD}
kit  provisioned  sandbox:cub  -  p0  kit:cub  id0  network  -  -  allow  tcp  api.anthropic.com:443
local  added  all  -  p1  -  id1  network  -  -  allow  tcp  deb.debian.org
local  added  all  -  p1  -  id10  http  POST  /*/*/git-upload-pack  allow  -  github.com
local  added  sandbox:cub  -  p2  -  id2  network  -  -  allow  tcp  docs.example.com:443
local  added  sandbox:cub  -  p2  -  id3  http  GET,HEAD  /**  allow  -  dl.example.com
local  added  sandbox:cub  -  p2  -  id4  network  -  -  deny  tcp  tracker.example.com
local  added  sandbox:cub  -  p2  -  id5  http  POST  /me/app.git/git-receive-pack  allow  -  github.com
local  added  sandbox:cub  -  p2  -  id6  http  POST  /me/app/git-receive-pack  allow  -  github.com
local  added  sandbox:cub  -  p2  -  id7  http  POST  /me/site.git/git-receive-pack  allow  -  github.com
local  added  sandbox:cub  -  p2  -  id8  http  POST  /me/site/git-receive-pack  allow  -  github.com
local  added  sandbox:cub  -  p2  -  id11  http  POST  /me/app.git/info/lfs/objects/batch  allow  -  github.com
local  added  sandbox:cub  -  p2  -  id12  http  POST  /me/secret.git/git-receive-pack  deny  -  github.com
local  added  sandbox:cub  -  p2  -  id13  network  -  -  allow  tcp  github.com
local  added  sandbox:cub  -  p2  -  id14  network  -  -  allow  tcp  a.example
                                                                                   b.example
local  added  sandbox:fern  -  p3  -  id9  network  -  -  allow  tcp  fern-only.example
"""


def rows(out) -> list[list[str]]:
    return [x.split() for x in out.splitlines()]


def row(out, first) -> list[str]:
    return next(r for r in rows(out) if r and r[0] == first)


def test_og_net_name_lists_what_applies_a_repos_two_push_rules_one_row_another_sandboxs_none(og, cub):
    s = cub(rules=NET_RULES)
    code, out, _ = og("net", "cub")
    assert code == 0 and acted(s) == []
    assert row(out, "github.com/me/app")[1:3] == ["push", "this"] and sum(r[:2] == ["github.com/me/app", "push"] for r in rows(out)) == 1
    assert row(out, "docs.example.com")[1:3] == ["allowed", "this"] and row(out, "dl.example.com")[1] == "read-only"
    assert row(out, "tracker.example.com")[1] == "blocked" and row(out, "deb.debian.org")[1:3] == ["allowed", "every"]
    assert row(out, "b.example")[1] == "allowed" and "fern-only" not in out


def test_sbxs_own_rules_are_counted_not_listed_sbx_lists_them_marked_v_changes_nothing(og, cub):
    cub(rules=NET_RULES)
    out = og("net", "cub")[1]
    assert "api.anthropic.com" not in out and re.search(r"and 1 of sbx.s own rules: og net cub --sbx", out)
    assert og("-v", "net", "cub")[1] == out
    assert og("net", "cub", "example.com", "--sbx")[0] != 0
    v = og("net", "cub", "--sbx")[1]
    assert re.search(r"(?m)^api.anthropic.com +allowed +this sandbox +sbx.s own", v) and not re.search("of sbx.s own rules", v)


def test_on_a_terminal_a_push_and_a_block_are_marked_and_the_shared_rules_dim(cub, monkeypatch, capfd):
    from ogun.core import log
    cub(rules=NET_RULES)
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("COLUMNS", "120")
    log._consoles.clear()
    monkeypatch.setattr(log, "pretty", lambda err=False: True)
    netcmd.net(["cub"])
    log._consoles.clear()
    box = "".join(capfd.readouterr())
    line = {k: next(x for x in box.splitlines() if k in x) for k in
            ("github.com/me/app ", "tracker.example.com", "dl.example.com", "docs.example.com", "deb.debian.org")}
    assert "▸ push" in line["github.com/me/app "] and "✗ blocked" in line["tracker.example.com"]
    assert "read-only" in line["dl.example.com"] and "○" not in line["dl.example.com"] and "○" not in line["docs.example.com"]
    assert "\x1b[2mallowed" in line["deb.debian.org"] and "\x1b[2mallowed" not in line["docs.example.com"]


def test_a_rule_limited_to_a_path_or_method_shows_it_the_whole_host_one_plain(og, cub):
    cub(rules=NET_RULES)
    out = og("net", "cub")[1]
    assert re.search(r"(?m)^github.com/\*/\*/git-upload-pack +allowed \(POST\) +every sandbox", out)
    assert re.search(r"(?m)^github.com/me/app.git/info/lfs/objects/batch +allowed \(POST\) +this sandbox", out)
    assert re.search(r"(?m)^github.com/me/secret.git/git-receive-pack +blocked \(POST\)", out)
    assert not re.search(r"(?m)^github.com/me/secret +push", out) and re.search(r"(?m)^github.com +allowed +this sandbox", out)


def test_og_net_name_domain_allows_in_ogs_own_words(og, cub):
    s = cub()
    code, out, err = og("net", "cub", "example.com")
    assert code == 0 and acted(s) == [["policy", "allow", "network", "--sandbox", "cub", "example.com"]]
    assert "cub may reach example.com" in out + err


def test_deny_blocks_for_that_sandbox_or_all(og, cub):
    s = cub()
    og("net", "cub", "ads.example", "--deny")
    og("net", "--all", "ads.example", "--deny")
    assert acted(s) == [["policy", "deny", "network", "--sandbox", "cub", "ads.example"], ["policy", "deny", "network", "ads.example"]]


def rm_net(id_, sb="cub"):
    return ["policy", "rm", "network", "--id", id_, *(["--sandbox", sb] if sb else []), "--force"]


def test_rm_takes_back_a_domains_rules_by_id_read_only_too_no_y_n_for_a_sandbox_or_all(og, cub):
    s = cub(rules=NET_RULES)
    for args in (["cub", "docs.example.com"], ["cub", "dl.example.com"], ["--all", "deb.debian.org"]):
        og("net", *args, "--rm")
    assert acted(s) == [rm_net("id2"), rm_net("id3"), rm_net("id1", sb="")]


def test_a_host_sharing_a_rule_the_rule_goes_the_other_host_set_again_as_it_was(og, cub):
    s = cub(rules=NET_RULES)
    og("net", "cub", "a.example", "--rm")
    assert acted(s) == [rm_net("id14"), ["policy", "allow", "network", "--sandbox", "cub", "b.example"]]


def test_a_blocked_host_whose_shared_rule_cant_be_set_again_is_fixed_by_blocking_it_again(og, cub):
    cub(rules=f"{LS_HEAD}\nlocal  added  sandbox:cub  -  p2  -  id30  network  -  -  deny  tcp  a2.example\n"
              "                                                     b2.example\n", deny_fail=True)
    code, out, err = og("net", "cub", "a2.example", "--rm")
    assert code == 1 and any(re.fullmatch(r" *og net cub b2.example --deny", x) for x in (out + err).splitlines())


def test_both_hosts_of_a_shared_rule_removed_at_once_the_rule_goes_once_neither_added_back(og, cub):
    s = cub(rules=NET_RULES)
    code, out, err = og("net", "cub", "a.example", "b.example", "--rm")
    assert code == 0 and acted(s) == [rm_net("id14")]
    assert "removed the rule for a.example" in out + err and "removed the rule for b.example" in out + err


@pytest.mark.parametrize(("target", "ids"), [("github.com/me/app", ["id5", "id6"]), ("github.com", ["id13"])],
                         ids=["a repo's two push rules", "github.com's whole-host rule only"])
def test_rm_of_github_removes_exactly_its_rules(og, cub, target, ids):
    s = cub(rules=NET_RULES)
    og("net", "cub", target, "--rm")
    assert acted(s) == [rm_net(i) for i in ids]


def test_nothing_to_remove_fails_saying_so_and_asks_sbx_nothing(og, cub):
    s = cub(rules=NET_RULES)
    code, out, err = og("net", "cub", "nothing.example", "--rm")
    assert code != 0 and "og net: no rule for nothing.example on cub to remove" in out + err and acted(s) == []


def test_a_removal_sbx_refuses_neither_says_nor_records_the_push_removed(og, cub):
    from ogun.core import paths
    cub(rules=NET_RULES, rm_fail=True)
    code, out, err = og("net", "cub", "github.com/me/app", "--rm")
    log_file = paths.state_dir() / "og.log"
    assert code != 0 and "failed" in out + err and "push to github.com/me/app" not in out + err
    assert not log_file.exists() or log_file.read_text() == ""


@pytest.mark.parametrize("args", [["cub", "github.com"], ["cub", "github.com", "--deny"], ["cub", "**", "--deny"],
                                  ["cub", "github.com/me/app", "--deny"], ["--all", "github.com/me/app", "--rm"],
                                  ["cub", "x.example", "--deny", "--rm"], ["nosuch", "x.example"], ["cub", "--rm"],
                                  ["cub", "example.com", "--chec"], ["cub", "-x", "--read-only"]])
def test_og_net_refuses_asking_sbx_nothing(og, cub, args):
    s = cub()
    assert og("net", *args)[0] != 0
    assert acted(s) == [] and not [c for c in s.calls if c[:2] == ["policy", "check"]]


def test_a_repo_blocked_and_a_repo_for_all_each_say_their_own_why_with_the_rm_line(og, cub):
    cub()
    lines = "".join(og("net", "cub", "github.com/me/app", "--deny")[1:]).splitlines()
    assert any(re.fullmatch(r"og net: a repo push can.t be blocked, only removed:", x) for x in lines)
    assert "og net cub github.com/me/app --rm" in [x.strip() for x in lines]
    lines = "".join(og("net", "--all", "github.com/me/app", "--rm")[1:]).splitlines()
    assert "og net: a push is per sandbox — name it:" in lines and "og net <name> github.com/me/app --rm" in [x.strip() for x in lines]


def test_help_anywhere_in_og_net_is_help_and_changes_nothing(og, cub):
    s = cub()
    code, out, _ = og("net", "cub", "x.example", "--rm", "--help")
    assert code == 0 and out.startswith("usage: og net ") and acted(s) == []


# ── og net's parts: the sandbox it's for, and what's named to block or remove ──

def test_every_sandbox_asks_sbx_nothing_one_must_be_in_its_listing(cub, capfd):
    s = cub()
    assert netcmd.listed("--all") is True and s.calls == []
    assert netcmd.listed("fern") is True
    assert netcmd.listed("nosuch") is False and "og net: no sandbox 'nosuch'" in "".join(capfd.readouterr())
    cub(ls_fail=True)
    assert netcmd.listed("cub") is False and "couldn't list its sandboxes" in "".join(capfd.readouterr())


def test_whats_named_to_block_or_remove_sorts_into_domains_and_repos(cub):
    assert netcmd.named("cub", False, ["a.example", "github.com/me/app"]) == (["a.example"], ["me/app"])
    assert netcmd.named("cub", True, ["a.example", "b.example"]) == (["a.example", "b.example"], [])
    assert netcmd.named("--all", False, ["**"]) == (["**"], [])   # removing what og policy names


@pytest.mark.parametrize(("who", "deny", "named", "says"), [
    ("cub", True, ["**"], "would block github.com too"),
    ("cub", False, ["github.com/me/*"], "name a repo as github.com/<owner>/<repo>"),
    ("cub", True, ["github.com/me/app"], "a repo push can't be blocked"),
    ("--all", False, ["github.com/me/app"], "a push is per sandbox"),
])
def test_what_cant_be_blocked_or_removed_so_is_none_and_said(cub, capfd, who, deny, named, says):
    assert netcmd.named(who, deny, named) is None and says in "".join(capfd.readouterr())


# ── og net --log: what the proxy blocked ──

PLOG = json.dumps({   # in the shape sbx's log --json gives
    "allowed": [{"sandbox_id": "cub", "host": "api.anthropic.com:443", "proxy_type": "forward", "count": 1204,
                 "first_seen": "2026-03-04T09:00:00-05:00", "last_seen": "2026-03-12T18:30:00-05:00"}],
    "blocked": [
        {"sandbox_id": "cub", "host": "docs.docker.com:443", "proxy_type": "forward",
         "rule": "no applicable policies for op(action=net:connect:tcp, resource=net:domain:docs.docker.com:443)",
         "reason": "No matching allow rule (default deny)", "count": 2,
         "first_seen": "2026-03-12T15:00:00-05:00", "last_seen": "2026-03-12T15:05:00-05:00"},
        {"sandbox_id": "cub", "host": "registry.npmjs.org:443", "proxy_type": "forward",
         "rule": "no applicable policies for op(action=http:request:post, via=net:connect:tcp, resource=http:endpoint[http:domain["
                 "net:domain:registry.npmjs.org:443,http:path:/-/npm/v1/security/audits/quick]])",
         "reason": "No matching allow rule (default deny)", "count": 2,
         "first_seen": "2026-03-08T11:00:00-05:00", "last_seen": "2026-03-08T11:30:00-05:00"},
        {"sandbox_id": "cub", "host": "telemetry.example.com:443", "proxy_type": "forward",
         "rule": "no applicable policies for op(action=net:connect:tcp, resource=net:domain:telemetry.example.com:443)",
         "reason": "No matching allow rule (default deny)", "count": 377,
         "first_seen": "2026-03-04T09:00:30-05:00", "last_seen": "2026-03-12T18:00:00-05:00"}]})


def test_og_net_log_a_row_a_host_blocked_newest_first_then_allowed_and_how_to_allow_one(og, cub):
    s = cub(plog=PLOG)
    code, out, _ = og("net", "cub", "--log")
    lines = out.splitlines()
    assert code == 0 and ["policy", "log", "cub", "--json"] in s.calls
    assert lines[0].split() == ["HOST", "STATE", "TIMES", "LAST", "SEEN"]
    assert [f"{x.split()[0]}/{x.split()[1]}" for x in lines[1:5]] == [
        "telemetry.example.com/blocked", "docs.docker.com/blocked", "registry.npmjs.org/blocked", "api.anthropic.com/allowed"]
    assert re.search(r"(?m)^docs.docker.com +blocked +2 +03-12 \d\d:\d\d$", out)
    assert "registry.npmjs.org: only POST /-/npm/v1/security/audits/quick was blocked" in lines
    assert "docs.docker.com: only" not in out and "to allow one: og allow cub <host> --read-only" in out


def test_v_changes_nothing_n_keeps_the_newest_of_each_all_names_each_sandbox(og, cub):
    cub(plog=PLOG)
    out = og("net", "cub", "--log")[1]
    assert og("-v", "net", "cub", "--log")[1] == out
    n1 = og("net", "cub", "--log", "-n", "1")[1]
    assert len(re.findall(r" (blocked|allowed) ", n1)) == 2 and "the newest 1 of each; all of them: og net cub --log -n 0" in n1
    a = og("net", "--all", "--log")[1]
    assert re.search(r"(?m)^cub +docs.docker.com +blocked", a) and "to allow one" not in a
    assert "cub: registry.npmjs.org: only POST /-/npm/v1/security/audits/quick was blocked" in a.splitlines()


def test_an_empty_log_is_no_rows_a_log_sbx_couldnt_give_is_an_error(og, cub):
    cub(plog='{"allowed": [], "blocked": []}')
    code, out, err = og("net", "cub", "--log")
    assert code == 0 and out + err == ""
    cub(plog="not json")
    assert og("net", "cub", "--log")[0] != 0


def test_og_net_log_sorts_by_the_moment_not_the_text_across_a_clock_change(og, cub):
    cub(plog=json.dumps({"allowed": [], "blocked": [
        {"host": "early.example:443", "rule": "", "reason": "", "count": 1, "last_seen": "2026-11-01T01:50:00-04:00"},
        {"host": "late.example:443", "rule": "", "reason": "", "count": 1, "last_seen": "2026-11-01T01:10:00-05:00"}]}))
    out = og("net", "cub", "--log", "-n", "1")[1]
    assert re.search(r"(?m)^late.example ", out) and "early.example" not in out


def test_og_net_on_a_list_sbx_couldnt_give_says_so_never_no_such_sandbox(og, cub):
    cub(ls_fail=True)
    code, out, err = og("net", "cub", "--log")
    assert code == 1 and "couldn't list" in out + err and "no sandbox" not in out + err


# ── og net --check: would it be allowed ──

def test_check_a_row_yes_and_all_exit_0_nothing_changed(og, cub):
    s = cub()
    code, out, _ = og("net", "cub", "api.github.com", "--check")
    assert code == 0 and [x.split() for x in out.splitlines()] == [["HOST", "ALLOWED", "ACCESS"], ["api.github.com", "yes", "all"]]
    assert [c for c in s.calls if c[:2] == ["policy", "check"]] == [["policy", "check", "network", "--sandbox", "cub", "--json", "api.github.com"]]
    assert acted(s) == []


def test_blocked_with_no_rule_no_exit_3_with_the_og_allow_that_would_open_it(og, cub):
    cub()
    code, out, err = og("net", "cub", "example.com", "--check")
    assert code == 3 and re.search(r"(?m)^example.com +no +none$", out + err)
    assert "to allow it: og allow cub example.com --read-only" in (out + err).splitlines()


def test_blocked_by_a_rule_points_at_the_rules_one_row_a_host_and_all_asks_every_sandbox(og, cub):
    s = cub()
    code, out, err = og("net", "cub", "denied.example", "example.com", "--check")
    lines = (out + err).splitlines()
    assert code == 3 and "denied.example: blocked by a rule; to see it: og net cub" in lines
    assert "to allow it: og allow cub example.com --read-only" in lines and sum(" no " in x for x in lines) == 2
    n = len(s.calls)
    og("net", "--all", "api.github.com", "--check")
    assert ["policy", "check", "network", "--json", "api.github.com"] in s.calls[n:]


def test_a_host_with_only_read_only_http_rules_is_a_yes_read_exit_0(og, cub):
    cub(rules=f"{LS_HEAD}\nlocal  added  all  -  p1  -  id1  http  GET,HEAD  /**  allow  -  docs.docker.com\n")
    code, out, _ = og("net", "cub", "docs.docker.com", "--check")
    assert code == 0 and re.search(r"(?m)^docs.docker.com +yes +read$", out)


def test_github_the_clone_post_is_reading_each_repos_push_rules_one_push_another_sandboxs_none(og, cub):
    rules = "\n".join(x for x in NET_RULES.splitlines() if "network  -  -  allow  tcp  github.com" not in x)
    rules += ("\nlocal  added  all  -  p1  -  id20  http  GET,HEAD  /**  allow  -  github.com"
              "\nlocal  added  sandbox:fern  -  p3  -  id21  http  POST  /me/fern.git/git-receive-pack  allow  -  github.com\n")
    cub(rules=rules)
    code, out, _ = og("net", "cub", "github.com", "--check")
    assert code == 0 and re.search(r"(?m)^github.com +yes +read · push to me/app, me/site$", out)


def test_authorization_required_with_no_rule_letting_anything_through_is_no_exit_3(og, cub):
    cub()
    code, out, err = og("net", "cub", "docs.docker.com", "--check")
    assert code == 3 and re.search(r"(?m)^docs.docker.com +no +none$", out + err)
    assert "docs.docker.com: blocked by a rule; to see it: og net cub" in (out + err).splitlines()


def test_sbx_unable_to_answer_is_exit_1_the_answers_it_gave_still_shown_check_alone_is_usage(og, cub):
    cub()
    assert og("net", "cub", "broken.example", "--check")[0] == 1
    assert og("net", "cub", "--check")[0] != 0
    code, out, err = og("net", "cub", "api.github.com", "broken.example", "--check")
    assert code == 1 and re.search(r"(?m)^api.github.com +yes +all$", out + err) and "couldn't say whether broken.example" in out + err


def test_a_mistyped_option_among_the_domains_is_usage_and_never_reaches_sbx(og, cub):
    s = cub()
    code, out, err = og("net", "cub", "-n", "--check")
    assert code == 1 and (out + err).startswith("usage: og net ") and not [c for c in s.calls if c[:2] == ["policy", "check"]]


# ── a sync's parts: the hosts leaving, the hosts new ──

def test_a_leaving_host_has_its_allow_removed_by_id_and_leaves_the_record(fakes, capfd):
    fakes.sbx.answer(["policy", "ls"], stdout=erule("id9", "http", "GET,HEAD", "/**", "old.example.com"))
    assert egress.remove_gone("box", "box", ["old.example.com"], {}, set()) == (["old.example.com"], True)
    assert rm_id("id9") in fakes.sbx.calls
    assert "box: old.example.com removed (its registry entry no longer lists it)" in "".join(capfd.readouterr())


def test_one_another_rule_needs_leaves_the_record_its_rule_untouched(fakes):
    fakes.sbx.answer(["policy", "ls"], stdout=erule("id9", "http", "GET,HEAD", "/**", "kept.example.com"))
    assert egress.remove_gone("box", "box", ["kept.example.com"], {}, {"kept.example.com"}) == (["kept.example.com"], True)
    assert not [c for c in fakes.sbx.calls if c[:2] == ["policy", "rm"]]


def test_a_block_on_a_leaving_host_is_yours_and_stays(fakes):
    fakes.sbx.answer(["policy", "ls"], stdout=erule("id9", "network", "-", "-", "old.example.com", decision="deny"))
    assert egress.remove_gone("box", "box", ["old.example.com"], {}, set()) == (["old.example.com"], True)
    assert not [c for c in fakes.sbx.calls if c[:2] == ["policy", "rm"]]


def test_a_rule_sbx_wont_remove_keeps_its_host_on_the_record(fakes):
    fakes.sbx.answer(["policy", "ls"], stdout=erule("id9", "http", "GET,HEAD", "/**", "old.example.com"))
    fakes.sbx.answer(["policy", "rm"], code=1)
    assert egress.remove_gone("box", "box", ["old.example.com"], {}, set()) == ([], False)


def test_rules_sbx_cant_list_remove_nothing_and_say_so(fakes, capfd):
    fakes.sbx.answer(["policy", "ls"], code=1)
    assert egress.remove_gone("box", "og box", ["old.example.com"], {}, set()) == ([], False)
    assert "og og box: couldn't read box's rules from sbx" in "".join(capfd.readouterr())


def test_new_hosts_read_only_unless_they_write_each_said_and_recorded(fakes, capfd):
    want = {"r.example.com": {"write": False}, "w.example.com": {"write": True}}
    assert egress.allow_new("box", ["r.example.com", "w.example.com"], want, True) == []
    assert ["policy", "allow", "network", "--sandbox", "box", "r.example.com", "--method", "GET,HEAD"] in fakes.sbx.calls
    assert ["policy", "allow", "network", "--sandbox", "box", "w.example.com"] in fakes.sbx.calls
    assert "box may reach r.example.com (reading only), as its registry entry lists" in "".join(capfd.readouterr())


def test_a_new_host_sbx_refuses_is_returned_with_the_og_allow_to_run(fakes, capfd):
    fakes.sbx.answer(["policy", "allow"], code=1)
    assert egress.allow_new("box", ["r.example.com"], {"r.example.com": {"write": False}}, False) == ["r.example.com"]
    assert "og allow box r.example.com --read-only" in "".join(capfd.readouterr())


def test_another_sandboxs_allow_of_the_same_host_is_never_removed(fakes):
    fakes.sbx.answer(["policy", "ls"], stdout=erule("id8", "http", "GET,HEAD", "/**", "old.example.com",
                                                    scope="sandbox:other"))
    assert egress.remove_gone("box", "box", ["old.example.com"], {}, set()) == (["old.example.com"], True)
    assert not [c for c in fakes.sbx.calls if c[:2] == ["policy", "rm"]]


def test_a_host_sbx_wouldnt_allow_isnt_left_on_the_record_as_allowed(web):
    setup, w, _ = web
    s = setup([{"hosts": ["api.example.com"]}])
    s.answer(["policy", "allow"], code=1)
    assert not egress.egress_sync("box", w) and egress_rec(web) == []


# ── og policy's parts ──

def test_the_sandboxes_policy_covers_each_with_its_workspace_never_a_header_odd_name_or_none():
    listing = "SANDBOX AGENT STATUS WORKSPACE\nfern claude running /w/fern\n.bad claude running /w/x\nloose claude stopped\n"
    assert policy.sandboxes(listing) == [("fern", "/w/fern")]


@pytest.mark.parametrize(("ok", "unlisted", "row"), [
    ([True, True], False, "2 sandboxes"), ([True, False], False, "1 failed"), ([], False, "no sandboxes"),
    ([], True, "not set")])
def test_push_rules_for_each_sandbox_and_the_row_that_says_how_it_went(monkeypatch, ok, unlisted, row):
    answers = iter(ok)
    monkeypatch.setattr(pushrules, "push_rules", lambda name, w, say: next(answers))
    (k, v), good = policy.pushes([(f"s{i}", "/w") for i in range(len(ok))], unlisted)
    assert k == "pushes" and row in v and good == all(ok)


@pytest.mark.parametrize(("ok", "unlisted", "row"), [
    ([True], False, "1 sandbox as listed"), ([False, True], False, "1 not as listed"), ([], False, "no sandboxes"),
    ([], True, "not set")])
def test_each_sandboxs_domains_synced_as_og_policy_and_the_row(monkeypatch, ok, unlisted, row):
    answers, seen = iter(ok), []
    monkeypatch.setattr(egress, "egress_sync", lambda name, w, say, cmd: seen.append((say, cmd)) or next(answers))
    (k, v), good = policy.domains([(f"s{i}", "/w") for i in range(len(ok))], unlisted)
    assert k == "domains" and row in v and good == all(ok) and all(x == (False, "policy") for x in seen)


def test_every_allow_covering_github_is_named_with_its_removal(capfd):
    added = [("all", "*.com"), ("sandbox:fern", "github.com"), ("all", "github.com"), ("all", "api.example.com")]
    assert policy.github_wide(added) == [("all", "*.com"), ("sandbox:fern", "github.com"), ("all", "github.com")]
    err = capfd.readouterr().err
    assert "*.com covers all of github.com for every sandbox, so any sandbox can push" in err
    assert "all of github.com is allowed for fern, so fern can push" in err and "og net fern github.com --rm" in err


def test_og_policy_leaves_sbxs_own_default_rules_to_the_baseline_never_naming_them(og, fakes):
    policy_sbx(fakes, rules=LS_HEAD + "\n" + rule("all", "**", via="default") + "\n")
    _, out, err = og("policy")
    assert "covers all of github.com" not in out + err


@pytest.fixture
def every_step(monkeypatch):
    """og policy with every step it runs answering as set (all fine unless a test
    says), one sandbox listed: its exit code."""
    from ogun.core import sbx
    said = {"baseline": True, "push": True, "sync": True}
    monkeypatch.setattr(baseline, "baseline", lambda: said["baseline"])
    monkeypatch.setattr(baseline, "ssh_agent_off", lambda: True)
    monkeypatch.setattr(sbx, "ls", lambda: "SANDBOX AGENT STATUS WORKSPACE\nfern claude running /w\n")
    monkeypatch.setattr(pushrules, "push_rules", lambda *a, **k: said["push"])
    monkeypatch.setattr(egress, "egress_sync", lambda *a, **k: said["sync"])
    monkeypatch.setattr(ruletable, "read_rules", lambda: [])
    return said


def test_og_policy_with_every_step_fine_exits_zero(home, every_step):
    assert policy.policy([]) == 0


@pytest.mark.parametrize("step", ["baseline", "push", "sync"])
def test_a_baseline_push_rule_or_domain_sync_that_fails_fails_og_policy(home, every_step, step):
    every_step[step] = False
    assert policy.policy([]) == 1
