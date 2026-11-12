"""og ls: sbx's table as og shows it, and --json, the same list for a machine: a
fixed shape, no placeholders, no colour, and a list that can't be read fails
rather than printing []. og sh: a shell or one command inside a sandbox, its argv
passed as is and its exit code kept. og stop: every name checked before any is
stopped."""

import json

import pytest

from ogun.sandbox import sandboxes

TABLE = "SANDBOX      AGENT    STATUS\nfern         claude   running\nsettings              stopped\n"


@pytest.fixture
def sbx_ls(fakes):
    """sbx ls lists one sandbox with an agent and one without: the empty AGENT
    cell is what the column reader exists for."""
    fakes.sbx.answer(["ls"], stdout=TABLE)
    return fakes.sbx


def test_ls_json_is_one_object_per_sandbox(og, sbx_ls):
    code, out, _ = og("ls", "--json")
    assert code == 0
    assert json.loads(out) == [{"sandbox": "fern", "agent": "claude", "status": "running"},
                               {"sandbox": "settings", "agent": "", "status": "stopped"}]


def test_an_empty_cell_is_empty_in_json_and_a_dash_in_the_table(og, sbx_ls):
    assert json.loads(og("ls", "--json")[1])[1]["agent"] == ""
    assert any(line.split()[:2] == ["settings", "-"] for line in og("ls")[1].splitlines())


def test_the_plain_table_is_aligned_words_without_marks_or_colour(og, sbx_ls):
    code, out, _ = og("ls")
    lines = out.splitlines()
    assert code == 0
    assert lines[0].startswith("SANDBOX")
    assert lines[1].split()[2] == "running"
    assert "\033" not in out and "▸" not in out and "○" not in out


def test_any_other_argument_is_sbx_ls_itself_its_words_untouched(og, sbx_ls):
    code, out, _ = og("ls", "--all")
    assert code == 0
    assert "settings              stopped" in out.splitlines()
    assert sbx_ls.calls[-1] == ["ls", "--all"]


def test_json_has_no_colour_or_clock(og, sbx_ls):
    out = og("ls", "--json")[1]
    assert "\033" not in out
    assert len(json.loads(out)) == 2


def test_ls_json_with_other_sbx_arguments_is_refused_saying_why(og, sbx_ls):
    code, out, err = og("ls", "--json", "--some-filter")
    assert code == 1
    assert out == ""
    assert "takes no other sbx ls arguments" in err


def test_plain_ls_fails_with_sbxs_own_exit_code(og, fakes):
    fakes.sbx.answer(["ls"], code=7)
    assert og("ls")[0] == 7


def test_ls_json_fails_when_the_list_cant_be_read_and_never_prints_an_empty_list(og, fakes):
    fakes.sbx.answer(["ls"], code=7)
    code, out, err = og("ls", "--json")
    assert code == 1
    assert out == ""
    assert "og ls: sbx couldn't list its sandboxes" in err


def test_a_name_header_still_answers_under_sandbox(og, fakes):
    fakes.sbx.answer(["ls"], stdout="NAME     STATUS\nfern     running\n")
    assert json.loads(og("ls", "--json")[1]) == [{"sandbox": "fern", "agent": "", "status": "running"}]


# ── reading sbx's table: each cell is the slice under its header ──

def test_an_empty_cell_mid_row_stays_empty_and_columns_past_status_arent_ours():
    table = "SANDBOX  AGENT   STATUS   PORTS     WORKSPACE\ncub               running  8080/tcp  /w/cub,\n"
    assert sandboxes.as_json(table) == [{"sandbox": "cub", "agent": "", "status": "running"}]


def test_a_status_a_newer_sbx_marks_is_the_bare_word():
    table = "SANDBOX  AGENT   STATUS\ncub      claude  ● running\nfern     claude  ○ stopped\n"
    assert [r["status"] for r in sandboxes.as_json(table)] == ["running", "stopped"]


def test_a_table_without_two_of_ogs_columns_is_no_sandboxes():
    assert sandboxes.as_json("WHATEVER\nx\n") == []


# ── OpenAPPA: the sandboxes it protects, marked ──

def test_og_ls_marks_openappa_sandboxes_in_a_plugins_column_and_has_none_when_none_is(og, fakes, home):
    from ogun.core import records
    fakes.sbx.answer(["ls"], stdout="SANDBOX  AGENT   STATUS   WORKSPACE\nbox      claude  running  /work/box\n"
                                    "plain    claude  stopped  /work/plain\n")
    d = records.records_dir()
    d.mkdir(parents=True)
    (d / "box.json").write_text('{"sandbox": "box", "appa": {"version": "v0.37.0"}}')
    (d / "plain.json").write_text('{"sandbox": "plain"}')
    code, out, _ = og("ls")
    lines = out.splitlines()
    assert code == 0 and lines[0].split() == ["SANDBOX", "AGENT", "STATUS", "PLUGINS"]
    assert next(x for x in lines if x.startswith("box")).split()[-1] == "OpenAPPA"
    assert "OpenAPPA" not in next(x for x in lines if x.startswith("plain"))
    (d / "box.json").unlink()
    code, out, _ = og("ls")
    assert code == 0 and "plain" in out and "OpenAPPA" not in out and "PLUGINS" not in out


