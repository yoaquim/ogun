"""grants: the 1Password values a sandbox is handed (registry.json `secrets`). A
top-level grant reaches every sandbox on the Macs its `profiles` name; a repo's
grant only that repo's sandboxes, behind the owner gate. Each grant is approved
once per Mac, at a real terminal, before any sandbox gets it; applied to the one
sandbox (its hosts allowed with --sandbox, its value registered through og pass);
recorded; and revoked when the registry stops granting it. GitHub hosts,
wildcards and malformed entries are refused; a variable granted two ways is
refused outright."""

import io
import os
import stat
import sys

import pytest

from conftest import use_profile
from ogun.core import paths, records, settings
from ogun.sandbox import facts
from ogun.secrets import approval, grants, secret

TOP = [{"env": "TYPE_KEY", "hosts": ["api.example.com"], "item": "api-x", "profiles": ["home"]},
       {"env": "WORK_KEY", "hosts": ["api.work.example"], "item": "c", "profiles": ["work"]}]

# a grant line: scope (owner/repo, or *@<machine> for a top-level one), env, hosts, item, field.
# An approval is for that exact line: a grant moved to another owner or Mac is a new one
ALL_TYPE = "*@home\tTYPE_KEY\tapi.example.com\tapi-x\tcredential"
ORDERS = "personal/orders\tORDERS_API_KEY\tapi.orders.example\torders-staging-key\tcredential"
ORDERS_SRC = "op://Sandbox/orders-staging-key/credential"

# sbx secret ls --sandbox sb1, as sbx prints it: SCOPE TARGETS ENV PLACEHOLDER SECRET
HEAD = "CUSTOM SECRETS\nSCOPE TARGETS ENV PLACEHOLDER SECRET\n"
HAVE1 = f"sb1 api.orders.example ORDERS_API_KEY sbx-cs-HAVE1 ref:{ORDERS_SRC} (on-demand)"
LS_HAVE = HEAD + HAVE1
LS_GLOBAL = HEAD + f"(global) api.orders.example ORDERS_API_KEY sbx-cs-GLOB1 ref:{ORDERS_SRC} (on-demand)"
LS_STALE = HEAD + "\n".join([
    "sb1 api.example.com TYPE_KEY sbx-cs-KEEP1 ref:op://Sandbox/api-x/credential (on-demand)",
    f"sb1 api.orders.example ORDERS_API_KEY sbx-cs-OLD1 ref:{ORDERS_SRC} (on-demand)",
    "sb1 api.orders.example ORDERS_API_KEY_2 sbx-cs-NEAR1 ref:op://Sandbox/orders-staging-key/credential2 (on-demand)",
    f"other api.orders.example ORDERS_API_KEY sbx-cs-OTHER ref:{ORDERS_SRC} (on-demand)"])
# the whole listing, service section first: TYPE_KEY's row left, ORDERS_API_KEY's gone
LS_GONE = ("SCOPE TYPE NAME SECRET\nsb1 service github (stored)\n(global) service anthropic (oauth)\n\n"
           "CUSTOM SECRETS\nSCOPE        TARGETS          ENV        PLACEHOLDER    SECRET\n"
           "sb1 api.example.com TYPE_KEY sbx-cs-KEEP1 ref:op://Sandbox/api-x/credential (on-demand)")


def _registry(orders_item="orders-staging-key", orders_owner="personal", top=None):
    return {
        "orders": {"owner": orders_owner, "secrets": [
            {"env": "ORDERS_API_KEY", "hosts": ["api.orders.example"], "item": orders_item, "field": "credential"}]},
        "loose": {"secrets": [{"env": "LOOSE", "hosts": ["l.example.com"], "item": "l"}]},
        "bad": {"owner": "personal", "secrets": [
            {"env": "G", "hosts": ["api.github.com"], "item": "g"},
            {"env": "U", "hosts": ["objects.githubusercontent.com"], "item": "u"},
            {"env": "W", "hosts": ["*.example.com"], "item": "w"},
            {"env": "X; rm -rf /", "hosts": ["x.example.com"], "item": "x"},
            {"env": "GH_TOKEN", "hosts": ["x.example.com"], "item": "x"},
            {"env": "NOHOST", "hosts": [], "item": "x"}]},
        "clash": {"owner": "personal", "secrets": [{"env": "TYPE_KEY", "hosts": ["api.example.com"], "item": "other"}]},
        "same": {"owner": "personal", "secrets": [
            {"env": "TYPE_KEY", "hosts": ["API.example.com"], "item": "api-x", "field": "credential"}]},
    }, {"secrets": TOP if top is None else top}


class World:
    def __init__(self, home, registry):
        self.home, self._registry = home, registry

    def dir(self, rel: str) -> str:
        return str(self.home / "Projects" / rel)

    def machine(self, m: str | None) -> None:
        """This Mac's og profile; None: none chosen."""
        use_profile(self.home, m)

    def registry(self, **changes) -> None:
        repos, top = _registry(**changes)
        self._registry(repos, **top)

    @property
    def approvals(self):
        return approval.approved_file()

    def approve(self, *lines: str) -> None:
        """Approved on this Mac already, from vault Sandbox."""
        self.approvals.parent.mkdir(parents=True, exist_ok=True)
        self.approvals.write_text("".join(f"{g}\tSandbox\n" for g in lines))


