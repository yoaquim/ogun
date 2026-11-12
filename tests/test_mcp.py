"""mcp: gateway MCP servers. A repo's own servers go to the repo its entry
describes, never to a folder that only shares its name. A gateway keeps the
credentials a server was loaded with, so a renewed login reaches a running
sandbox only through another `sbx mcp load`: og mcp auth reloads into the
running sandboxes that use the server; every attach logs in again what is not
"authorized" (at a terminal only) and reloads the sandbox's own servers. og mcp
ls reads sbx's JSON and the registry; auth refuses a server the registry does
not name. A registry may be shared by several Macs: a server scoped to the work profile, or
a repo checked out elsewhere, is another Mac's."""

import json
import os
import re
import sys

import pytest

from conftest import use_profile
from ogun import mcp


def test_the_placed_repo_gets_its_entrys_servers(world):
    assert "db-hidden" in mcp.servers(str(world / ".hidden-repo"), quiet=True)


def test_a_same_named_folder_elsewhere_doesnt(world):
    assert "db-hidden" not in mcp.servers(str(world / "tmp/.hidden-repo"), quiet=True)


# sbx's own view: db-fern logged in, db-cub expired, db-old registered
# but named by no repo, notes a header-secret server (no OAuth), localtool a local
# server no repo names
STATUS = [{"server_name": "db-fern", "status": "authorized"},
          {"server_name": "db-cub", "status": "needs-refresh"},
          {"server_name": "db-old", "status": "needs-refresh"}]
KNOWN = ("db-fern", "db-cub", "db-old", "notes", "localtool")
# the calls made only to read: every other call is something og did
READS = (["ls"], ["mcp", "auth", "status"], ["mcp", "ls"], ["policy", "inspect"])


@pytest.fixture
def gw(home, registry, fakes):
    """fern and cub running, idle stopped, all acme; notes for every sandbox. set_
    answers sbx: fail, the calls that fail; down, sbx's MCP reads failing;
    lsdown, its sandbox list."""
    use_profile(home, "home")   # a profiled Mac: no "no profile" note in what og says
    p = home / "Projects/acme"
    for d in ("fern", "cub", "idle"):
        (p / d).mkdir(parents=True)
    registry({"fern": {"owner": "acme", "mcp": ["db-fern"]},
              "idle": {"owner": "acme", "mcp": ["db-fern"]},
              "cub": {"owner": "acme", "mcp": ["db-cub", "bad name"]}}, mcp=["notes"])

    def set_(fail=(), down=False, lsdown=False, status=STATUS, known=KNOWN):
        s = fakes.sbx
        s.clear()
        for c in fail:
            s.answer(c.split(), code=1)
        s.answer(["ls"], code=1 if lsdown else 0, stdout="" if lsdown else
                 "SANDBOX  AGENT   STATUS   PORTS  WORKSPACE\n"
                 f"fern     claude  running  -      {p / 'fern'}\n"
                 f"cub      claude  running  -      {p / 'cub'}\n"
                 f"idle     claude  stopped  -      {p / 'idle'}\n")
        s.answer(["mcp", "auth", "status"], stdout=json.dumps(status), code=int(down))
        s.answer(["mcp", "ls"], code=int(down),
                 stdout="NAME  TYPE  URL/COMMAND\n" + "".join(f"{k} remote x\n" for k in known))
        # attach's default-rule check: none is back (test_session covers one that is)
        s.answer(["policy", "inspect"], code=1)
        return s

    set_()
    return set_


def acts(s) -> list[list[str]]:
    return [c for c in s.calls if not any(c[:len(r)] == r for r in READS)]


def row(out: str, pattern: str) -> bool:
    return any(re.fullmatch(pattern, line) for line in out.splitlines())


def changes_log(home) -> str:
    f = home / ".local/state/ogun/og.log"
    return f.read_text() if f.exists() else ""


# ── og mcp ls ──

