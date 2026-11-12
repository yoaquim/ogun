"""template: where the recipes live, and the golden template build: refused while
the Mac's ssh-agent is forwarded, before anything is created; Claude Code brought
to the latest release before the save, best effort."""

import json
import shutil

import pytest

from conftest import FIXTURES, use_profile, with_header
from conftest import TST_RECIPE as TST
from ogun.core import paths, settings
from ogun.sandbox import template


def test_recipes_live_in_ogs_config_folder(home):
    assert template.recipes_dir() == home / ".config/ogun/templates"


def test_recipes_are_the_named_scripts_there(home):
    d = home / ".config/ogun/templates"
    d.mkdir(parents=True)
    for f in ("web.sh", "data-1.sh", "Bad Name.sh", "notes.md"):
        (d / f).write_text("")
    assert template.recipes() == ["data-1", "web"]


# ── the golden template build ──

@pytest.fixture
def build(fakes, og, home):
    """og template home, sbx answering as given: ssh-agent forwarding read as
    `agent`, the Claude Code update answering `update`."""
    d = home / ".config/ogun/templates"
    d.mkdir(parents=True)
    shutil.copy(FIXTURES / "templates/home.sh", d)

    def run(agent="false\n", update_code=0):
        fakes.sbx.clear()
        fakes.sbx.answer(["settings", "get"], stdout=agent)
        fakes.sbx.answer(["exec"], stdout="v 2.1.277 2.1.280\n", code=update_code, has="claude update")
        return og("template", "home")
    return run


def test_the_build_refuses_while_forwarding_is_on_before_creating_anything(build, fakes, home):
    assert build(agent="true\n")[0] == 1
    assert ["settings", "set", "ssh.agentForwardingEnabled", "false"] in fakes.sbx.calls
    assert not [c for c in fakes.sbx.calls if c[:2] == ["env", "create"] or c[:1] in (["rm"], ["exec"])]
    assert not (home / ".local/state/sbx-golden-home").exists()


@pytest.mark.parametrize("update_code", [0, 1], ids=["updated", "update failed"])
def test_the_build_updates_claude_code_before_saving_and_saves_even_when_that_fails(build, fakes, update_code):
    assert build(update_code=update_code)[0] == 0
    calls = [" ".join(c) for c in fakes.sbx.calls]
    update = next(i for i, c in enumerate(calls) if "claude update" in c)
    save = calls.index("template save golden-home ogun-home")
    assert update < save


# ── recipes, og template ls and rm ──

def test_recipes_are_every_templates_sh_sorted(recipes):
    assert template.recipes() == ["home", "orders", "tst", "work"]


def test_template_ls_each_recipe_its_image_built_or_not_and_when_and_how_to_build_the_rest(og, stub):
    stub("ogun-work", "desk")
    code, out, _ = og("template", "ls")
    lines = out.splitlines()
    assert code == 0
    assert any(x.split() == ["work", "ogun-work:latest", "yes", "3", "days", "ago"] for x in lines)
    assert any(x.split() == ["home", "ogun-home:latest", "no", "-"] for x in lines)
    assert any(x.split()[:3] == ["tst", "ogun-tst:latest", "no"] for x in lines)
    assert "desk" not in out
    assert "to build one: og template home, og template orders, og template tst" in lines


def test_template_ls_from_a_listing_sbx_couldnt_give_fails_never_reads_as_nothing_built(og, stub):
    stub(tpl_fail=True)
    code, out, err = og("template", "ls")
    assert code != 0 and "what's built is unknown" in out + err


def test_template_ls_json_every_recipe_its_image_when_and_its_build_and_runtime_egress(og, stub, recipes):
    use_profile(recipes, "work")
    stub("ogun-work", "desk")
    d = json.loads(og("template", "ls", "--json")[1])
    assert d["profile"] == "work" and d["listing_ok"] is True and "legacy" not in d
    by = {r["name"]: r for r in d["recipes"]}
    assert list(by) == ["home", "orders", "tst", "work"]
    assert by["orders"]["egress"] == [] and by["orders"]["runtime_egress"] == ["api.orders.example"]
    assert by["work"] == {"name": "work", "image": "ogun-work:latest", "built": True, "created": "3 days ago",
                          "egress": ["sh.rustup.rs", "static.rust-lang.org"],
                          "runtime_egress": ["index.crates.io", "static.crates.io", "*.rust-lang.org"]}
    assert by["tst"]["built"] is False and by["tst"]["created"] == ""
    assert by["tst"]["egress"] == ["example.com", "*.example.org"]
    assert by["tst"]["runtime_egress"] == ["api.example.com", "*.api.example.com"]


