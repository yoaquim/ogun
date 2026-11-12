"""og pass: one secret handed to one sandbox. Its argument gates (the variable's
shape, the host's, GitHub refused in any form, an unknown sandbox), the
set-custom it builds and the placeholder it reads back and exports, --expose
(the real value over the sandbox's stdin, never in argv), --paste as the value's
source (never printed, at any -v), --rm, the listing, and the scripts it runs
inside the sandbox, run for real against scratch files."""

import json
import subprocess

import pytest

from ogun.core import paths
from ogun.secrets import secret

LS = "NAME STATUS WORKSPACE\nfern running /x\n"
# as sbx answers (2026-10-29), but with another placeholder on the Saved line, so a
# test sees which line og read
SAVED = ("Applied secret updates to sandbox fern\nSaved custom secret sbx-cs-SAVEDLINE for target x env Y (fern)\n"
         "  Generated placeholder:  sbx-cs-TESTPH01\n")


def stub(fakes, *, ls_fail=False, set_out=SAVED, set_err="", set_code=0, exec_code=0, execi_fail=False,
         secrets="", secrets_json="", secrets_fail=False, rm_fail=False):
    """sbx as it answers for sandbox fern: exec_code is what its exec exits with
    (drop.sh says 3 for nothing to clear); secrets its `secret ls --sandbox`
    table, secrets_json the --json one."""
    s = fakes.sbx
    s.clear()
    s.answer(["ls"], stdout=LS, code=1 if ls_fail else 0)
    s.answer(["secret", "set-custom"], stdout=set_out, stderr=set_err, code=set_code)
    s.answer(["exec", "fern"], code=exec_code)
    s.answer(["exec", "-i"], code=1 if execi_fail else 0)
    s.answer(["secret", "ls", "--sandbox", "fern", "--json"], stdout=secrets_json, code=1 if secrets_fail else 0)
    s.answer(["secret", "ls"], stdout=secrets, code=1 if secrets_fail else 0)
    s.answer(["secret", "rm"], code=1 if rm_fail else 0)
    return s


@pytest.fixture
def sbx(fakes, monkeypatch):
    monkeypatch.delenv("OG_VAULT", raising=False)
    fakes.op.answer([], stdout="raw-secret-123")
    return stub(fakes)


def set_customs(s) -> list[list[str]]:
    return [c[2:] for c in s.calls if c[:2] == ["secret", "set-custom"]]


def exported(s, script="export.sh") -> list[list[str]]:
    """The arguments after the script each `sbx exec fern bash -lc <script>` was given."""
    body = secret.env_script(script)
    return [c[5:] for c in s.calls if c[:2] == ["exec", "fern"] and len(c) > 4 and c[4] == body]


def execi(s) -> list[list[str]]:
    return [c for c in s.calls if c[:2] == ["exec", "-i"]]


def removed(s) -> list[list[str]]:
    return [c for c in s.calls if c[:2] == ["secret", "rm"]]


def said(r) -> str:
    return r[1] + r[2]


# ── help ──

def test_help_names_env_var_and_explains_each_part_and_mode(og, sbx):
    code, out, _ = og("pass", "--help")
    assert code == 0
    for part in ("usage: og pass <name> <ENV_VAR> ", "og pass <name> <ENV_VAR> <host>…",
                 "swapped for the real value on requests to these hosts", "-p, --paste", "--item <name>", "docs/secrets.md"):
        assert part in out
    assert "--expose" in out and "the real value in the sandbox's environment" in out


def test_help_anywhere_in_the_line_is_help_never_a_pass(og, sbx):
    code, out, _ = og("pass", "fern", "K", "api.example.com", "--item", "i", "--help")
    assert code == 0 and "usage: og pass" in out
    assert not set_customs(sbx)


def test_a_bare_og_pass_prints_its_usage(og, sbx):
    code, out, err = og("pass")
    assert code == 1 and "usage: og pass <name> <ENV_VAR>" in out + err


def test_no_other_commands_help_carries_it(og, sbx):
    assert "--expose" not in og("ls", "--help")[1]


# ── gates ──

