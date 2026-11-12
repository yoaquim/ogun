"""help: one command table, read by the help page, every --help and every usage
error. Help answers on stdout with exit 0 (asking is not an error); a usage
error answers on stderr with exit 1. --help after a command is that command's
usage and never runs the command (a real sandbox action from a help request
would be the bad failure here). The table and the commands og runs agree, so no
command is listed without being runnable or runnable without being
listed. Extra arguments are refused, never dropped: a dropped one could be the
sandbox you meant. And the sandbox-name rules every command holds a
name to: one shape, one reserved list."""

import json
import re
from pathlib import Path

import pytest

from ogun import cli, help
from ogun.core import naming
from ogun.exchange import screen, take
from ogun.net import allow
from ogun.sandbox import remove

CMDS = list(help.COMMANDS)


# ── the page and the table ──

def test_og_help_lists_the_groups_and_the_flags_on_stdout(og):
    code, out, _ = og("help")
    lines = out.splitlines()
    headings = [t for t in lines if t[:1].isalpha() and " " not in t]   # a section's title, alone on its line
    assert code == 0 and headings == [g for g, _ in help.GROUPS]
    assert "--no-attach" in out and "docs/README.md" in out


def test_help_and_h_are_the_same_page(og):
    page = og("help")[1]
    assert og("--help")[1] == page and og("-h")[1] == page


def test_the_table_holds_every_command_help_and_ssh_among_them():
    assert len(CMDS) >= 20 and "help" in CMDS and "ssh" in CMDS


def test_every_table_command_appears_in_the_list(og):
    out = og("help")[1]
    for c in CMDS:
        assert re.search(rf"^  {re.escape(c)} +", out, re.M), c


def test_every_table_command_is_one_og_runs_and_every_one_og_runs_is_in_the_table():
    assert sorted(cli._RAW_CMDS) == sorted(CMDS)


# ── a command's own usage ──

def test_cmd_help_prints_that_commands_usage_on_stdout(og):
    code, out, _ = og("take", "--help")
    assert code == 0 and re.search(r"^usage: og take <name> ", out, re.M) and "out/" in out


@pytest.mark.parametrize("cmd", [c for c in CMDS if c != "help"])   # og help -h is the page itself
def test_h_is_the_usage_for_every_command_in_the_table(og, cmd):
    code, out, _ = og(cmd, "-h")
    assert code == 0 and re.search(rf"^usage: og {cmd}", out, re.M)


def test_og_tidy_and_og_scan_answer_help_with_ogs_own_usage(og):
    t, s = og("tidy", "--help")[1], og("scan", "--help")[1]
    assert t.splitlines()[0] == "usage: og tidy [--rm]"
    assert re.search(r"Find what removed sandboxes left behind.*stored secrets", t, re.S)
    assert s.splitlines()[0] == "usage: og scan" and "og take and every attach run it too" in s
    code, _, err = og("scan", "extra")
    assert code == 1 and err.strip() == "usage: og scan"


def test_og_help_h_is_the_page_itself_not_a_lookup_of_h(og):
    assert re.search(r"^og — one sandboxed", og("help", "-h")[1], re.M)


# THE property: a help request never acts on a sandbox

def test_a_help_request_never_runs_the_command_it_asks_about(og, fakes):
    for c in CMDS:
        og(c, "--help")
    assert fakes.sbx.calls == []


@pytest.mark.parametrize("args", [
    "attach demo --help", "sh --help", "stop demo --help", "tidy --rm --help",   # og tidy --rm --help removing a box
    "rm demo --force --help", "take demo --all -h", "give demo file.txt --help", "allow example.com --help",
])
def test_help_after_a_commands_own_arguments_still_only_prints_usage(og, fakes, args):
    a = args.split()
    code, out, err = og(*a)
    assert code == 0 and re.search(rf"^usage: og {a[0]}", out + err, re.M)
    assert fakes.sbx.calls == []


@pytest.mark.parametrize("cmd", ["doctor", "policy", "ls", "project", "style"])
def test_every_command_a_person_types_draws_ogs_own_help_with_examples_and_runs_nothing(og, fakes, cmd):
    code, out, err = og(cmd, "--help")
    assert code == 0 and (out + err).startswith(f"usage: og {cmd}") and "Examples:" in out + err
    assert fakes.sbx.calls == []


# ── usage errors: stderr, exit 1 ──

def test_a_missing_argument_is_a_usage_line_on_stderr_nothing_on_stdout_and_fails(og, fakes):
    code, out, err = og("attach")
    assert code == 1 and out == "" and "usage: og attach <name>" in err.splitlines()


def test_an_unknown_option_reaching_the_create_path_fails_naming_help_on_stderr(og, fakes):
    code, _, err = og("--badflag")
    assert code == 1
    lines = err.splitlines()
    i = next(i for i, x in enumerate(lines) if "unknown option --badflag" in x)
    assert "og help" in "\n".join(lines[i:i + 2])


def test_og_help_of_an_unknown_command_fails_saying_so_on_stderr(og):
    code, _, err = og("help", "nosuchcommand")
    assert code == 1 and "no such command" in err