def test_template_ls_json_leaves_built_unknown_when_sbx_couldnt_list(og, stub):
    stub(tpl_fail=True)
    code, out, _ = og("template", "ls", "--json")
    d = json.loads(out)
    assert code == 0 and d["listing_ok"] is False and all(r["built"] is None for r in d["recipes"])


def test_template_rm_removes_that_recipes_image_without_asking_and_says_how_to_build_it(og, stub):
    s = stub("ogun-work")
    code, out, _ = og("template", "rm", "work")
    assert code == 0 and ["template", "rm", "ogun-work:latest", "-f"] in s.calls
    assert "✓ removed ogun-work:latest" in out and "og template work" in out


def test_template_rm_of_one_not_built_has_nothing_to_remove_and_isnt_a_failure(og, stub):
    s = stub()
    code, out, err = og("template", "rm", "work")
    assert code == 0 and "isn't built here: nothing to remove" in out + err
    assert not [c for c in s.calls if c[:2] == ["template", "rm"]]


@pytest.mark.parametrize(("args", "knobs"), [(["x;y"], {}), ([], {}), (["work"], {"tpl_fail": True})],
                         ids=["off a recipe's shape", "none", "sbx couldn't list"])
def test_template_rm_refused_removes_nothing(og, stub, args, knobs):
    s = stub("ogun-work", **knobs)
    assert og("template", "rm", *args)[0] != 0
    assert not [c for c in s.calls if c[:2] == ["template", "rm"]]


def test_a_build_of_a_recipe_that_isnt_there_is_refused(og, stub):
    code, out, err = og("template", "nosuchrecipe")
    assert code == 1 and (out + err).startswith("og template: ") and "no recipe ~/.config/ogun/templates/nosuchrecipe.sh" in out + err


@pytest.mark.parametrize("args", [["tst", "work"], ["--json"]], ids=["two names", "an option"])
def test_two_names_or_an_option_it_doesnt_take_are_refused_before_any_sbx_call(og, stub, args):
    s = stub()
    n = len(s.calls)
    assert og("template", *args)[0] != 0
    assert s.calls[n:] == []


def test_help_anywhere_in_the_line_is_the_help_box_never_a_build(og, stub):
    s = stub()
    code, out, _ = og("template", "home", "--help")
    assert code == 0 and "usage: og template" in out and "og template ls" in out
    assert not [c for c in s.calls if c[:2] == ["env", "create"]]


@pytest.mark.parametrize(("recipe", "key", "values"), [
    ("tst", "egress", ["example.com", "*.example.org"]),
    ("work", "egress", ["sh.rustup.rs", "static.rust-lang.org"]),
    ("work", "runtime-egress", ["index.crates.io", "static.crates.io", "*.rust-lang.org"]),
    ("orders", "egress", []),                         # it builds from the baseline alone
    ("orders", "runtime-egress", ["api.orders.example"]),   # and opens only its staging API at runtime
])
def test_headers_are_read_from_the_leading_comment_block(recipes, recipe, key, values):
    assert template.header(recipes / f".config/ogun/templates/{recipe}.sh", key) == values


# ── the build: base, update, recipe, scrub, save; nothing saved on failure ──

GOLDEN = "golden-tst"


def order(calls, *needles) -> bool:
    """Each needle is in some call, the first of each in this order."""
    joined = [" ".join(c) for c in calls]
    at = [next((i for i, c in enumerate(joined) if n in c), -1) for n in needles]
    return -1 not in at and at == sorted(at)


def test_a_build_runs_in_its_own_sandbox_every_step_in_order_then_removes_it(og, stub, recipes):
    s = stub(golden=[GOLDEN])
    assert og("template", "tst")[0] == 0
    ws = recipes / ".local/state/sbx-golden-tst"
    assert order(s.calls, f"env create {ws}/.sbxenv.yaml", "policy allow network deb.debian.org",
                 "policy allow network --sandbox golden-tst example.com,*.example.org", "apt-get",
                 "claude update", "exec -i golden-tst bash -c cat > /tmp/ogun-recipe.sh",
                 "exec golden-tst bash -lc bash -euo pipefail /tmp/ogun-recipe.sh", "rm -rf /tmp/ogun-recipe.sh",
                 "stop golden-tst", "template save golden-tst ogun-tst", "rm golden-tst")
    assert [f"{ws}/.sbxenv.yaml", "--force"] == next(c[2:] for c in s.calls if c[:2] == ["env", "create"])
    assert not any("--auto-approve" in c for c in s.calls)



def test_its_declared_egress_is_for_the_build_sandbox_alone_and_its_runtime_egress_not_at_all(og, stub):
    s = stub(golden=[GOLDEN])
    og("template", "tst")
    allows = [c for c in s.calls if c[:3] == ["policy", "allow", "network"]]
    assert not any("example.com" in a or "example.org" in a for c in allows if c[3] != "--sandbox" for a in c)
    assert not any("api.example.com" in a for c in s.calls for a in c)