@pytest.mark.parametrize("args", [
    ["ghost", "API_KEY", "api.example.com", "--item", "i"],          # unknown sandbox
    ["fern", "2BAD-NAME", "api.example.com", "--item", "i"],         # not a variable name
    ["fern", "API_KEY", "bad host", "--item", "i"],
    ["fern", "GH2", "github.com", "--item", "i"],                    # one GitHub identity per sandbox
    ["fern", "GH2", "api.github.com", "--item", "i"],
    ["fern", "K", "api.example.com,github.com", "--item", "i"],      # hidden in a comma list
    ["fern", "K", "api.example.com", "github.com", "--item", "i"],   # a later host
    ["fern", "K", "api.example.com", "--bogus", "x"],
    ["fern", "K", "api.example.com", "--item"],                      # dangling: an error, never a loop
    ["fern", "GH2", "GITHUB.COM", "--item", "i"],                    # DNS is case-insensitive
    ["fern", "GH2", "api.GitHub.com", "--item", "i"],
    ["fern", "K", "api.example.com", "--expose", "--item", "i"],     # a host with --expose
    ["fern", "K", "raw.githubusercontent.com", "--item", "i"],
    ["fern", "K", "api.example.com", "--item", "i", "--vault"],
    ["fern", "K", "--expose", "--paste", "--item", "i"],             # two sources
], ids=["unknown sandbox", "bad env", "bad host", "github.com", "api.github.com", "comma list", "later host",
        "unknown option", "dangling --item", "GITHUB.COM", "api.GitHub.com", "host and --expose",
        "githubusercontent", "dangling --vault", "--paste and --item"])
def test_refused(og, sbx, args):
    assert og("pass", *args)[0] == 1
    assert not set_customs(sbx) and not execi(sbx)


@pytest.mark.parametrize("opt", [["--vault", "Office"], ["--field", "password"]])
def test_a_1password_option_with_paste_is_refused(og, sbx, opt):
    assert og("pass", "fern", "K", "--expose", "--paste", *opt, stdin="v")[0] == 1


@pytest.mark.parametrize("host", ["github.com/acme/app", "https://github.com/acme/app", "GitHub.com:443",
                                  "https://api.github.com/x"])
def test_a_github_address_in_any_shape_is_refused_with_the_command_that_replaces_its_token(og, sbx, host):
    r = og("pass", "fern", "GH2", host, "--paste", stdin="")
    assert r[0] == 1
    assert "GitHub is refused" in said(r) and "to replace that token, run:" in said(r) and "og fern --org" in said(r)


def test_the_github_refusal_names_the_owner_its_token_was_set_for(og, sbx, home):
    (home / ".local/state/ogun/tokens").mkdir()
    (home / ".local/state/ogun/tokens/fern.owner").write_text("acme\n")
    assert "og fern --org acme" in said(og("pass", "fern", "GH2", "github.com", "--item", "i"))


def test_a_web_address_that_isnt_githubs_says_to_name_the_host_alone(og, sbx):
    r = og("pass", "fern", "K", "https://api.example.com/v1", "--item", "i")
    assert r[0] == 1 and "name the host alone, like api.example.com" in said(r)


def test_a_list_sbx_couldnt_give_is_said_as_that_never_as_no_such_sandbox(og, fakes, sbx):
    stub(fakes, ls_fail=True)
    r = og("pass", "fern", "K", "api.example.com", "--item", "i")
    assert r[0] == 1 and "sbx couldn't list its sandboxes" in said(r) and "no sandbox" not in said(r)


def test_no_host_and_no_expose_is_refused_the_real_value_is_never_the_default(og, sbx):
    r = og("pass", "fern", "AGE_KEY", "--item", "i")
    assert r[0] == 1 and "name the host(s)" in said(r) and "--expose" in said(r)


# ── the proxy ──

def test_set_custom_gets_the_hosts_the_variable_and_the_op_reference_for_this_sandbox_alone(og, sbx):
    assert og("pass", "fern", "MAILER_KEY", "api.mailer.example,app.mailer.example", "--item", "Mailer key")[0] == 0
    assert set_customs(sbx) == [["--sandbox", "fern", "--host", "api.mailer.example", "--host", "app.mailer.example",
                                 "--env", "MAILER_KEY", "--ref", "op://Sandbox/Mailer key/credential"]]


def test_the_generated_placeholder_is_exported_into_the_running_sandbox(og, sbx):
    og("pass", "fern", "MAILER_KEY", "api.mailer.example", "--item", "i")
    assert exported(sbx) == [["_", "MAILER_KEY", "sbx-cs-TESTPH01"]]


def test_the_done_line_says_where_the_value_came_from(og, sbx):
    r = og("pass", "fern", "K", "api.example.com", "--paste", stdin="v\n")
    assert r[0] == 0 and "you pasted it" in said(r)
    r = og("pass", "fern", "K", "api.example.com", "--item", "i")
    assert r[0] == 0 and "from op://Sandbox/i/credential" in said(r)