def test_plain_ls_that_sbx_cant_give_is_ogs_error_then_sbxs_words_as_a_note(og, fakes):
    fakes.sbx.answer(["ls"], stderr="error: the daemon isn't running\n", code=1)
    code, out, err = og("ls")
    assert code != 0
    assert out + err == "og ls: sbx couldn't list its sandboxes:\n  · error: the daemon isn't running\n"


# ── og sh and og stop ──

@pytest.fixture
def up(fakes):
    """sbx listing run1 running and stop1 stopped, as a newer sbx marks them
    (starting: up1 on its way too); each part of it failing as asked."""
    def set_(starting=False, ls_fail=False, exec_rc=0, stop_fail=False):
        s = fakes.sbx
        s.clear()
        rows = "SANDBOX   AGENT    STATUS      WORKSPACE\nrun1      claude   ● running   /w\nstop1     claude   ○ stopped   /w\n"
        s.answer(["ls"], stdout=rows + ("up1       claude   starting    /w\n" if starting else ""),
                 stderr="error: the daemon isn't running\n" if ls_fail else "", code=int(ls_fail))
        s.answer(["exec"], code=exec_rc)
        s.answer(["stop"], stderr="error: busy\n" if stop_fail else "", code=int(stop_fail))
        return s

    set_()
    return set_


def ran(s, verb: str) -> list[list[str]]:
    return [c for c in s.calls if c[:1] == [verb]]


def test_og_sh_name_opens_a_login_shell(og, up):
    s = up()
    og("sh", "run1")
    assert ran(s, "exec") == [["exec", "-it", "run1", "bash", "-l"]]


def test_og_sh_name_command_runs_it_with_its_argv_as_is_help_and_all_no_terminal_when_piped(og, up):
    s = up()
    og("sh", "run1", "grep", "-r", "a b", "--help")
    assert ran(s, "exec") == [["exec", "-i", "run1", "bash", "-lc", 'exec "$@"', "_", "grep", "-r", "a b", "--help"]]


def test_a_dash_dash_before_the_command_is_dropped(og, up):
    s = up()
    og("sh", "run1", "--", "ls", "-la")
    assert ran(s, "exec") == [["exec", "-i", "run1", "bash", "-lc", 'exec "$@"', "_", "ls", "-la"]]


def test_og_sh_exits_with_the_commands_code(og, up):
    up(exec_rc=7)
    assert og("sh", "run1", "false")[0] == 7


def test_og_sh_help_is_its_help_never_a_shell(og, up):
    s = up()
    code, out, _ = og("sh", "--help")
    assert code == 0 and "usage: og sh" in out and s.calls == []


def test_og_sh_to_a_sandbox_that_isnt_there_says_so_and_runs_nothing(og, up):
    s = up()
    code, _, err = og("sh", "ghost", "ls")
    assert code != 0 and "no sandbox 'ghost'" in err and "og ls" in err.split("no sandbox 'ghost'")[1]
    assert ran(s, "exec") == []


def test_og_sh_when_sbx_cant_list_says_that_never_no_such_sandbox(og, up):
    s = up(ls_fail=True)
    code, out, err = og("sh", "run1", "ls")
    assert code != 0 and "sbx couldn't list its sandboxes" in out + err and "no sandbox" not in out + err
    assert ran(s, "exec") == []


def test_og_sh_with_no_name_is_a_usage_error(og, up):
    s = up()
    assert og("sh")[0] == 1 and s.calls == []


def test_og_stop_name_stops_it_with_one_done_line(og, up):
    s = up()
    code, out, err = og("stop", "run1")
    assert code == 0 and ran(s, "stop") == [["stop", "run1"]] and "✓ stopped run1" in out + err


def test_one_already_stopped_is_said_not_stopped_again(og, up):
    s = up()
    code, out, err = og("stop", "stop1")
    assert code == 0 and "stop1 is already stopped" in out + err and ran(s, "stop") == []


def test_a_name_that_isnt_a_sandbox_stops_none_of_them(og, up):
    s = up()
    code, out, err = og("stop", "run1", "ghost")
    assert code != 0 and "no sandbox 'ghost'" in out + err and ran(s, "stop") == []


def test_og_stop_all_stops_every_running_sandbox(og, up):
    s = up()
    assert og("stop", "--all")[0] == 0 and ran(s, "stop") == [["stop", "run1"]]


def test_anything_but_stopped_is_up_a_sandbox_starting_among_them_and_is_stopped(og, up):
    s = up(starting=True)
    assert og("stop", "--all")[0] == 0 and ran(s, "stop") == [["stop", "run1", "up1"]]
    assert og("stop", "up1")[0] == 0 and ran(s, "stop")[1:] == [["stop", "up1"]]


def test_sbxs_failure_to_stop_is_said_under_ogs_error(og, up):
    up(stop_fail=True)
    code, out, err = og("stop", "run1")
    assert code != 0 and "couldn't stop run1:" in out + err and "error: busy" in (out + err).split("couldn't stop run1:")[1]
    assert "✓" not in out + err


def test_a_list_sbx_couldnt_give_stops_nothing(og, up):
    s = up(ls_fail=True)
    assert og("stop", "run1")[0] != 0 and ran(s, "stop") == []


@pytest.mark.parametrize("args", [[], ["run1", "--bogus"], ["--all", "run1"]])
def test_no_name_an_unknown_option_or_all_with_names_is_usage_and_stops_nothing(og, up, args):
    s = up()
    assert og("stop", *args)[0] == 1 and s.calls == []