def test_the_recipe_goes_in_as_a_file_byte_for_byte(og, stub):
    s = stub(golden=[GOLDEN])
    og("template", "tst")
    i = next(i for i, c in enumerate(s.calls) if "cat > /tmp/ogun-recipe.sh" in " ".join(c))
    assert s.stdin[i] == TST


def test_the_scrub_removes_the_base_paths_and_the_recipes_own_and_fails_if_one_survives(og, stub):
    s = stub(golden=[GOLDEN])
    og("template", "tst")
    line = next(" ".join(c) for c in s.calls if "rm -rf /tmp/ogun-recipe.sh" in " ".join(c))
    for p in ("~/.aws/sso", "~/.claude/.credentials.json", "~/.bash_history", "~/.cache/tst", "still there"):
        assert p in line


def test_the_declared_egress_is_printed(og, stub):
    stub(golden=[GOLDEN])
    out = "".join(og("template", "tst")[1:])
    assert "egress the recipe declares" in out and "example.com,*.example.org" in out


@pytest.mark.parametrize("knob", ["recipe_fail", "stop_fail"])
def test_a_failing_recipe_or_a_sandbox_that_wont_stop_saves_nothing_and_still_removes_it(og, stub, recipes, knob):
    s = stub(golden=[GOLDEN], **{knob: True})
    code, out, err = og("template", "tst")
    assert code == 1
    assert not [c for c in s.calls if c[:2] == ["template", "save"]]
    assert ["rm", GOLDEN, "--force"] in s.calls
    assert not (recipes / ".local/state/sbx-golden-tst").exists()
    if knob == "recipe_fail":
        assert not any("rm -rf /tmp/ogun-recipe.sh" in " ".join(c) for c in s.calls)
        assert "og template: 'tst' failed — nothing saved" in out + err


def test_a_baseline_env_og_cant_read_stops_a_build_before_anything_is_made(og, stub, recipes):
    (recipes / ".config/ogun/baseline.env").write_text("SBX_BASELINE_DOMAINS=unquoted\n")
    s = stub(golden=[GOLDEN])
    code, out, err = og("template", "tst")
    assert code == 1 and "baseline.env" in out + err
    assert not [c for c in s.calls if c[:2] == ["env", "create"]]
    assert not (recipes / ".local/state/sbx-golden-tst").exists()


def test_a_build_stopped_by_an_error_still_removes_its_sandbox_and_workspace(og, stub, recipes, monkeypatch):
    def stops(_sb):
        raise settings.Unreadable("a step og can't go on from")
    monkeypatch.setattr(template.base, "tools", stops)
    s = stub(golden=[GOLDEN])
    code, out, err = og("template", "tst")
    assert code == 1 and "a step og can't go on from" in out + err
    assert ["rm", GOLDEN, "--force"] in s.calls
    assert not (recipes / ".local/state/sbx-golden-tst").exists()


def test_a_leftover_from_an_earlier_build_is_removed_first_and_says_so(og, stub):
    s = stub(golden=[GOLDEN], leftover=GOLDEN)
    code, out, _ = og("template", "tst")
    assert code == 0 and "removing golden-tst, left over from an earlier build" in out
    assert order(s.calls, "rm golden-tst", "env create")


def test_a_leftover_listed_through_a_symlink_or_a_doubled_slash_is_still_the_builds_own(og, stub, recipes, tmp_path):
    (tmp_path / "alias").mkdir()
    (tmp_path / "alias/home").symlink_to(recipes)
    s = stub(golden=[GOLDEN], leftover=GOLDEN, leftover_ws=f"{tmp_path}/alias/home//.local/state/sbx-golden-tst")
    assert og("template", "tst")[0] == 0
    assert order(s.calls, "rm golden-tst", "env create")


def test_a_leftover_that_cant_be_removed_stops_the_build_before_anything_is_made(og, stub, recipes):
    s = stub(golden=[GOLDEN], leftover=GOLDEN, rm_fail=True)
    assert og("template", "tst")[0] == 1
    assert not [c for c in s.calls if c[:2] == ["env", "create"]]
    assert not (recipes / ".local/state/sbx-golden-tst").exists()


def test_a_golden_sandbox_someone_made_by_hand_is_never_removed(og, stub, recipes):
    mine = recipes / "Projects/mine"
    s = stub(leftover=GOLDEN, leftover_ws=str(mine))
    code, out, err = og("template", "tst")
    assert code == 1
    assert f"a sandbox named golden-tst exists, and it isn't a build's (its workspace: {mine})" in out + err
    assert not [c for c in s.calls if c[:1] in (["rm"], ["env"])]