def test_og_mcp_is_each_server_with_its_status_and_the_repos_that_get_it(og, gw):
    out = og("mcp")[1]
    assert row(out, "db-fern +authorized +fern,idle")
    assert row(out, "db-cub +needs-refresh +cub")
    assert row(out, "notes +registered +every sandbox")


def test_a_server_sbx_has_but_no_repo_names_is_listed_used_by_nobody(og, gw):
    assert row(og("mcp", "ls")[1], "db-old +needs-refresh +-")


def test_each_login_that_is_not_fine_says_how_to_log_in_again(og, gw):
    out = og("mcp")[1]
    assert "log in again: og mcp auth db-cub" in out and "og mcp auth db-fern" not in out


def test_so_is_a_registration_with_no_oauth_login_that_no_repo_names(og, gw):
    assert row(og("mcp", "ls")[1], "localtool +registered +-")


def test_for_a_server_no_repo_names_the_hint_is_sbx_mcp_auth(og, gw):
    out = og("mcp")[1]
    assert "log in again: sbx mcp auth db-old" in out and "og mcp auth db-old" not in out


def test_an_invalid_name_in_the_registry_never_reaches_the_listing(og, gw):
    out = og("mcp")[1]
    assert row(out, "db-cub .*") and "bad name" not in out


def test_og_mcp_ls_json_is_server_status_used_by(og, gw):
    got = {r["server"]: r for r in json.loads(og("mcp", "ls", "--json")[1])}
    assert got["db-fern"] == {"server": "db-fern", "status": "authorized", "used_by": ["fern", "idle"]}
    assert got["db-old"]["used_by"] == []


def test_a_server_neither_sbx_nor_anyone_registered_says_so(og, gw):
    gw(status=[], known=())
    code, out, _ = og("mcp")
    assert code == 0 and row(out, "db-fern +not-registered.*")
    assert "register once: sbx mcp add db-fern" in out


def test_sbx_failing_to_list_is_an_error_never_every_server_logged_out(og, gw):
    gw(down=True)
    code, out, err = og("mcp")
    assert code == 1 and "og mcp: sbx couldn't say which servers are logged in" in out + err
    assert "not-registered" not in out + err and "sbx mcp add" not in out + err


def test_og_mcp_ls_with_another_argument_is_a_usage_error(og, gw):
    code, _, err = og("mcp", "ls", "extra")
    assert code == 1 and "usage: og mcp" in err


# ── og mcp auth ──

def test_og_mcp_auth_logs_in_then_reloads_into_each_running_sandbox_using_it(og, gw):
    s = gw()
    og("mcp", "auth", "db-fern")
    assert acts(s) == [["mcp", "auth", "db-fern"], ["mcp", "load", "db-fern", "--sandbox", "fern"]]


def test_a_server_the_registry_does_not_name_is_refused_nothing_called(og, gw):
    s = gw()
    code, out, err = og("mcp", "auth", "db-old")
    assert code == 1
    assert "isn't in registry.json; to log in to it anyway, run:" in out + err and "sbx mcp auth db-old" in out + err
    assert acts(s) == []


def test_auth_all_is_every_oauth_registry_server_each_reloaded_where_it_runs(og, gw):
    s = gw()
    assert og("mcp", "auth", "--all")[0] == 0
    did = acts(s)
    for c in ("mcp auth db-cub", "mcp auth db-fern", "mcp load db-cub --sandbox cub",
              "mcp load db-fern --sandbox fern"):
        assert c.split() in did
    assert not [c for c in did if c in (["mcp", "auth", "notes"], ["mcp", "auth", "db-old"]) or "idle" in c]


def test_auth_for_a_server_without_oauth_is_refused_nothing_called(og, gw):
    s = gw()
    code, out, err = og("mcp", "auth", "notes")
    assert code == 1 and "no OAuth login" in out + err and acts(s) == []


def test_a_reload_that_fails_after_the_login_fails_the_command_naming_the_sandbox(og, gw):
    gw(fail=["mcp load db-fern --sandbox fern"])
    code, out, err = og("mcp", "auth", "db-fern")
    assert code == 1
    assert "couldn't load db-fern again into fern; to try again, run:" in out + err and "og mcp load fern" in out + err


