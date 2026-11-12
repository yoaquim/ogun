"""health: og ports and og doctor, against sbx's --json in the shape sbx 0.49.1
gives. A sandbox's ports listed, published on loopback only,
unpublished by its sandbox port; sbx diagnose's checks and og's own (ssh-agent
forwarding, the baseline, sbx's default rules), only read."""

import json
import re

import pytest

from ogun.core import paths
from ogun.net import baseline
from ogun.sandbox import health

ONE = [{"host_ip": "127.0.0.1", "host_port": 49153, "sandbox_port": 9418, "protocol": "tcp4"}]
TWO = [{"host_ip": "127.0.0.1", "host_port": 49170, "sandbox_port": 3000, "protocol": "tcp4"},
       {"host_ip": "127.0.0.1", "host_port": 52012, "sandbox_port": 3000, "protocol": "udp4"}]


@pytest.fixture
def ports(fakes, home):
    """sbx listing cub, with these mappings published; a publish adds 3000 at 49170."""
    def set_(published=ONE, ls_fail=False, pub_fail=False, unpub_fail_port=None):
        s = fakes.sbx
        s.clear()
        s.answer(["ls"], stdout="SANDBOX  AGENT   STATUS\ncub      claude  running\n", code=1 if ls_fail else 0)
        s.answer(["ports", "cub", "--json"], stdout=json.dumps(published))
        s.answer(["ports", "cub", "--publish"], stderr="error: port in use\n" if pub_fail else "", code=1 if pub_fail else 0)
        if unpub_fail_port:
            s.answer(["ports", "cub", "--unpublish"], stderr="error: busy\n", code=1, has=str(unpub_fail_port))
        return s
    return set_


def changed(s) -> list[list[str]]:
    return [c for c in s.calls if c[:1] == ["ports"] and c[2] in ("--publish", "--unpublish")]


def test_og_ports_lists_whats_published_this_macs_address_the_sandboxs_port_the_protocol(og, ports):
    ports()
    code, out, _ = og("ports", "cub")
    assert code == 0 and re.search(r"(?m)^127.0.0.1:49153 +9418 +tcp4$", out) and "to publish one: og ports cub <port>" in out


def test_og_ports_name_port_publishes_it_and_says_where_on_this_mac_it_landed(og, ports):
    s = ports()
    s.clear()   # read before the publish: what was there; after it, the new one too
    s.answer(["ls"], stdout="SANDBOX  AGENT   STATUS\ncub      claude  running\n")
    s.answer(["ports", "cub", "--json"], stdout=json.dumps(ONE), once=True)
    s.answer(["ports", "cub", "--json"], stdout=json.dumps([*ONE, TWO[0]]))
    code, out, err = og("ports", "cub", "3000")
    assert code == 0 and ["ports", "cub", "--publish", "3000"] in s.calls
    assert re.search(r"✓ cub:3000 is at 127.0.0.1:49170.*only this Mac reaches it", out + err, re.S)


def test_rm_unpublishes_each_mapping_of_that_sandbox_port_as_sbx_names_it(og, ports):
    s = ports(published=[TWO[0]])
    code, out, err = og("ports", "cub", "--rm", "3000")
    assert code == 0 and changed(s) == [["ports", "cub", "--unpublish", "127.0.0.1:49170:3000/tcp4"]]
    assert "✓ unpublished cub:3000/tcp4 (was 127.0.0.1:49170)" in out + err


def test_a_protocol_named_removes_only_its_mappings(og, ports):
    s = ports(published=TWO)
    code, out, err = og("ports", "cub", "--rm", "3000/udp")
    assert code == 0 and changed(s) == [["ports", "cub", "--unpublish", "127.0.0.1:52012:3000/udp4"]]
    assert "unpublished cub:3000/udp4 (was 127.0.0.1:52012)" in out + err


def test_an_ipv6_mapping_is_unpublished_with_its_address_bracketed(og, ports):
    s = ports(published=[{"host_ip": "::1", "host_port": 52013, "sandbox_port": 3000, "protocol": "tcp6"}])
    og("ports", "cub", "--rm", "3000")
    assert changed(s) == [["ports", "cub", "--unpublish", "[::1]:52013:3000/tcp6"]]