def test_listed_hosts_collect_like_a_comma_list_flags_anywhere_between(og, sbx):
    og("pass", "fern", "MAILER2", "api.mailer.example", "--item", "i", "app.mailer.example")
    assert set_customs(sbx)[0][2:6] == ["--host", "api.mailer.example", "--host", "app.mailer.example"]


def test_a_missing_item_is_asked_for(og, sbx):
    assert og("pass", "fern", "K", "api.example.com", stdin="Asked Item\n")[0] == 0
    assert set_customs(sbx)[0][-2:] == ["--ref", "op://Sandbox/Asked Item/credential"]


def test_an_empty_answer_is_refused_nothing_registered(og, sbx):
    assert og("pass", "fern", "K", "api.example.com", stdin="\n")[0] == 1
    assert not set_customs(sbx)


def test_vault_and_field_shape_the_op_reference(og, sbx):
    og("pass", "fern", "K2", "api.example.com", "--item", "It", "--vault", "Office", "--field", "password")
    assert set_customs(sbx)[0][-2:] == ["--ref", "op://Office/It/password"]


def test_a_placeholder_named_only_in_set_customs_other_line_is_still_found(og, fakes, sbx):
    s = stub(fakes, set_out='Saved custom secret placeholder "sbx-cs-ONLYSAVED" in scope "fern"\n')
    assert og("pass", "fern", "K8", "api.example.com", "--item", "i")[0] == 0
    assert exported(s) == [["_", "K8", "sbx-cs-ONLYSAVED"]]


def test_no_placeholder_in_the_answer_fails_the_pass_nothing_exported(og, fakes, sbx):
    s = stub(fakes, set_out="Saved.\n")
    assert og("pass", "fern", "K9", "api.example.com", "--item", "i")[0] == 1
    assert not [c for c in s.calls if c[:1] == ["exec"]]


def test_a_set_custom_failure_fails_the_pass_with_sbxs_words_as_a_note(og, fakes, sbx):
    stub(fakes, set_out="ERROR: nope\n", set_code=1)
    r = og("pass", "fern", "K3", "api.example.com", "--item", "i")
    assert r[0] == 1 and "sbx couldn't register the secret:\n  · ERROR: nope" in said(r)


def test_a_placeholder_that_cant_be_written_into_the_sandbox_undoes_its_registration(og, fakes, sbx):
    s = stub(fakes, exec_code=1)
    r = og("pass", "fern", "K6", "api.example.com", "--item", "i")
    assert r[0] == 1
    assert removed(s) == [["secret", "rm", "--sandbox", "fern", "--placeholder", "sbx-cs-TESTPH01", "-f"]]
    assert "removed again" in said(r) and "og pass fern K6 api.example.com --item i" in said(r)


def test_when_the_undo_fails_too_it_names_that_one_placeholder_never_rm(og, fakes, sbx):
    stub(fakes, exec_code=1, rm_fail=True)
    r = og("pass", "fern", "K7", "api.example.com", "--item", "i")
    assert r[0] == 1
    assert "sbx secret rm --sandbox fern --placeholder sbx-cs-TESTPH01 -f" in said(r) and "--rm" not in said(r)


# ── --expose: the real value over stdin ──

def test_expose_sends_the_real_value_from_op_to_the_sandboxs_stdin_never_in_argv(og, fakes, sbx):
    assert og("pass", "fern", "AGE_KEY", "--expose", "--item", "fern age key")[0] == 0
    assert fakes.op.calls == [["read", "-n", "op://Sandbox/fern age key/credential"]]
    assert sbx.stdin[sbx.calls.index(execi(sbx)[0])] == "raw-secret-123"
    assert execi(sbx)[0][2:4] == ["fern", "bash"] and execi(sbx)[0][-2:] == ["_", "AGE_KEY"]
    assert not any("raw-secret-123" in a for c in sbx.calls for a in c)
    assert not set_customs(sbx)


@pytest.mark.parametrize("item", ["github-pat-personal-desk", "My GitHub token"])
def test_a_github_item_is_refused_exposed_before_any_read(og, fakes, sbx, item):
    r = og("pass", "fern", "T", "--expose", "--item", item)
    assert r[0] == 1 and "never exposed" in said(r)
    assert fakes.op.calls == [] and sbx.calls == [["ls"]]


@pytest.mark.parametrize("env", ["GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN"])
def test_the_names_gh_and_git_read_are_refused_exposed_whatever_the_item(og, fakes, sbx, env):
    r = og("pass", "fern", env, "--expose", "--item", "Office PAT")
    assert r[0] == 1 and "never exposed" in said(r)
    assert fakes.op.calls == []