def test_one_made_by_hand_after_the_check_but_before_the_create_is_left_alone(og, stub, recipes):
    s = stub(golden=[GOLDEN], race_ws=str(recipes / "Projects/mine"))
    assert og("template", "tst")[0] == 1
    assert [c for c in s.calls if c[:2] == ["env", "create"]]
    assert not [c for c in s.calls if c[:1] == ["rm"]]


@pytest.fixture
def lock_held(recipes):
    """Another process holds tst's build lock."""
    import subprocess
    import sys
    (recipes / ".local/state").mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen([sys.executable, "-c", 'import fcntl, sys, time; f = open(sys.argv[1], "a"); '
                          'fcntl.flock(f, fcntl.LOCK_EX); print("held", flush=True); time.sleep(30)',
                          str(recipes / ".local/state/sbx-golden-tst.lock")], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "held"
    yield
    p.kill()
    p.wait()


def test_a_build_while_another_of_the_same_recipe_runs_is_refused_and_touches_no_sandbox(og, stub, lock_held):
    s = stub(golden=[GOLDEN])
    code, out, err = og("template", "tst")
    assert code == 1 and "a build of 'tst' is already running" in out + err
    assert not [c for c in s.calls if c[:1] in (["rm"], ["env"], ["stop"]) or c[:2] == ["template", "save"]]


def test_the_lock_goes_when_a_build_ends_and_no_sbx_call_inherits_it(og, stub, recipes):
    import fcntl
    s = stub(golden=[GOLDEN])
    assert og("template", "tst")[0] == 0
    assert og("template", "tst")[0] == 0   # two in a row both run
    with open(recipes / ".local/state/sbx-golden-tst.lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)   # and this process holds nothing afterwards
    assert s.calls and not any(x.endswith("sbx-golden-tst.lock") for fds in s.fds for x in fds)


@pytest.mark.parametrize("header", ["# egress: evil.com;rm", "# runtime-egress: ok.com $(x)"])
def test_a_recipe_declaring_egress_that_isnt_a_domain_builds_nothing(og, stub, recipes, header):
    (recipes / ".config/ogun/templates/bad.sh").write_text(f"#!/bin/bash\n{header}\ntrue\n")
    s = stub()
    assert og("template", "bad")[0] == 1
    assert not [c for c in s.calls if c[:2] == ["env", "create"]]


def test_no_name_builds_every_recipe_each_in_its_own_sandbox_and_image(og, stub):
    s = stub(golden=["golden-home", "golden-orders", GOLDEN, "golden-work"])
    assert og("template")[0] == 0
    assert order(s.calls, "template save golden-home ogun-home", "template save golden-orders ogun-orders",
                 "template save golden-tst ogun-tst", "template save golden-work ogun-work")


def test_an_unknown_recipe_is_refused_before_anything_is_created(og, stub):
    s = stub()
    assert og("template", "nope")[0] == 1
    assert not [c for c in s.calls if c[:2] == ["env", "create"]]


def test_v_shows_each_sbx_call_on_stderr_and_changes_nothing_else(og, stub):
    stub(golden=[GOLDEN])
    plain = og("template", "tst")[1]
    stub(golden=[GOLDEN])
    code, out, err = og("-v", "template", "tst")
    assert code == 0 and out == plain
    assert "$ sbx template save golden-tst ogun-tst" in err and "$ sbx env create" in err


def test_a_finished_build_says_what_it_built_and_og_log_records_it(og, stub, recipes):
    stub(golden=[GOLDEN])
    assert "built ogun-tst:latest" in "".join(og("template", "tst")[1:])
    assert "built the template ogun-tst:latest" in (paths.state_dir() / "og.log").read_text()


# ── OpenAPPA in a template ──

def test_a_recipe_with_appa_on_installs_openappa_before_the_image_is_saved(og, stub, recipes):
    with_header(recipes / ".config/ogun/templates/tst.sh", "# appa: on")
    s = stub(golden=[GOLDEN])
    assert og("template", "tst")[0] == 0
    assert ["policy", "allow", "network", "--sandbox", GOLDEN, "release-assets.githubusercontent.com"] in s.calls
    assert order(s.calls, "releases/download", "stop golden-tst")


def test_any_other_appa_value_stops_the_build_before_anything_is_made(og, stub, recipes):
    with_header(recipes / ".config/ogun/templates/tst.sh", "# appa: maybe")
    s = stub(golden=[GOLDEN])
    code, out, err = og("template", "tst")
    assert code == 1 and "declares appa 'maybe' — the only value is on" in out + err
    assert not [c for c in s.calls if c[:2] == ["env", "create"]]


def test_a_recipe_without_it_builds_with_no_openappa_at_all(og, stub):
    s = stub(golden=[GOLDEN])
    og("template", "tst")
    assert not any("release-assets" in a or "releases/download" in a for c in s.calls for a in c)