# a command og doesn't have is no command at all, and a flag it doesn't have is refused
# before sbx is asked anything

@pytest.mark.parametrize("cmd", ["nope", "bogus"])
def test_a_command_og_has_not_is_no_such_command(og, cmd):
    assert "no such command" in og("help", cmd)[2]


def test_a_flag_og_has_not_is_refused_before_sbx_is_asked_anything(og, fakes):
    code, out, err = og("demo", "--bogus")
    assert code != 0 and "unknown option --bogus" in out + err and fakes.sbx.calls == []


@pytest.mark.parametrize("args", ["rm a b", "rm a b --force", "ssh a b"])
def test_extra_arguments_are_a_usage_error_that_reaches_nothing(og, fakes, args):
    a = args.split()
    code, _, err = og(*a)
    assert code == 1 and re.search(rf"^usage: og {a[0]} ", err, re.M)
    assert fakes.sbx.calls == []


def test_og_give_with_nothing_to_give_prints_the_tables_usage(og):
    assert og("give")[2].strip() == "usage: og give [<name>] <file>...  |  [<name>] --clip"


def test_og_template_ls_json_is_its_json_reading_anything_else_after_ls_is_a_usage_error(og, recipes):
    code, out, _ = og("template", "ls", "--json")
    d = json.loads(out)
    assert code == 0 and "recipes" in d and "listing_ok" in d and d["recipes"]
    assert og("template", "ls", "--yaml")[0] != 0
    code, _, err = og("template", "ls", "extra")
    assert code != 0 and re.search(r"^usage: og template ", err, re.M)


@pytest.mark.parametrize("args", ["project", "project bogus", "project ls extra", "project add a b", "project add --nope",
                                  "style extra"])
def test_og_project_and_og_style_called_wrong_is_ogs_usage_line_exit_1_never_clicks_2(og, args):
    a = args.split()
    code, _, err = og(*a)
    assert code == 1 and err.startswith(f"usage: og {a[0]}")


# ── the exchange's own name rule, which help can't shadow ──

@pytest.mark.parametrize("name", ["--help", "-h"])
def test_a_dash_named_out_file_is_refused_by_the_exchange_not_shadowed_by_help(tmp_path, name):
    # out/ names are written by the sandbox: a file called --help is unreachable
    # through take, individually or under --all, because both run this check
    f = tmp_path / name
    f.write_text("")
    assert screen.check(Path(f), "out") == "its name doesn't start with a letter or digit"


# ── one sandbox-name rule, one reserved list ──

LONG, TOO_LONG = "a" * 61, "a" * 62


@pytest.mark.parametrize("n", ["fern", "a", "a.b_c-1", "Fern9", LONG])
def test_a_new_sandbox_name_is_a_letter_or_digit_then_dot_underscore_dash_up_to_61(n):
    assert naming.name_ok(n) and naming.name_chars(n)


@pytest.mark.parametrize("n", ["", ".x", "-x", "_x", "../x", "a/b", "a b", "a;b", TOO_LONG])
def test_and_nothing_else(n):
    assert not naming.name_ok(n)


def test_the_characters_alone_drop_only_the_cap():
    assert naming.name_chars(TOO_LONG) and not naming.name_chars("../x") and not naming.name_chars("")


def test_the_two_copies_agree_on_every_printable_character_first_and_later():
    for c in map(chr, range(32, 127)):
        for n in (c, "a" + c, LONG[:-1] + c, LONG + c):
            assert naming.name_ok(n) == (naming.name_chars(n) and len(n) <= 61), repr(n)


@pytest.mark.parametrize("n", ["inbox", "Inbox", "SHARED", "boxes", "Boxes"])
def test_inbox_shared_and_boxes_are_reserved_in_any_case(n):
    assert naming.reserved(n)


@pytest.mark.parametrize("n", ["fern", "inboxes", "share", "box", "sandbox", "sandboxes", "SandBoxes"])
def test_and_no_other_name_is(n):
    assert not naming.reserved(n)


# ── og help's list and each command's own usage line are one text ──

def _own_usage():
    from ogun import mcp, ship
    from ogun.core import changes, registry
    from ogun.exchange import give
    from ogun.sandbox import health, sandboxes, session, template
    from ogun.secrets import secret, token
    return {"mcp": mcp.MCP_USAGE, "ship": ship.SHIP_USAGE, "token": token.USAGE, "pass": secret.PASS_USAGE,
            "allow": allow.ALLOW_USAGE, "net": allow.NET_USAGE, "give": give.GIVE_USAGE, "take": take.TAKE_USAGE,
            "project": registry.PROJECT_USAGE, "log": changes.LOG_USAGE, "ports": health.PORTS_USAGE,
            "ls": sandboxes.LS_USAGE, "sh": sandboxes.SH_USAGE, "stop": sandboxes.STOP_USAGE, "rm": remove.RM_USAGE,
            "template": template.TEMPLATE_USAGE, "attach": session.ATTACH_USAGE}


@pytest.mark.parametrize("cmd", sorted(_own_usage()))
def test_og_helps_list_gives_each_command_the_usage_it_gives_itself(cmd):
    assert help.COMMANDS[cmd][0] == _own_usage()[cmd]