@pytest.fixture
def world(home, registry, monkeypatch):
    for d in ("personal/orders", "initech/orders", "personal/loose", "personal/bad", "personal/clash",
              "personal/same", "personal/plain", "personal/orders/sub/orders"):
        (home / "Projects" / d).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SBX_VAULT", "Sandbox")
    monkeypatch.delenv("SBX_SECRETS_APPROVED", raising=False)
    # not a terminal, and full of yes: no pipe, file or setting can approve a grant
    monkeypatch.setattr(sys, "stdin", io.StringIO("y\n" * 8))
    w = World(home, registry)
    w.registry()
    w.machine("home")
    return w


@pytest.fixture
def terminal(monkeypatch):
    """stdin a real pseudo-terminal that answers every question with `answer`:
    the approval is asked only at a terminal, and read from it."""
    opened = []

    def at(answer: str) -> None:
        m, s = os.openpty()
        os.write(m, ((answer + "\n") * 8).encode())
        f = os.fdopen(s, "r")
        opened.extend([m, f])
        monkeypatch.setattr(sys, "stdin", f)

    yield at
    for x in opened:
        x.close() if hasattr(x, "close") else os.close(x)


def stub(fakes, *, ls="", ls_fail=False, ls_global="", ls_global_fail=False, ls_first_empty=False, ls_after_set=None,
         set_fail=False, set_fail_for=None, allow_fail=False, exec_fail=False, rm_fail=False, rm_fail_ph=None):
    """sbx as it answers for sandbox sb1. ls: its own `secret ls --sandbox` listing;
    ls_global: plain `secret ls`, every scope's. ls_after_set: the listing once one
    read has gone by (a registration this call made shows up). set_fail_for: the
    set-custom arguments after --sandbox sb1 that fail."""
    s = fakes.sbx
    s.clear()
    mine = ["secret", "ls", "--sandbox", "sb1"]
    if ls_first_empty:
        s.answer(mine, code=1, once=True)
    if ls_after_set is not None:
        s.answer(mine, stdout=ls, once=True)
        s.answer(mine, stdout=ls_after_set)
    s.answer(mine, stdout=ls, code=1 if ls_fail else 0)
    s.answer(["secret", "ls"], stdout=ls_global, code=1 if ls_global_fail else 0)
    if set_fail_for:
        s.answer(["secret", "set-custom", "--sandbox", "sb1", *set_fail_for], stdout="ERROR: nope\n", code=1)
    s.answer(["secret", "set-custom"], stdout="ERROR: nope\n" if set_fail else "Generated placeholder: sbx-cs-TESTPH01\n",
             code=1 if set_fail else 0)
    s.answer(["policy", "allow"], code=1 if allow_fail else 0)
    s.answer(["exec", "sb1"], code=1 if exec_fail else 0)
    if rm_fail_ph:
        s.answer(["secret", "rm", "--sandbox", "sb1", "--placeholder", rm_fail_ph], code=1)
    s.answer(["secret", "rm"], code=1 if rm_fail else 0)
    s.answer(["ls"], stdout="NAME STATUS WORKSPACE\nsb1  running /x\n")
    return s


def ran(calls, script: str) -> list[list[str]]:
    """The (env, placeholder) each run of that env script (og's sandbox-scripts/env/) inside sb1 was given."""
    body = secret.env_script(script)
    return [c[-2:] for c in calls if c[:2] == ["exec", "sb1"] and len(c) > 4 and c[4] == body]


def set_customs(calls) -> list[list[str]]:
    return [c for c in calls if c[:2] == ["secret", "set-custom"]]


def rm_egress(host: str) -> list[str]:
    return ["policy", "rm", "network", "--sandbox", "sb1", "--resource", host]


def rm_ph(ph: str) -> list[str]:
    return ["secret", "rm", "--sandbox", "sb1", "--placeholder", ph, "-f"]


def in_order(text: str, *parts: str) -> bool:
    at = 0
    for p in parts:
        at = text.find(p, at)
        if at < 0:
            return False
        at += len(p)
    return True


def recorded(world, egress: str = "", ws: str = "personal/orders", *applied: str) -> None:
    """sb1's create record, as create writes it, with these grants applied since."""
    assert facts.record("sb1", "session", world.dir(ws), None, "name: sb1\n", egress.split(","))
    if applied:
        assert grants.facts("sb1", list(applied))


def rec_envs() -> list[str]:
    return [s["env"] for s in records.read_record("sb1")["secrets"]]


def rec_source(env: str) -> list[str]:
    return [s["source"] for s in records.read_record("sb1")["secrets"] if s["env"] == env]


# ── which grants a sandbox gets ──

def test_the_repos_own_grant_and_this_macs_top_level_grants_a_line_each(world):
    assert approval.grants(world.dir("personal/orders")) == [ALL_TYPE, ORDERS]


def test_a_top_level_grant_reaches_only_the_profiles_it_names(world):
    world.machine("work")
    got = "\n".join(approval.grants(world.dir("personal/orders")))
    assert "WORK_KEY" in got and "ORDERS_API_KEY" in got and "TYPE_KEY" not in got


def test_no_profile_no_top_level_grant_the_repos_own_still_applies(world):
    world.machine(None)
    assert approval.grants(world.dir("personal/orders")) == [ORDERS]


def test_a_repo_without_an_entry_gets_only_the_top_level_grants(world):
    assert approval.grants(world.dir("personal/plain")) == [ALL_TYPE]


# ── the owner gate, as for template and mcp ──