def test_sbx_refusing_the_second_of_two_the_first_is_said_as_gone_and_on_the_record(og, ports):
    ports(published=TWO, unpub_fail_port=52012)
    code, out, err = og("ports", "cub", "--rm", "3000")
    assert code == 1
    assert re.search(r"couldn't unpublish.*already unpublished: cub:3000/tcp4 \(was 127.0.0.1:49170\)", out + err, re.S)
    assert "unpublished cub:3000/tcp4" in (paths.state_dir() / "og.log").read_text()


def test_one_not_published_has_nothing_to_remove_and_nothing_runs(og, ports):
    s = ports()
    code, out, err = og("ports", "cub", "--rm", "8080")
    assert code == 0 and "isn't published" in out + err and changed(s) == []


def test_an_address_of_this_mac_is_refused_og_publishes_on_loopback_only(og, ports):
    s = ports()
    code, out, err = og("ports", "cub", "0.0.0.0:8080:3000")
    assert code != 0 and "names an address; og publishes on 127.0.0.1 only" in out + err and changed(s) == []


@pytest.mark.parametrize("args", [["cub", "abc"], ["cub", "--rm"], [], ["ghost", "3000"]],
                         ids=["not a port", "--rm alone", "no name", "a missing sandbox"])
def test_refused_with_nothing_run(og, ports, args):
    s = ports()
    assert og("ports", *args)[0] != 0 and changed(s) == []


def test_a_list_sbx_couldnt_give_is_said(og, ports):
    ports(ls_fail=True)
    code, out, err = og("ports", "cub")
    assert code == 1 and "couldn't list" in out + err


def test_ports_sbx_couldnt_list_are_said_and_nothing_is_published(og, ports):
    s = ports()
    s.clear()
    s.answer(["ls"], stdout="SANDBOX  AGENT   STATUS\ncub      claude  running\n")
    s.answer(["ports", "cub", "--json"], code=1)
    code, out, err = og("ports", "cub", "3000")
    assert code == 1 and "og ports: sbx couldn't list cub's ports" in out + err and changed(s) == []


def test_sbx_refusing_a_publish_is_said_under_ogs_error(og, ports):
    ports(pub_fail=True)
    code, out, err = og("ports", "cub", "3000")
    assert code == 1 and re.search(r"couldn't publish.*port in use", out + err, re.S)


# ── og ports' parts: the specs, the listing, unpublishing, publishing ──

@pytest.mark.parametrize(("specs", "rm"), [(["3000"], False), (["8080:3000", "53/udp"], False), (["3000/tcp4"], True)])
def test_a_port_or_a_mac_port_to_a_sandbox_port_passes(home, capfd, specs, rm):
    assert health.spec_refused(specs, rm) is False and capfd.readouterr() == ("", "")


@pytest.mark.parametrize(("specs", "rm", "says"), [
    (["abc"], False, "usage: og ports"), (["3000", "70000x"], False, "usage: og ports"),   # off a terminal, the line alone
    (["8080:3000"], True, "usage: og ports"),
    (["0.0.0.0:80:3000"], False, "names an address"), (["192.168.1.2:3000"], False, "names an address"),
])
def test_one_spec_out_of_shape_or_naming_an_address_refuses_them_all(home, capfd, specs, rm, says):
    assert health.spec_refused(specs, rm) is True and says in "".join(capfd.readouterr())


def test_the_listing_is_each_mapping_where_on_this_mac_its_port_its_protocol(home, capfd):
    health.listing("cub", TWO)
    out = "".join(capfd.readouterr())
    assert re.search(r"(?m)^127.0.0.1:52012 +3000 +udp4$", out) and "og ports cub <port>" in out


def test_unpublishing_takes_each_mapping_of_the_port_one_not_there_is_said(ports, capfd):
    s = ports(published=TWO)
    assert health.unpublish("cub", ["3000/udp", "9999"], TWO) == 0
    assert changed(s) == [["ports", "cub", "--unpublish", "127.0.0.1:52012:3000/udp4"]]
    assert "port 9999 isn't published" in "".join(capfd.readouterr())