def test_a_failed_1password_read_fails_the_pass_and_says_it_was_1password(og, fakes, sbx):
    fakes.op.clear()
    fakes.op.answer([], code=1)
    r = og("pass", "fern", "K4", "--expose", "--item", "i")
    assert r[0] == 1 and "1Password couldn't read" in said(r) and "inside fern" not in said(r)


def test_so_does_one_that_fails_partway_though_the_sandbox_took_what_came(og, fakes, sbx):
    fakes.op.clear()
    fakes.op.answer([], stdout="raw-sec", code=1)
    assert og("pass", "fern", "K4", "--expose", "--item", "i")[0] == 1


def test_a_sandbox_write_failure_fails_the_pass(og, fakes, sbx):
    stub(fakes, execi_fail=True)
    assert og("pass", "fern", "K5", "--expose", "--item", "i")[0] == 1


# ── --paste: the value from a prompt or a pipe instead of 1Password ──

def test_expose_paste_delivers_a_piped_value_over_stdin_its_newline_dropped_no_1password(og, fakes, sbx):
    assert og("pass", "fern", "AGE_KEY", "--expose", "--paste", stdin="pasted-789\n")[0] == 0
    assert sbx.stdin[sbx.calls.index(execi(sbx)[0])] == "pasted-789"
    assert fakes.op.calls == []
    assert not any("pasted-789" in a for c in sbx.calls for a in c)
    assert execi(sbx)[0][-2:] == ["_", "AGE_KEY"]


def test_a_piped_multi_line_value_arrives_whole(og, sbx):
    assert og("pass", "fern", "K", "-p", "--expose", stdin="l1\nl2\n")[0] == 0
    assert sbx.stdin[sbx.calls.index(execi(sbx)[0])] == "l1\nl2"


def test_an_empty_paste_is_refused(og, sbx):
    assert og("pass", "fern", "K", "--expose", "--paste", stdin="")[0] == 1


def test_a_pasted_github_token_is_refused_exposed_before_any_write(og, sbx):
    r = og("pass", "fern", "MY_TOKEN", "--expose", "--paste", stdin="ghp_abc123")
    assert r[0] == 1 and "GitHub token" in said(r)
    assert not execi(sbx)


def test_a_pasted_value_goes_to_the_proxy_as_set_custom_value_no_1password(og, fakes, sbx):
    assert og("pass", "fern", "API_KEY", "api.example.com", "--paste", stdin="pasted-proxy\n")[0] == 0
    assert set_customs(sbx) == [["--sandbox", "fern", "--host", "api.example.com", "--env", "API_KEY",
                                 "--value", "pasted-proxy"]]
    assert fakes.op.calls == []
    assert exported(sbx) == [["_", "API_KEY", "sbx-cs-TESTPH01"]]


def test_a_pasted_value_is_never_printed_to_the_proxy_or_exposed(og, sbx):
    r = og("pass", "fern", "API_KEY", "api.example.com", "--paste", stdin="pasted-hush\n")
    assert r[0] == 0 and "pasted-hush" not in said(r)
    r = og("pass", "fern", "AGE_KEY", "--expose", "--paste", stdin="pasted-hush")
    assert r[0] == 0 and "pasted-hush" not in said(r)


def test_nor_at_vv_which_shows_each_sbx_command_with_the_value_not_shown(og, sbx):
    r = og("-vv", "pass", "fern", "API_KEY", "api.example.com", "--paste", stdin="pasted-hush")
    assert r[0] == 0
    assert "pasted-hush" not in said(r) and "--value '<the value, not shown>'" in said(r)


def test_nor_when_sbxs_error_echoes_it_back(og, fakes, sbx):
    stub(fakes, set_out="", set_err="ERROR: bad arguments: --env API_KEY --value pasted-hush\n", set_code=1)
    r = og("pass", "fern", "API_KEY", "api.example.com", "--paste", stdin="pasted-hush")
    assert r[0] == 1 and "bad arguments" in said(r) and "pasted-hush" not in said(r)


def test_a_multi_line_one_echoed_back_at_vv_shows_no_line_of_it(og, fakes, sbx):
    stub(fakes, set_out="", set_code=1,
         set_err="ERROR: bad arguments: --value first-secret-line\nsecond-secret-line\n")
    r = og("-vv", "pass", "fern", "API_KEY", "api.example.com", "--paste", stdin="first-secret-line\nsecond-secret-line\n")
    assert r[0] == 1 and "bad arguments" in said(r)
    assert "first-secret-line" not in said(r) and "second-secret-line" not in said(r)