def test_a_same_named_repo_of_another_owner_gets_nothing(world, capfd):
    got = approval.grants(world.dir("initech/orders"))
    assert not any("ORDERS_API_KEY" in g for g in got)
    assert "for owner 'personal', but this sandbox's owner is 'initech'" in capfd.readouterr().err


def test_an_entry_with_no_declared_owner_grants_nothing(world, capfd):
    assert not any("LOOSE" in g for g in approval.grants(world.dir("personal/loose")))
    assert "declares no `owner`" in capfd.readouterr().err


def test_a_subfolder_named_like_the_repo_is_not_the_repo(world, capfd):
    assert not any("ORDERS_API_KEY" in g for g in approval.grants(world.dir("personal/orders/sub/orders")))
    assert "not the repo it describes" in capfd.readouterr().err


# ── refusals ──

def test_github_hosts_wildcards_malformed_names_gits_own_env_and_hostless_grants_are_refused(world, capfd):
    world.machine(None)
    assert approval.grants(world.dir("personal/bad")) == []
    err = capfd.readouterr().err
    assert err.count("GitHub host") == 2
    assert "'*.example.com' is not an exact host" in err
    assert "malformed" in err and "GH_TOKEN" in err and "names no host" in err


def test_one_variable_granted_two_ways_is_refused_outright(world, capfd):
    assert not any("TYPE_KEY" in g for g in approval.grants(world.dir("personal/clash")))
    assert "TYPE_KEY is granted twice, differently" in capfd.readouterr().err


def test_the_same_grant_twice_hosts_in_any_case_is_applied_once(world):
    assert approval.grants(world.dir("personal/same")) == [ALL_TYPE]


def test_a_registry_that_doesnt_parse_grants_nothing_and_says_so(world, capfd):
    paths.registry_file().write_text("{")
    assert approval.grants(world.dir("personal/orders")) == []
    assert "doesn't parse" in capfd.readouterr().err


# ── approval, once per Mac ──

def _asked(err: str) -> bool:
    return "grant it to this sandbox" in err


def test_an_unapproved_grant_with_no_terminal_is_skipped_named_and_not_recorded(world, capfd):
    assert approval.approved(world.dir("personal/orders")) == []
    err = capfd.readouterr().err
    assert "not approved on this Mac" in err and "ORDERS_API_KEY" in err
    assert not world.approvals.exists() or world.approvals.read_text() == ""


def test_approved_at_the_terminal_applied_and_recorded_for_this_mac_owner_only(world, terminal):
    terminal("y")
    assert approval.approved(world.dir("personal/orders")) == [ALL_TYPE, ORDERS]
    assert world.approvals.read_text() == f"{ALL_TYPE}\tSandbox\n{ORDERS}\tSandbox\n"
    assert stat.S_IMODE(world.approvals.stat().st_mode) == 0o600


def test_the_prompt_names_the_scope_the_variable_its_hosts_and_its_1password_source(world, terminal, capfd):
    terminal("y")
    approval.approved(world.dir("personal/orders"))
    err = capfd.readouterr().err
    assert _asked(err)
    assert in_order(err, "EVERY SANDBOX on this Mac (top-level grant, profile home)", "TYPE_KEY")
    assert in_order(err, "repo 'personal/orders'", "ORDERS_API_KEY", "op://Sandbox/orders-staging-key/credential")


def test_once_approved_the_next_create_applies_it_without_asking(world, terminal, capfd):
    terminal("y")
    approval.approved(world.dir("personal/orders"))
    capfd.readouterr()
    assert approval.approved(world.dir("personal/orders")) == [ALL_TYPE, ORDERS]
    assert not _asked(capfd.readouterr().err)


def test_a_grant_whose_source_changed_is_new_asked_again_not_applied_on_the_old_approval(world, capfd):
    world.approve(ALL_TYPE, ORDERS)
    world.registry(orders_item="orders-staging-key-2")
    assert approval.approved(world.dir("personal/orders")) == [ALL_TYPE]
    assert "orders-staging-key-2" in capfd.readouterr().err


def test_an_approval_is_for_its_owner_the_grant_moved_to_another_owner_is_asked_again(world, capfd):
    world.approve(ALL_TYPE, ORDERS)
    world.registry(orders_owner="initech")
    assert not any("ORDERS_API_KEY" in g for g in approval.approved(world.dir("initech/orders")))
    assert in_order(capfd.readouterr().err, "initech/orders", "not approved on this Mac")


def test_a_top_level_approval_is_for_its_profile_a_changed_profile_asks_again(world, capfd):
    top = [dict(TOP[0], profiles=["home", "work"]), TOP[1]]
    world.registry(top=top)
    world.approve(ALL_TYPE)
    world.machine("work")
    assert not any("TYPE_KEY" in g for g in approval.approved(world.dir("personal/plain")))
    assert in_order(capfd.readouterr().err, "profile work", "TYPE_KEY")


def test_an_approval_is_for_its_vault_the_same_item_in_another_vault_is_asked_again(world, terminal, capfd, monkeypatch):
    terminal("y")
    approval.approved(world.dir("personal/orders"))
    assert world.approvals.read_text().splitlines()[1].endswith("\tSandbox")
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setenv("SBX_VAULT", "Other")
    capfd.readouterr()
    assert approval.approved(world.dir("personal/orders")) == []
    assert "op://Other/orders-staging-key/credential" in capfd.readouterr().err