def test_unpublishing_stops_at_the_one_sbx_refuses_saying_whats_gone(ports, capfd):
    s = ports(published=TWO, unpub_fail_port="52012")
    assert health.unpublish("cub", ["3000"], TWO) == 1 and len(changed(s)) == 2
    assert "already unpublished: cub:3000/tcp4 (was 127.0.0.1:49170)" in "".join(capfd.readouterr())


def test_publishing_says_where_each_new_mapping_landed_or_sbxs_refusal(ports, capfd):
    s = ports(published=[*ONE, TWO[0]])
    assert health.publish("cub", ["3000"], ONE) == 0 and ["ports", "cub", "--publish", "3000"] in s.calls
    assert "cub:3000 is at 127.0.0.1:49170" in "".join(capfd.readouterr())
    ports(pub_fail=True)
    assert health.publish("cub", ["3000"], ONE) == 1 and "couldn't publish cub's 3000" in "".join(capfd.readouterr())


# ── og doctor ──

DIAG = {"version": "1.0", "checks": [
    {"name": "CLI binary", "status": "pass", "message": "found", "detail": "/opt/homebrew/Caskroom/sbx/0.49.1/Sbx.app/Contents/MacOS/sbx", "hint": ""},
    {"name": "Binary version", "status": "warn", "message": "update available: v0.50.1 (running v0.49.1)",
     "detail": "https://github.com/docker/sbx-releases/releases/tag/v0.50.1", "hint": "Download the latest release from the link above"},
    {"name": "Daemon", "status": "pass", "message": "healthy", "detail": "version v0.49.1", "hint": ""},
    {"name": "ZFS offset sync", "status": "skip", "message": "state directory is not on ZFS", "detail": "", "hint": ""},
    {"name": "Authentication", "status": "pass", "message": "authenticated", "detail": "", "hint": ""}],
    "summary": {"pass": 3, "warn": 1, "fail": 0, "skip": 1}}


def baseline_rules(drop=lambda line: False) -> str:
    """The baseline as og policy sets it: a network rule a host, an http rule a read-only one."""
    b = baseline.baseline_lists()
    rows = ["SOURCE   CREATED VIA   APPLIES TO   POLICY   POLICY_ID   RULE   RULE_ID   TYPE   METHOD   PATH   DECISION   PROTOCOLS   RESOURCES"]
    rows += [f"local  added  all  -  p1  -  id-{h}  network  -  -  allow  tcp  {h}" for h in b["SBX_BASELINE_DOMAINS"].split(",") if h]
    for r in b["SBX_BASELINE_HTTP"].split():
        h, _, rest = r.partition("=")
        m, _, path = rest.partition("=")
        rows.append(f"local  added  all  -  p1  -  id-{h}  http  {m}  {path or '/**'}  allow  -  {h}")
    return "\n".join(x for x in rows if not drop(x)) + "\n"


@pytest.fixture
def doctor(fakes, home, og):
    def run(diag=DIAG, agent="false\n", agent_fail=False, back=(), drop=lambda line: False):
        s = fakes.sbx
        s.clear()
        s.answer(["diagnose"], stdout=diag if isinstance(diag, str) else json.dumps(diag))
        s.answer(["settings", "get"], stdout=agent, code=1 if agent_fail else 0)
        for r in back:
            s.answer(["policy", "inspect", r])
        s.answer(["policy", "inspect"], code=1)
        s.answer(["policy", "ls"], stdout=baseline_rules(drop))
        code, out, err = og("doctor")
        writes = [c for c in s.calls if c[:2] == ["settings", "set"] or c[:2] in (["policy", "allow"], ["policy", "rm"])]
        return code, out + err, writes
    return run


def test_doctor_all_well_sbxs_checks_an_update_with_brews_command_then_ogs_exit_0_nothing_changed(doctor):
    code, out, writes = doctor()
    assert code == 0 and writes == []
    assert "Daemon: healthy" in out and re.search(r"Binary version: update available: v0.50.1.*brew upgrade --cask sbx", out, re.S)
    assert "ZFS" not in out
    for want in ("ssh-agent forwarding: off", "baseline: in place", "default rules: off", "everything checks out"):
        assert want in out