def test_so_does_a_sandbox_list_that_fails_with_nothing_reloaded(og, gw):
    s = gw(lsdown=True)
    code, out, err = og("mcp", "auth", "db-fern")
    both = out + err
    assert code == 1 and re.search(r"✓ logged in to db-fern.*couldn't list its sandboxes.*og mcp load <name>", both, re.S)
    assert not [c for c in s.calls if c[:2] == ["mcp", "load"]]


def test_a_failed_login_reloads_nothing_and_fails_the_command(og, gw):
    s = gw(fail=["mcp auth db-fern"])
    assert og("mcp", "auth", "db-fern")[0] == 1
    assert ["mcp", "auth", "db-fern"] in s.calls and not [c for c in s.calls if c[:2] == ["mcp", "load"]]


def test_a_login_that_works_is_one_done_line_naming_where_it_was_reloaded_and_is_on_the_record(og, gw, home):
    _, out, err = og("mcp", "auth", "db-fern")
    assert (out + err).strip() == "✓ logged in to db-fern  reloaded into fern"
    assert "logged in to db-fern, reloaded into fern" in changes_log(home)


def test_one_no_running_sandbox_uses_says_so(og, gw, registry):
    registry({"idle": {"owner": "acme", "mcp": ["db-fern"]}})
    _, out, err = og("mcp", "auth", "db-fern")
    assert (out + err).strip() == "✓ logged in to db-fern  no running sandbox uses it"


def test_a_login_that_didnt_finish_is_ogs_error_the_retry_on_its_own_line_nothing_recorded(og, gw, home):
    gw(fail=["mcp auth db-fern"])
    _, out, err = og("mcp", "auth", "db-fern")
    assert (out + err).strip() == "og mcp: the login to db-fern didn't finish; to try again, run:\nog mcp auth db-fern"
    assert changes_log(home) == ""


def test_auth_all_heads_each_server_with_a_step(og, gw):
    _, out, err = og("mcp", "auth", "--all")
    assert re.search(r"→ db-cub: logging in \(browser\).*→ db-fern: logging in \(browser\)", out + err, re.S)


# ── og mcp load, and what every attach does ──

def test_og_mcp_load_reloads_that_sandboxs_servers_global_ones_too(og, gw):
    s = gw()
    og("mcp", "load", "fern")
    assert acts(s) == [["mcp", "load", "notes", "--sandbox", "fern"], ["mcp", "load", "db-fern", "--sandbox", "fern"]]


def test_a_login_that_is_not_authorized_without_a_terminal_is_told_not_opened(og, gw):
    s = gw()
    out = og("mcp", "load", "cub", stdin="")[1]
    assert "db-cub: needs-refresh — log in: og mcp auth db-cub" in out
    assert ["mcp", "auth", "db-cub"] not in s.calls and ["mcp", "load", "db-cub", "--sandbox", "cub"] in s.calls


def test_at_a_terminal_it_is_logged_in_again_before_the_reload(og, gw, monkeypatch):
    s = gw()
    _, tty = os.openpty()
    monkeypatch.setattr(sys, "stdin", os.fdopen(tty))
    og("mcp", "load", "cub")
    assert [c for c in acts(s) if "db-cub" in c] == [["mcp", "auth", "db-cub"],
                                                          ["mcp", "load", "db-cub", "--sandbox", "cub"]]


def test_a_load_that_fails_says_how_to_retry_and_fails_the_command(og, gw):
    gw(fail=["mcp load db-fern --sandbox fern"])
    code, out, _ = og("mcp", "load", "fern")
    assert code == 1 and "! couldn't load db-fern; to see why, run: og mcp" in out


def test_auth_all_when_sbx_cant_say_which_servers_log_in_is_an_error(og, gw):
    s = gw(down=True)
    code, out, err = og("mcp", "auth", "--all")
    assert code == 1 and "sbx couldn't say which servers have a login, so nothing was done" in out + err
    assert acts(s) == []