def test_declined_at_the_terminal_not_applied_and_remembered_as_declined(world, terminal, capfd):
    terminal("n")
    assert approval.approved(world.dir("personal/orders")) == []
    assert "declined" in capfd.readouterr().err
    assert world.approvals.read_text() == f"{ALL_TYPE}\tSandbox\tdeclined\n{ORDERS}\tSandbox\tdeclined\n"


def test_a_decline_stands_the_next_create_doesnt_ask_again(world, terminal, capfd):
    terminal("n")
    approval.approved(world.dir("personal/orders"))
    capfd.readouterr()
    terminal("y")
    assert approval.approved(world.dir("personal/orders")) == []
    err = capfd.readouterr().err
    assert "declined earlier" in err and not _asked(err)


def test_a_declined_grant_that_changed_is_a_new_one_and_is_asked_about(world, terminal, capfd):
    terminal("n")
    approval.approved(world.dir("personal/orders"))
    capfd.readouterr()
    world.registry(orders_item="orders-staging-key-3")
    terminal("y")
    got = approval.approved(world.dir("personal/orders"))
    err = capfd.readouterr().err
    assert any("orders-staging-key-3" in g for g in got)
    assert "orders-staging-key-3" in err and _asked(err)


# ── applying to one sandbox ──

def test_a_grant_opens_its_hosts_for_this_sandbox_and_registers_its_value_by_reference(world, fakes):
    s = stub(fakes)
    assert grants.apply("sb1", [ORDERS]) == ([ORDERS], True)
    assert ["policy", "allow", "network", "--sandbox", "sb1", "api.orders.example"] in s.calls
    assert ["secret", "set-custom", "--sandbox", "sb1", "--host", "api.orders.example", "--env", "ORDERS_API_KEY",
            "--ref", ORDERS_SRC] in s.calls


def test_never_globally_every_allow_and_registration_names_the_sandbox(world, fakes):
    s = stub(fakes)
    grants.apply("sb1", [ALL_TYPE, ORDERS])
    allows = [c for c in s.calls if c[:3] == ["policy", "allow", "network"]]
    assert allows and set_customs(s.calls)
    assert all(c[3:5] == ["--sandbox", "sb1"] for c in allows)
    assert all(c[2:4] == ["--sandbox", "sb1"] for c in set_customs(s.calls))


def test_a_grant_that_cant_be_registered_fails_and_prints_the_og_pass_to_run(world, fakes, capfd):
    stub(fakes, set_fail=True)
    assert grants.apply("sb1", [ORDERS]) == ([], False)
    assert "og pass sb1 ORDERS_API_KEY api.orders.example --item orders-staging-key" in capfd.readouterr().err


def test_apply_returns_exactly_the_grants_applied_and_talks_only_on_stderr(world, fakes, capfd):
    stub(fakes)
    assert grants.apply("sb1", [ALL_TYPE, ORDERS]) == ([ALL_TYPE, ORDERS], True)
    assert capfd.readouterr().out == ""


def test_registered_but_its_placeholder_not_written_into_the_sandbox_is_not_applied(world, fakes):
    stub(fakes, exec_fail=True)
    assert grants.apply("sb1", [ORDERS]) == ([], False)


def test_a_grant_that_failed_takes_back_the_egress_it_opened(world, fakes):
    recorded(world)
    s = stub(fakes, set_fail=True)
    assert not grants.apply("sb1", [ORDERS])[1]
    assert rm_egress("api.orders.example") in s.calls


def test_unless_the_sandbox_needs_that_host_anyway_its_templates_runtime_egress(world, fakes):
    recorded(world, egress="api.orders.example")
    s = stub(fakes, set_fail=True)
    assert not grants.apply("sb1", [ORDERS])[1]
    assert not [c for c in s.calls if c[:2] == ["policy", "rm"]]


def test_or_an_earlier_grant_in_the_same_batch_applied_not_yet_recorded_uses_it(world, fakes):
    recorded(world)
    s = stub(fakes, set_fail_for=["--host", "api.orders.example", "--env", "ORDERS_API_KEY_2"])
    second = "personal/orders\tORDERS_API_KEY_2\tapi.orders.example\tother\tcredential"
    assert grants.apply("sb1", [ORDERS, second]) == ([ORDERS], False)
    assert not [c for c in s.calls if c[:2] == ["policy", "rm"]]


def test_a_grant_the_sandbox_already_holds_exactly_is_adopted_never_registered_again(world, fakes, capfd):
    s = stub(fakes, ls=LS_HAVE)
    assert grants.apply("sb1", [ORDERS]) == ([ORDERS], True)
    assert not set_customs(s.calls)
    assert ran(s.calls, "export.sh") == [["ORDERS_API_KEY", "sbx-cs-HAVE1"]]
    assert "already registered" in capfd.readouterr().err


def test_one_from_another_source_sandbox_or_variable_isnt_adopted(world, fakes):
    s = stub(fakes, ls=HEAD + "\n".join([
        "sb1 api.orders.example ORDERS_API_KEY sbx-cs-HAVE2 ref:op://Sandbox/other-item/credential (on-demand)",
        f"other api.orders.example ORDERS_API_KEY sbx-cs-HAVE3 ref:{ORDERS_SRC} (on-demand)",
        f"sb1 api.orders.example OTHER_TOKEN sbx-cs-HAVE5 ref:{ORDERS_SRC} (on-demand)"]))
    assert grants.apply("sb1", [ORDERS]) == ([ORDERS], True)
    assert set_customs(s.calls)
    assert not any(p in " ".join(c) for c in s.calls for p in ("HAVE2", "HAVE3", "HAVE5"))