# ── --rm: what pass gave, removed ──

# sbx secret ls --sandbox fern, as sbx prints it (2026-10-29): service rows first, then the custom ones
SECRETS = """
  SCOPE      TYPE      NAME     SECRET
  fern       service   github   (stored)

  CUSTOM SECRETS
  SCOPE      TARGETS            ENV        PLACEHOLDER        SECRET
  fern       api.example.com    TESTKEY    sbx-cs-AAAA1111    dummy-***
  fern       a.example.com, b.example.com   TESTKEY    sbx-cs-BBBB2222    ref:op://Sandbox/x/credential (on-demand)
  fern       api.other.com      OTHERKEY   sbx-cs-CCCC3333    ref:op://Sandbox/y/credential (on-demand)
"""


def rm_ph(ph: str) -> list[str]:
    return ["secret", "rm", "--sandbox", "fern", "--placeholder", ph, "-f"]


def test_rm_removes_each_registration_of_that_variable_and_clears_its_env(og, fakes, sbx):
    s = stub(fakes, secrets=SECRETS)
    r = og("pass", "fern", "TESTKEY", "--rm")
    assert r[0] == 0
    assert removed(s) == [rm_ph("sbx-cs-AAAA1111"), rm_ph("sbx-cs-BBBB2222")]
    assert exported(s, "drop.sh") == [["_", "TESTKEY"]]
    assert "✓ removed TESTKEY from fern" in said(r) and "sbx dropped it; the proxy may swap it in until sbx restarts" in said(r)


def test_rm_of_nothing_anywhere_is_said_nothing_removed_not_a_failure(og, fakes, sbx):
    s = stub(fakes, secrets=SECRETS, exec_code=3)
    r = og("pass", "fern", "NOPE", "--rm")
    assert r[0] == 0 and "fern has no NOPE: nothing to remove" in said(r) and "✓" not in said(r)
    assert not removed(s)


def test_rm_of_an_exposed_one_which_sbx_never_held_clears_it_from_the_env(og, fakes, sbx):
    stub(fakes, secrets=SECRETS)
    r = og("pass", "fern", "AGE_KEY", "--rm")
    assert r[0] == 0 and "✓ removed AGE_KEY from fern  gone from its environment" in said(r)


@pytest.mark.parametrize("knobs", [
    {"secrets": "  SCOPE TARGETS ENV PLACEHOLDER SECRET\n  fern something-new\n"},   # a layout og can't read
    {"secrets_fail": True},
    # a custom-secrets header og doesn't know: never "nothing to remove" while the secret stays live
    {"secrets": "  SCOPE  TARGETS  ENV  PLACEHOLDER  VALUE\n  fern  api.example.com  TESTKEY  sbx-cs-AAAA1111  dummy-***\n"},
], ids=["unreadable row", "sbx failed", "unknown header"])
def test_rm_from_a_listing_og_cant_read_removes_nothing(og, fakes, sbx, knobs):
    s = stub(fakes, **knobs)
    r = og("pass", "fern", "TESTKEY", "--rm")
    assert r[0] == 1 and "couldn't read fern's secrets" in said(r)
    assert [c for c in s.calls if c[:1] != ["ls"] and c[:2] != ["secret", "ls"]] == []


def test_a_listing_with_only_its_service_rows_has_nothing_to_remove(og, fakes, sbx):
    stub(fakes, secrets="\n  SCOPE  TYPE  NAME  SECRET\n  fern  service  github  (stored)\n", exec_code=3)
    assert "nothing to remove" in said(og("pass", "fern", "NOPE", "--rm"))


def test_an_empty_answer_with_neither_header_says_nothing_nothing_removed_or_cleared(og, fakes, sbx):
    s = stub(fakes, secrets="")
    assert og("pass", "fern", "TESTKEY", "--rm")[0] == 1
    assert [c for c in s.calls if c[:1] != ["ls"] and c[:2] != ["secret", "ls"]] == []


def test_one_sbx_wont_remove_fails_with_the_command_to_do_it_by_hand(og, fakes, sbx):
    stub(fakes, secrets=SECRETS, rm_fail=True)
    r = og("pass", "fern", "TESTKEY", "--rm")
    assert r[0] == 1 and "sbx secret rm --sandbox fern --placeholder sbx-cs-AAAA1111" in said(r)