def test_load_when_login_status_cant_be_read_says_so_and_fails_but_the_reloads_still_run(og, gw):
    s = gw(down=True)
    code, out, _ = og("mcp", "load", "fern")
    assert code == 1 and "couldn't check the MCP logins" in out
    assert ["mcp", "load", "db-fern", "--sandbox", "fern"] in s.calls


def test_load_of_a_stopped_sandbox_is_refused_pointing_at_the_attach_that_starts_it(og, gw):
    s = gw()
    code, out, err = og("mcp", "load", "idle")
    assert code == 1 and re.search(r"isn't running.*og idle", out + err, re.S) and acts(s) == []


def test_load_of_an_unknown_sandbox_is_refused(og, gw):
    code, out, err = og("mcp", "load", "nope")
    assert code == 1 and "no sandbox 'nope'" in out + err


def test_og_attach_reloads_its_servers_before_the_session_starts(og, gw):
    s = gw()
    og("attach", "fern", stdin="")
    # around them, the upkeep runs inside the sandbox (test_session)
    assert [c for c in s.calls if c[:1] == ["run"] or c[:2] == ["mcp", "load"]] == [
        ["mcp", "load", "notes", "--sandbox", "fern"], ["mcp", "load", "db-fern", "--sandbox", "fern"],
        ["run", "--name", "fern", "claude"]]


def test_help_after_auth_all_or_load_is_its_usage_and_calls_nothing(og, gw, fakes):
    code, out, _ = og("mcp", "auth", "--all", "--help")
    assert code == 0 and out.startswith("usage: og mcp ") and "Examples:" in out
    code, out, _ = og("mcp", "load", "fern", "--help")
    assert code == 0 and out.startswith("usage: og mcp ")
    assert fakes.sbx.calls == []


@pytest.mark.parametrize("args", [["bogus"], ["load"]])
def test_an_unknown_subcommand_or_load_with_no_name_is_a_usage_error_that_calls_nothing(og, gw, fakes, args):
    code, _, err = og("mcp", *args)
    assert code == 1 and err.startswith("usage: og mcp ") and fakes.sbx.calls == []


def test_og_help_mcp_is_the_usage_line(og):
    assert "usage: og mcp [ls [--json] | auth <server> | auth --all | load <name>]" in og("help", "mcp")[1]


# ── a registry shared by several Macs ──

@pytest.fixture
def multi(home, registry):
    """A server for the work profile's sandboxes only, and a repo checked out on
    another Mac. on(machine): this Mac's og profile ("" for none)."""
    (home / "Projects/acme/fern").mkdir(parents=True)
    registry({"fern": {"owner": "acme", "mcp": ["db-fern"]}, "away": {"owner": "acme", "mcp": ["db-away"]}},
             mcp=["notes", {"name": "search", "profiles": ["work"]}])
    def on(machine: str) -> str:
        use_profile(home, machine or None)
        return str(home / "Projects/acme/fern")

    return on


def test_a_top_level_server_scoped_to_a_profile_reaches_every_sandbox_under_it(multi):
    assert mcp.servers(multi("work"), quiet=True) == ["notes", "search", "db-fern"]


@pytest.mark.parametrize("machine", ["home", ""])   # no profile: fails closed
def test_and_none_under_another_profile_nor_under_none(multi, machine):
    assert "search" not in mcp.servers(multi(machine), quiet=True)


def test_og_mcps_registry_is_this_macs_a_profiles_server_listed_a_repo_not_checked_out_here_left_out(multi):
    multi("work")
    assert mcp.registry() == {"search": ["every sandbox"], "db-fern": ["fern"], "notes": ["every sandbox"]}


def test_so_another_profile_doesnt_list_that_server(multi):
    multi("home")
    assert "search" not in mcp.registry()


def test_og_mcp_auth_takes_a_profiles_server_under_that_profile(og, multi, fakes):
    multi("work")
    fakes.sbx.answer(["mcp", "auth", "status"], stdout="[]")
    _, out, err = og("mcp", "auth", "search")
    assert "in registry.json" not in out + err and "no OAuth login sbx knows of" in out + err