def test_two_matching_rows_are_never_picked_between(world, fakes, capfd):
    s = stub(fakes, ls=LS_HAVE + f"\nsb1 api.orders.example ORDERS_API_KEY sbx-cs-HAVE4 ref:{ORDERS_SRC} (on-demand)")
    assert grants.apply("sb1", [ORDERS]) == ([], False)
    assert not set_customs(s.calls)
    assert "more than once" in capfd.readouterr().err


def test_nor_is_one_from_a_listing_sbx_failed_to_finish(world, fakes):
    s = stub(fakes, ls=LS_HAVE, ls_fail=True, ls_global="CUSTOM SECRETS")
    grants.apply("sb1", [ORDERS])
    assert ran(s.calls, "export.sh") != [["ORDERS_API_KEY", "sbx-cs-HAVE1"]]
    assert set_customs(s.calls)


def test_a_variable_also_registered_for_every_sandbox_isnt_granted_with_how_to_remove_it(world, fakes, capfd):
    s = stub(fakes, ls_global=LS_GLOBAL)
    assert grants.apply("sb1", [ORDERS]) == ([], False)
    assert not set_customs(s.calls) and not [c for c in s.calls if c[:2] == ["policy", "allow"]]
    err = capfd.readouterr().err
    assert "registered for every sandbox (sbx-cs-GLOB1)" in err
    assert "sbx secret rm --placeholder <it> -f" in err


def test_nor_adopted_even_when_the_sandbox_holds_its_own_matching_one(world, fakes):
    s = stub(fakes, ls_global=LS_GLOBAL, ls=LS_HAVE)
    assert not grants.apply("sb1", [ORDERS])[1]
    assert ran(s.calls, "export.sh") == []


def test_a_global_row_for_another_variable_or_a_service_row_changes_nothing(world, fakes):
    stub(fakes, ls_global="(global) api.example.com OTHER_KEY sbx-cs-GLOB2 ref:op://Sandbox/x/credential (on-demand)\n"
                          "(global) service github (stored)")
    assert grants.apply("sb1", [ORDERS]) == ([ORDERS], True)


def test_when_sbxs_registrations_cant_be_read_no_grant_is_applied_at_all(world, fakes, capfd):
    s = stub(fakes, ls_global=LS_GLOBAL, ls_global_fail=True)
    assert grants.apply("sb1", [ORDERS]) == ([], False)
    assert not set_customs(s.calls) and not [c for c in s.calls if c[:2] == ["policy", "allow"]]
    assert "could not read sbx's registered secrets" in capfd.readouterr().err


def test_on_attach_too_a_listing_sbx_failed_to_finish_adopts_nothing(world, fakes):
    recorded(world)
    # every scope's listing reads fine: only the sandbox's own fails
    s = stub(fakes, ls=LS_HAVE, ls_fail=True)
    grants.give("sb1", [ORDERS])
    assert set_customs(s.calls)
    assert ["ORDERS_API_KEY", "sbx-cs-HAVE1"] not in ran(s.calls, "export.sh")


def test_an_adopted_grant_whose_env_cant_be_written_isnt_applied_nor_its_registration_removed(world, fakes):
    s = stub(fakes, ls=LS_HAVE, exec_fail=True)
    assert grants.apply("sb1", [ORDERS]) == ([], False)
    assert not [c for c in s.calls if c[:2] == ["secret", "rm"]]


def test_no_grants_no_sbx_call_at_all(world, fakes):
    s = stub(fakes)
    assert grants.apply("sb1", []) == ([], True)
    assert s.calls == []


# ── giving: applied only where it can be recorded, taken back if recording fails ──

def test_a_sandbox_with_no_create_record_gets_no_grant(world, fakes, capfd):
    s = stub(fakes)
    assert not grants.give("sb1", [ORDERS])
    assert not set_customs(s.calls)
    assert "no create record" in capfd.readouterr().err


def test_with_a_record_the_grant_is_applied_and_recorded(world, fakes):
    recorded(world)
    stub(fakes)
    assert grants.give("sb1", [ORDERS])
    assert rec_envs() == ["ORDERS_API_KEY"]


@pytest.fixture
def unrecordable_record(world):
    recorded(world)
    d = records.records_dir()
    d.chmod(0o500)
    yield
    d.chmod(0o700)


def test_a_grant_that_cant_be_recorded_is_taken_back_at_once(world, fakes, capfd, unrecordable_record):
    # the registration shows in sbx's listing only once this call has made it
    s = stub(fakes, ls_after_set=f"sb1 api.orders.example ORDERS_API_KEY sbx-cs-TESTPH01 ref:{ORDERS_SRC} (on-demand)")
    assert not grants.give("sb1", [ORDERS])
    assert rm_ph("sbx-cs-TESTPH01") in s.calls
    assert rm_egress("api.orders.example") in s.calls
    assert "taking it back" in capfd.readouterr().err