def test_an_environment_it_cant_clear_fails_the_command_on_its_own_line(og, fakes, sbx):
    stub(fakes, secrets=SECRETS, exec_code=1)
    r = og("pass", "fern", "TESTKEY", "--rm")
    assert r[0] == 1 and "✓" not in said(r)
    assert ("sbx dropped TESTKEY, but og couldn't clear it from fern's environment; to clear it, run:\n" in said(r)
            and "og sh fern sudo sed -i '/^export TESTKEY=/d' /etc/sandbox-persistent.sh" in said(r))


def test_one_a_registry_grant_gave_says_what_comes_back_before_its_done_line(og, fakes, sbx, home):
    stub(fakes, secrets=SECRETS)
    d = paths.state_dir() / "sandboxes"
    d.mkdir(parents=True)
    (d / "fern.json").write_text('{"secrets": [{"env": "TESTKEY"}]}')
    r = og("pass", "fern", "TESTKEY", "--rm")
    assert r[0] == 0
    assert "TESTKEY came from registry.json: attaching won't give it back to fern" in said(r)
    assert said(r).index("came from registry.json") < said(r).index("✓ removed TESTKEY from fern")


@pytest.mark.parametrize("args", [["fern", "TESTKEY", "api.example.com", "--rm"], ["ghost", "TESTKEY", "--rm"]])
def test_rm_takes_nothing_else_nor_a_sandbox_that_isnt_there(og, sbx, args):
    assert og("pass", *args)[0] == 1
    assert not removed(sbx)


# ── og pass <name>: what sbx holds for it ──

# in the shape `sbx secret ls --sandbox --json` gives; the pasted row's shape is a
# guess: sbx's table showed a pasted value as its first letters, `dummy-***`
SJSON = json.dumps({
    "secrets": [{"scope": "fern", "type": "service", "name": "github", "secret": "(stored)"}],
    "custom_secrets": [
        {"scope": "fern", "targets": ["*.mailer.example"], "env": "MAILER_API_KEY", "placeholder": "sbx-cs-CCCC",
         "kind": "ref", "source": "op://Sandbox/acme-mailer/credential", "refresh": "on-demand"},
        {"scope": "fern", "targets": ["api.example.com", "b.example.com"], "env": "PASTED_KEY", "placeholder": "sbx-cs-PPPP",
         "kind": "value", "source": "dummy-***"},
        {"scope": "other", "targets": ["x.example"], "env": "NOT_FERNS", "placeholder": "sbx-cs-OOOO", "kind": "ref",
         "source": "op://Sandbox/x/credential"}],
    "shadowed_services": [], "env_only_count": 0})


def test_og_pass_name_lists_its_secrets_a_line_each_and_changes_nothing(og, fakes, sbx):
    s = stub(fakes, secrets_json=SJSON)
    r = og("pass", "fern")
    assert r[0] == 0
    lines = said(r).splitlines()
    assert ("  · MAILER_API_KEY: swapped in on *.mailer.example · from 1Password: "
            "Sandbox/acme-mailer/credential · sbx-cs-CCCC") in lines
    assert "  · PASTED_KEY: swapped in on api.example.com, b.example.com · from pasted · sbx-cs-PPPP" in lines
    assert "dummy" not in said(r) and "NOT_FERNS" not in said(r)
    assert "GitHub: its own token, set by og" in said(r) and "og pass fern <ENV_VAR> --rm" in said(r)
    assert [c for c in s.calls if c[:2] not in (["ls"], ["secret", "ls"])] == []


def test_v_changes_none_of_the_listing(og, fakes, sbx):
    stub(fakes, secrets_json=SJSON)
    assert og("-v", "pass", "fern")[1] == og("pass", "fern")[1]


@pytest.mark.parametrize(("knobs", "name"), [({"secrets_fail": True}, "fern"), ({"secrets_json": "not json"}, "fern"),
                                             ({"secrets_json": SJSON}, "ghost")])
def test_a_list_sbx_couldnt_give_or_a_sandbox_that_isnt_there_is_an_error(og, fakes, sbx, knobs, name):
    stub(fakes, **knobs)
    assert og("pass", name)[0] == 1


def test_vv_never_shows_what_sbx_said_about_secrets_listing_or_removing(og, fakes, sbx):
    stub(fakes, secrets_json=SJSON, secrets=SECRETS)
    r = og("-vv", "pass", "fern")
    assert r[0] == 0 and "dummy" not in said(r) and "sbx secret's output isn't shown" in said(r)
    r = og("-vv", "pass", "fern", "TESTKEY", "--rm")
    assert r[0] == 0 and "dummy" not in said(r)


# ── the scripts it runs inside a sandbox, run for real against scratch files ──