def test_forwarding_on_a_baseline_host_gone_a_default_rule_back_each_warned_with_og_policy_exit_1(doctor):
    code, out, writes = doctor(agent="true\n", back=["default-ai-services"], drop=lambda x: x.endswith(" deb.debian.org"))
    assert code == 1 and writes == []
    for want in ("ssh-agent forwarding is on", "missing deb.debian.org", "default-ai-services", "og policy", "needs a look"):
        assert want in out


def test_a_setting_sbx_couldnt_read_is_said_as_that_never_as_on(doctor):
    code, out, _ = doctor(agent_fail=True)
    assert code == 1 and "couldn't read sbx's ssh-agent setting" in out and "forwarding is on" not in out


def test_one_of_a_hosts_two_http_rules_gone_is_missing_by_its_method_and_path(doctor):
    code, out, _ = doctor(drop=lambda x: "POST  /*/*/git-upload-pack" in x)
    assert code == 1 and "missing github.com POST /*/*/git-upload-pack" in out and "missing github.com GET" not in out


def test_a_failed_sbx_check_fails_it_an_answer_og_cant_read_fails_it_too(doctor):
    failed = json.loads(json.dumps(DIAG))
    failed["checks"][2].update(status="fail", message="not running")
    code, out, _ = doctor(diag=failed)
    assert code == 1 and "og doctor: Daemon failed: not running" in out and "✗" not in out
    assert doctor(diag="nope")[0] == 1


# ── og doctor's parts: sbx's checks, then og's ──

@pytest.fixture
def checks(fakes, home):
    def set_(diag=DIAG, agent="false\n", agent_fail=False, back=(), drop=lambda line: False, ls_fail=False):
        s = fakes.sbx
        s.clear()
        s.answer(["diagnose"], stdout=diag if isinstance(diag, str) else json.dumps(diag))
        s.answer(["settings", "get"], stdout=agent, code=1 if agent_fail else 0)
        for r in back:
            s.answer(["policy", "inspect", r])
        s.answer(["policy", "inspect"], code=1)
        s.answer(["policy", "ls"], stdout=baseline_rules(drop), code=1 if ls_fail else 0)
    return set_


def test_sbxs_checks_fail_only_on_a_failed_one_or_an_answer_og_cant_read(checks, capfd):
    checks()
    assert health.sbx_failed() is False and "brew upgrade --cask sbx" in "".join(capfd.readouterr())
    failed = json.loads(json.dumps(DIAG))
    failed["checks"][2].update(status="fail", message="not running")
    checks(diag=failed)
    assert health.sbx_failed() is True and "Daemon failed: not running" in "".join(capfd.readouterr())
    checks(diag="nope")
    assert health.sbx_failed() is True and "gave no answer og can read" in "".join(capfd.readouterr())


@pytest.mark.parametrize(("kw", "says"), [
    ({}, "baseline: in place"),
    ({"agent": "true\n"}, "ssh-agent forwarding is on"),
    ({"agent_fail": True}, "couldn't read sbx's ssh-agent setting"),
    ({"drop": lambda x: x.endswith(" deb.debian.org")}, "missing deb.debian.org"),
    ({"ls_fail": True}, "couldn't read sbx's rules, so the baseline is unknown"),
    ({"back": ["default-ai-services"]}, "default rules are back: default-ai-services"),
], ids=["all well", "forwarding on", "forwarding unread", "baseline host gone", "rules unread", "a default rule back"])
def test_ogs_checks_fail_on_each_setting_out_of_place_or_unread(checks, capfd, kw, says):
    checks(**kw)
    assert health.og_failed() is bool(kw) and says in "".join(capfd.readouterr())


def test_a_failed_sbx_check_still_shows_ogs_own(doctor):
    failed = json.loads(json.dumps(DIAG))
    failed["checks"][2].update(status="fail", message="not running")
    code, out, _ = doctor(diag=failed, agent="true\n")
    assert code == 1 and "Daemon failed" in out and "ssh-agent forwarding is on" in out and "baseline: in place" in out