def test_one_adopted_keeps_its_registration_only_what_adopting_added_goes(world, fakes, capfd, unrecordable_record):
    s = stub(fakes, ls=LS_HAVE)
    assert not grants.give("sb1", [ORDERS])
    assert not [c for c in s.calls if c[:2] == ["secret", "rm"]]
    assert ran(s.calls, "export.sh") == [["ORDERS_API_KEY", "sbx-cs-HAVE1"]]
    assert ran(s.calls, "unexport.sh") == [["ORDERS_API_KEY", "sbx-cs-HAVE1"]]
    assert rm_egress("api.orders.example") in s.calls
    assert "kept, but not exported" in capfd.readouterr().err


def test_adoption_and_take_back_decide_from_one_listing(world, fakes, unrecordable_record):
    # sbx answers only on the second read, and refuses the duplicate, as it does for real
    s = stub(fakes, ls=LS_HAVE, ls_first_empty=True, set_fail=True)
    assert not grants.give("sb1", [ORDERS])
    assert not [c for c in s.calls if c[:2] == ["secret", "rm"]]


# ── the create record ──

def test_the_record_starts_with_no_grants_and_gains_only_those_applied(world):
    recorded(world)
    assert records.read_record("sb1")["secrets"] == []
    assert grants.facts("sb1", [ORDERS])
    r = records.read_record("sb1")
    assert r["secrets"] == [{"scope": "personal/orders", "env": "ORDERS_API_KEY", "hosts": ["api.orders.example"],
                             "source": ORDERS_SRC}]
    assert r["sandbox"] == "sb1" and r["mounts"] == []


def test_more_grants_add_to_the_list_one_for_the_same_scope_and_variable_replaces_its_entry(world):
    recorded(world, "", "personal/orders", ORDERS)
    assert grants.facts("sb1", [ALL_TYPE])
    assert rec_envs() == ["ORDERS_API_KEY", "TYPE_KEY"]
    assert grants.facts("sb1", ["personal/orders\tORDERS_API_KEY\tapi.orders.example\torders-staging-key-2\tcredential"])
    assert [f"{s['env']}={s['source']}" for s in records.read_record("sb1")["secrets"]] == [
        "ORDERS_API_KEY=op://Sandbox/orders-staging-key-2/credential", "TYPE_KEY=op://Sandbox/api-x/credential"]


# ── catching up on attach: a create that stopped early, or a grant declared since ──

def test_an_attach_applies_only_the_approved_grants_its_record_doesnt_show_and_records_them(world, fakes):
    world.approve(ALL_TYPE, ORDERS)
    recorded(world, "", "personal/orders", ALL_TYPE)
    s = stub(fakes)
    grants.catch_up("sb1", world.dir("personal/orders"))
    assert set_customs(s.calls) == [["secret", "set-custom", "--sandbox", "sb1", "--host", "api.orders.example",
                                     "--env", "ORDERS_API_KEY", "--ref", ORDERS_SRC]]
    assert rec_envs() == ["TYPE_KEY", "ORDERS_API_KEY"]


def test_so_the_next_attach_registers_nothing_twice(world, fakes):
    world.approve(ALL_TYPE, ORDERS)
    recorded(world, "", "personal/orders", ALL_TYPE)
    s = stub(fakes)
    grants.catch_up("sb1", world.dir("personal/orders"))
    n = len(s.calls)
    grants.catch_up("sb1", world.dir("personal/orders"))
    assert not set_customs(s.calls[n:])


def test_an_attach_finding_the_grant_already_registered_records_it_and_registers_nothing(world, fakes):
    world.approve(ALL_TYPE, ORDERS)
    recorded(world, "", "personal/orders", ALL_TYPE)
    s = stub(fakes, ls=LS_HAVE)
    grants.catch_up("sb1", world.dir("personal/orders"))
    assert not set_customs(s.calls)
    assert rec_envs() == ["TYPE_KEY", "ORDERS_API_KEY"]


def test_a_sandbox_with_no_create_record_is_left_alone_says_so_and_asks_nothing(world, fakes, terminal, capfd):
    s = stub(fakes)
    terminal("y")
    grants.catch_up("sb1", world.dir("personal/orders"))
    err = capfd.readouterr().err
    assert not set_customs(s.calls)
    assert "no create record" in err and not _asked(err)
    assert not world.approvals.exists()


# ── revoking: a grant the registry no longer gives this sandbox ──

def _stale(world, fakes, **knobs):
    """sb1 made for personal/plain with TYPE_KEY and ORDERS_API_KEY recorded: plain is
    granted only TYPE_KEY, so attaching revokes ORDERS_API_KEY."""
    world.approve(ALL_TYPE, ORDERS)
    recorded(world, knobs.pop("egress", ""), "personal/plain", ALL_TYPE, ORDERS, *knobs.pop("more", ()))
    s = stub(fakes, **knobs)
    grants.catch_up("sb1", world.dir("personal/plain"))
    return s


def test_a_grant_no_longer_given_is_revoked_on_attach_its_own_row_only_and_leaves_the_record(world, fakes, capfd):
    s = _stale(world, fakes, ls=LS_STALE)
    assert [c for c in s.calls if c[:2] == ["secret", "rm"]] == [rm_ph("sbx-cs-OLD1")]
    assert rec_envs() == ["TYPE_KEY"]
    assert in_order(capfd.readouterr().err, "ORDERS_API_KEY", "no longer granted", "revoked")


def test_so_are_its_export_of_that_exact_placeholder_and_its_egress_only_that_host(world, fakes):
    s = _stale(world, fakes, ls=LS_STALE)
    assert ran(s.calls, "unexport.sh") == [["ORDERS_API_KEY", "sbx-cs-OLD1"]]
    assert rm_egress("api.orders.example") in s.calls
    assert rm_egress("api.example.com") not in s.calls