def run_script(name: str, *args: str, value: str = "", **env) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", secret.env_script(name), "_", *args], input=value, text=True,
                          capture_output=True, env={"PATH": "/usr/bin:/bin", **env})


def sourced(envfile, var: str) -> str:
    return subprocess.run(["bash", "-c", f'. "$1" && printf %s "${var}"', "_", str(envfile)],
                          capture_output=True, text=True).stdout


def test_an_env_script_is_read_from_ogs_own_tree():
    f = paths.SCRIPTS / "env/expose.sh"
    assert secret.env_script("expose.sh") == f.read_text()


def test_drop_clears_every_export_of_that_variable_no_other_and_exits_3_when_none(tmp_path):
    f = tmp_path / "env"
    f.write_text("export A=1\nexport TESTKEY=sbx-cs-X\nexport TESTKEY=$'l1\\nl2'\nexport TESTKEY2=k\n")
    assert run_script("drop.sh", "TESTKEY", str(f)).returncode == 0
    assert f.read_text() == "export A=1\nexport TESTKEY2=k\n"
    assert run_script("drop.sh", "TESTKEY", str(f)).returncode == 3


def test_export_writes_the_placeholders_line_replacing_only_that_variables(tmp_path):
    f = tmp_path / "env"
    f.write_text("export KEY=old\nexport KEYX=1\nexport OTHER=2\n")
    assert run_script("export.sh", "KEY", "sbx-ph-1", str(f)).returncode == 0
    assert f.read_text() == "export KEYX=1\nexport OTHER=2\nexport KEY=sbx-ph-1\n"
    assert run_script("export.sh", "KEY", "sbx-ph-2", str(f)).returncode == 0
    assert f.read_text().count("export KEY=") == 1 and sourced(f, "KEY") == "sbx-ph-2"


def test_export_to_an_env_not_there_yet_makes_it(tmp_path):
    f = tmp_path / "env"
    assert run_script("export.sh", "KEY", "sbx-ph-1", str(f)).returncode == 0 and f.read_text() == "export KEY=sbx-ph-1\n"


def test_unexport_drops_exactly_that_placeholders_line(tmp_path):
    f = tmp_path / "env"
    f.write_text("export KEY=sbx-ph-1\nexport OTHER=2\n")
    assert run_script("unexport.sh", "KEY", "sbx-ph-1", str(f)).returncode == 0 and f.read_text() == "export OTHER=2\n"
    f.write_text("export KEY=sbx-ph-1\nexport KEY=set-by-hand\n")
    assert run_script("unexport.sh", "KEY", "sbx-ph-1", str(f)).returncode == 0 and f.read_text() == "export KEY=set-by-hand\n"


def test_unexport_keeps_a_value_passed_again_since_and_a_missing_one_is_no_error(tmp_path):
    f = tmp_path / "env"
    f.write_text("export KEY=real-now\n")
    assert run_script("unexport.sh", "KEY", "sbx-ph-1", str(f)).returncode == 0 and f.read_text() == "export KEY=real-now\n"
    assert run_script("unexport.sh", "KEY", "sbx-ph-1", str(tmp_path / "none")).returncode == 0
    assert not (tmp_path / "none").exists()


def test_expose_lands_a_multi_line_value_sourceable_back(tmp_path):
    f = tmp_path / "env"
    assert run_script("expose.sh", "KEY", str(f), value="line1\nline2").returncode == 0
    assert f.read_text().count("export KEY=") == 1
    assert sourced(f, "KEY") == "line1\nline2"


def test_a_re_pass_replaces_the_prior_line_never_duplicates(tmp_path):
    f = tmp_path / "env"
    run_script("expose.sh", "KEY", str(f), value="v1")
    assert run_script("expose.sh", "KEY", str(f), value="v2").returncode == 0
    assert f.read_text().count("export KEY=") == 1
    assert sourced(f, "KEY") == "v2"


def test_an_empty_value_is_refused_by_the_script(tmp_path):
    assert run_script("expose.sh", "KEY", str(tmp_path / "env"), value="").returncode != 0


def test_trailing_newlines_survive_byte_for_byte(tmp_path):
    f = tmp_path / "env"
    assert run_script("expose.sh", "KEY", str(f), value="v\n\n").returncode == 0
    assert sourced(f, "KEY") == "v\n\n"


def test_a_failed_write_leaves_no_secret_temp_file_behind(tmp_path):
    t = tmp_path / "tmpdir"
    t.mkdir()
    assert run_script("expose.sh", "KEY", str(tmp_path / "nodir/env"), value="x", TMPDIR=str(t)).returncode != 0
    assert list(t.iterdir()) == []