def test_the_egress_removal_is_said_with_how_to_put_it_back(world, fakes, capfd):
    _stale(world, fakes, ls=LS_STALE)
    assert in_order(capfd.readouterr().err, "removed sb1's egress to api.orders.example", "og allow sb1 api.orders.example")


def test_a_host_a_kept_grant_or_the_templates_runtime_egress_needs_keeps_its_egress(world, fakes):
    s = _stale(world, fakes, egress="api.orders.example",
               more=["personal/orders\tOLD_API\tapi.example.com\told\tcredential"],
               ls=LS_STALE + "\nsb1 api.example.com OLD_API sbx-cs-OLDAPI ref:op://Sandbox/old/credential (on-demand)")
    assert rm_ph("sbx-cs-OLDAPI") in s.calls
    assert not [c for c in s.calls if c[:2] == ["policy", "rm"]]


def test_one_that_cant_be_removed_stays_on_the_record_and_prints_the_command(world, fakes, capfd):
    _stale(world, fakes, ls=LS_STALE, rm_fail=True)
    assert rec_envs() == ["TYPE_KEY", "ORDERS_API_KEY"]
    assert "sbx secret rm --sandbox sb1 --placeholder sbx-cs-OLD1" in capfd.readouterr().err


def test_one_whose_placeholder_cant_be_found_is_never_guessed_at(world, fakes, capfd):
    s = _stale(world, fakes, ls="")
    assert not [c for c in s.calls if c[:2] == ["secret", "rm"]]
    assert rec_envs() == ["TYPE_KEY", "ORDERS_API_KEY"]
    assert "sbx secret ls --sandbox sb1" in capfd.readouterr().err


def test_one_a_full_listing_shows_already_gone_leaves_the_record_and_its_egress_goes(world, fakes, capfd):
    s = _stale(world, fakes, ls=LS_GONE)
    assert not [c for c in s.calls if c[:2] == ["secret", "rm"]]
    assert rec_envs() == ["TYPE_KEY"]
    assert rm_egress("api.orders.example") in s.calls
    assert in_order(capfd.readouterr().err, "ORDERS_API_KEY", "already gone")


def test_as_does_one_with_only_the_service_section_no_custom_secret_at_all(world, fakes):
    _stale(world, fakes, ls="SCOPE TYPE NAME SECRET\nsb1 service github (stored)")
    assert rec_envs() == ["TYPE_KEY"]


@pytest.mark.parametrize("knobs", [
    # the rows, but without the header this layout is known by
    {"ls": "sb1 api.example.com TYPE_KEY sbx-cs-KEEP1 ref:op://Sandbox/api-x/credential (on-demand)"},
    # a listing sbx failed to give
    {"ls": LS_GONE, "ls_fail": True},
    # the header, but a row of this sandbox in some other shape
    {"ls": LS_GONE + f"\nsb1 api.orders.example ORDERS_API_KEY {ORDERS_SRC}"},
], ids=["no header", "sbx failed", "an unreadable row"])
def test_a_listing_that_cant_say_what_is_gone_never_says_a_placeholder_is(world, fakes, knobs):
    _stale(world, fakes, **knobs)
    assert rec_envs() == ["TYPE_KEY", "ORDERS_API_KEY"]


MULTI = "personal/orders\tMULTI\ta.example.com,b.example.com\tm\tcredential"


def test_a_multi_host_registration_is_found_and_revoked_too(world, fakes):
    world.approve(ALL_TYPE)
    recorded(world, "", "personal/plain", ALL_TYPE, MULTI)
    s = stub(fakes, ls="sb1 a.example.com, b.example.com MULTI sbx-cs-M1 ref:op://Sandbox/m/credential (on-demand)")
    grants.catch_up("sb1", world.dir("personal/plain"))
    assert rm_ph("sbx-cs-M1") in s.calls


def test_only_the_registration_to_exactly_the_recorded_hosts_is_revoked(world, fakes):
    world.approve(ALL_TYPE)
    recorded(world, "", "personal/plain", ALL_TYPE, MULTI)
    s = stub(fakes, ls="\n".join([
        "sb1 a.example.com, b.example.com MULTI sbx-cs-M1 ref:op://Sandbox/m/credential (on-demand)",
        "sb1 a.example.com, c.example.com MULTI sbx-cs-M2 ref:op://Sandbox/m/credential (on-demand)",
        "sb1 a.example.com MULTI sbx-cs-M3 ref:op://Sandbox/m/credential (on-demand)"]))
    grants.catch_up("sb1", world.dir("personal/plain"))
    assert rm_ph("sbx-cs-M1") in s.calls
    assert not any("sbx-cs-M2" in c or "sbx-cs-M3" in c for c in s.calls)


def test_each_placeholder_removed_has_its_export_cleared_now_though_another_failed(world, fakes):
    s = _stale(world, fakes, ls=LS_STALE + f"\nsb1 api.orders.example ORDERS_API_KEY sbx-cs-OLD2 ref:{ORDERS_SRC} (on-demand)",
               rm_fail_ph="sbx-cs-OLD2")
    assert ran(s.calls, "unexport.sh") == [["ORDERS_API_KEY", "sbx-cs-OLD1"]]
    assert rec_envs() == ["TYPE_KEY", "ORDERS_API_KEY"]


ORDERS2 = "personal/orders\tORDERS_API_KEY\tapi.orders.example\torders-staging-key-2\tcredential"


def test_a_grant_changed_in_place_waits_for_its_old_one_to_be_revoked(world, fakes, capfd):
    world.registry(orders_item="orders-staging-key-2")
    world.approve(ALL_TYPE, ORDERS2)
    recorded(world, "", "personal/orders", ALL_TYPE, ORDERS)
    stub(fakes, ls=LS_STALE, rm_fail=True)
    grants.catch_up("sb1", world.dir("personal/orders"))
    assert rec_source("ORDERS_API_KEY") == [ORDERS_SRC]
    assert in_order(capfd.readouterr().err, "ORDERS_API_KEY", "still live")
    # once the old one goes, the next attach gives the new one
    s = stub(fakes, ls=LS_STALE)
    n = len(s.calls)
    grants.catch_up("sb1", world.dir("personal/orders"))
    assert rm_ph("sbx-cs-OLD1") in s.calls[n:]
    assert [c[-1] for c in set_customs(s.calls[n:]) if "ORDERS_API_KEY" in c] == ["op://Sandbox/orders-staging-key-2/credential"]
    assert rec_source("ORDERS_API_KEY") == ["op://Sandbox/orders-staging-key-2/credential"]


def test_when_its_old_placeholder_is_already_gone_the_new_one_is_given_at_once(world, fakes):
    world.registry(orders_item="orders-staging-key-2")
    world.approve(ALL_TYPE, ORDERS2)
    recorded(world, "", "personal/orders", ALL_TYPE, ORDERS)
    s = stub(fakes, ls=LS_GONE)
    grants.catch_up("sb1", world.dir("personal/orders"))
    assert [c[-1] for c in set_customs(s.calls) if "ORDERS_API_KEY" in c] == ["op://Sandbox/orders-staging-key-2/credential"]
    assert rec_source("ORDERS_API_KEY") == ["op://Sandbox/orders-staging-key-2/credential"]


def test_a_registry_that_doesnt_parse_stops_og_and_revokes_nothing(world, fakes):
    world.approve(ALL_TYPE, ORDERS)
    recorded(world, "", "personal/plain", ALL_TYPE, ORDERS)
    paths.registry_file().write_text("{")
    s = stub(fakes, ls=LS_STALE)
    with pytest.raises(settings.Unreadable):
        grants.catch_up("sb1", world.dir("personal/orders"))
    assert not [c for c in s.calls if c[:2] == ["secret", "rm"]]
    assert rec_envs() == ["TYPE_KEY", "ORDERS_API_KEY"]


# ── where create and attach call them ──

# ── one grant, on its own ──

def test_one_grant_its_hosts_opened_and_its_value_registered_is_applied(world, fakes):
    s = stub(fakes)
    assert grants.apply_one("sb1", ORDERS, "", "", "Sandbox", []) is True
    assert ["policy", "allow", "network", "--sandbox", "sb1", "api.orders.example"] in s.calls and set_customs(s.calls)


def test_one_grant_with_no_variable_is_nothing_to_apply(world, fakes):
    s = stub(fakes)
    assert grants.apply_one("sb1", "personal/orders", "", "", "Sandbox", []) is None and s.calls == []


def test_one_grant_on_top_of_a_global_registration_fails_before_any_host_is_opened(world, fakes):
    s = stub(fakes)
    assert grants.apply_one("sb1", ORDERS, LS_GLOBAL, "", "Sandbox", []) is False
    assert not [c for c in s.calls if c[:2] == ["policy", "allow"]]


def test_one_grant_whose_hosts_sbx_wont_open_fails_with_the_og_allow_to_run(world, fakes, capfd):
    fakes.sbx.answer(["policy", "allow"], code=1)
    assert grants.apply_one("sb1", ORDERS, "", "", "Sandbox", []) is False
    assert "og allow sb1 api.orders.example" in capfd.readouterr().err


def test_one_grant_the_sandbox_holds_exactly_is_adopted(world, fakes):
    s = stub(fakes, ls=LS_HAVE)
    assert grants.apply_one("sb1", ORDERS, "", LS_HAVE, "Sandbox", []) is True and not set_customs(s.calls)


def test_one_grant_that_fails_takes_its_egress_back_unless_one_applied_keeps_it(world, fakes):
    recorded(world)
    s = stub(fakes, set_fail=True)
    assert grants.apply_one("sb1", ORDERS, "", "", "Sandbox", []) is False
    assert rm_egress("api.orders.example") in s.calls
    s = stub(fakes, set_fail=True)
    n = len(s.calls)
    assert grants.apply_one("sb1", ORDERS, "", "", "Sandbox", ["api.orders.example"]) is False
    assert not [c for c in s.calls[n:] if c[:2] == ["policy", "rm"]]


def test_one_grant_held_twice_fails_and_takes_its_egress_back(world, fakes, capfd):
    recorded(world)
    two = LS_HAVE + f"\nsb1 api.orders.example ORDERS_API_KEY sbx-cs-HAVE4 ref:{ORDERS_SRC} (on-demand)"
    s = stub(fakes, ls=two)
    assert grants.apply_one("sb1", ORDERS, "", two, "Sandbox", []) is False
    assert rm_egress("api.orders.example") in s.calls and "more than once" in capfd.readouterr().err