# ── og pass's parts, each on its own ──

def test_flags_hosts_collect_as_a_comma_list_the_vault_and_field_default(home):
    from ogun.secrets import github
    assert secret.pass_flags("fern", "K", ["a.io,b.io", "c.io"]) == {
        "hosts": ["a.io", "b.io", "c.io"], "expose": False, "paste": False, "op_opt": "",
        "item": "", "vault": github.vault(), "field": "credential"}


def test_flags_an_item_is_no_1password_option_to_refuse_with_paste_a_vault_is(home):
    o = secret.pass_flags("fern", "K", ["--item", "it", "-p", "--expose"])
    assert (o["item"], o["paste"], o["expose"], o["op_opt"]) == ("it", True, True, "")
    assert secret.pass_flags("fern", "K", ["--field", "f", "--vault", "V"])["op_opt"] == "--vault"


@pytest.mark.parametrize(("args", "says"), [
    (["--host", "a.io"], "usage: og pass"), (["--raw"], "usage: og pass"),
    (["--item"], "usage: og pass"), (["--nope"], "usage: og pass")])
def test_flags_that_dont_parse_are_one_and_say_why(home, capfd, args, says):
    assert secret.pass_flags("fern", "K", args) == 1 and says in "".join(capfd.readouterr())


def flags(**kw) -> dict:
    return {"hosts": ["api.example.com"], "expose": False, "paste": False, "op_opt": "", "item": "it",
            "vault": "Sandbox", "field": "credential", **kw}


def test_a_pass_with_every_rule_kept_is_not_refused(sbx, capfd):
    assert not secret.refused("fern", "API_KEY", flags())
    assert capfd.readouterr().err == ""


def test_a_sandbox_that_isnt_there_is_refused(sbx):
    assert secret.refused("nope", "API_KEY", flags())


@pytest.mark.parametrize(("env", "kw", "says"), [
    ("1BAD", {}, "isn't an environment variable name"),
    ("API_KEY", {"expose": True}, "--expose takes no host"),
    ("API_KEY", {"hosts": []}, "name the host(s) the proxy swaps the value in on"),
    ("API_KEY", {"paste": True}, "--paste and --item are two sources"),
    ("API_KEY", {"paste": True, "item": "", "op_opt": "--vault"}, "--vault is for a 1Password item"),
    ("API_KEY", {"hosts": ["https://github.com/x/y"]}, "GitHub is refused"),
    ("API_KEY", {"hosts": ["api.example.com/v1"]}, "isn't a host name"),
    ("GH_TOKEN", {"expose": True, "hosts": []}, "GH_TOKEN is never exposed"),
], ids=["variable name", "expose with a host", "no host", "paste and item", "paste and vault", "github host",
        "a path", "github variable exposed"])
def test_each_rule_refuses_and_says_which(sbx, capfd, env, kw, says):
    assert secret.refused("fern", env, flags(**kw))
    assert says in capfd.readouterr().err


def test_a_value_piped_in_with_paste_keeps_every_byte_but_the_last_newline(monkeypatch):
    import io
    import sys
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"line1\nline2\n")))
    assert secret.value_source("fern", "K", flags(paste=True, item="")) == (b"line1\nline2", "pasted", "")


@pytest.mark.parametrize(("piped", "kw", "says"), [
    (b"", {}, "nothing was pasted"), (b"ghp_abc\n", {"expose": True}, "that's a GitHub token, never exposed")])
def test_a_paste_that_is_empty_or_an_exposed_github_token_is_none(monkeypatch, capfd, piped, kw, says):
    import io
    import sys
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(piped)))
    assert secret.value_source("fern", "K", flags(paste=True, item="", **kw)) is None
    assert says in capfd.readouterr().err


def test_an_item_is_a_1password_reference_and_one_not_given_is_read_from_stdin(monkeypatch):
    import io
    import sys
    assert secret.value_source("fern", "K", flags(field="f")) == (None, "op://Sandbox/it/f", "it")
    monkeypatch.setattr(sys, "stdin", io.StringIO("asked\n"))
    assert secret.value_source("fern", "K", flags(item="")) == (None, "op://Sandbox/asked/credential", "asked")


@pytest.mark.parametrize(("item", "says"), [("", "a 1Password item is needed"),
                                            ("my-GitHub-pat", "GitHub items are never exposed")])
def test_no_item_or_an_exposed_github_item_is_none(monkeypatch, capfd, item, says):
    import io
    import sys
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert secret.value_source("fern", "K", flags(item=item, expose=True, hosts=[])) is None
    assert says in capfd.readouterr().err
