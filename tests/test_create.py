"""create: the sign-in check. sbx signed out of Docker fails a create halfway, with
a 401 and an `sbx env rm` hint that doesn't apply, so a create asks first and
stops with `sbx login` as the line to run. Only that answer stops it: any other
failure is left to the steps that already report it."""

import io
import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import use_profile, with_header
from ogun.core import records, settings
from ogun.exchange import folders
from ogun.sandbox import choose, create, facts, init

SIGNED_OUT = ("error: failed to check if sandbox exists: lookup runtime: request failed: 401 Unauthorized: user is not "
              "authenticated to Docker: secret not found not signed in to Docker; remove provisioned secrets for this environment")


def ls(fakes, err="", code=0):
    fakes.sbx.answer(["ls"], stdout="SANDBOX  AGENT  STATUS\n", stderr=err, code=code)


def test_signed_in_passes_silently(fakes, capfd):
    ls(fakes)
    assert create.signed_in()
    assert "".join(capfd.readouterr()) == ""


def test_signed_out_refuses_with_sbx_login_as_the_line_to_run(fakes, capfd):
    ls(fakes, SIGNED_OUT, 1)
    assert not create.signed_in()
    out = "".join(capfd.readouterr())
    assert "not signed in to Docker" in out and "\n" in out.split("not signed in to Docker", 1)[1]
    assert "sbx login" in out.split("not signed in to Docker", 1)[1]


def test_a_bare_401_counts_as_signed_out_too(fakes):
    ls(fakes, "request failed: 401 Unauthorized", 1)
    assert not create.signed_in()


def test_any_other_sbx_ls_failure_isnt_this_checks_to_report(fakes, capfd):
    ls(fakes, "cannot connect to the sandbox daemon", 1)
    assert create.signed_in()
    assert "".join(capfd.readouterr()) == ""


def test_a_create_stops_at_the_check_before_writing_anything(fakes, home, capfd):
    ls(fakes, SIGNED_OUT, 1)
    d = home / "Projects/personal/demo"
    d.mkdir(parents=True)
    assert not create.create("demo", "personal", str(d))
    out = "".join(capfd.readouterr())
    assert "sbx login" in out and "wrote" not in out
    assert not (d / ".sbxenv.yaml").exists()


def test_a_create_that_could_not_name_its_token_item_refuses_before_anything_is_made(recipes, stub, capfd):
    # no profile and no token_name: the token step at the end could name no item,
    # so the sandbox would be made, set up, and left without a token
    ok, d, calls = made(recipes, stub, None, name="no-name")
    out = "".join(capfd.readouterr())
    assert not ok and not any(c[:2] == ["env", "create"] for c in calls) and not (d / ".sbxenv.yaml").exists()
    assert "token_name" in out and "profile" in out and "nothing was made" in out


def test_but_a_create_given_its_item_needs_no_name_for_it(recipes, stub):
    ok, _, calls = made(recipes, stub, None, name="by-item", item="github-pat-personal-home")
    assert ok and any(c[:2] == ["env", "create"] for c in calls)


@pytest.fixture(autouse=True)
def _no_ssh(home, monkeypatch):
    monkeypatch.setattr("ogun.secrets.sshkeys.ssh_dir", lambda: home / "ssh")


# ── which template a create picks: the repo's, then this Mac's, then sbx's default ──

def pick(recipes, stub, machine, rel, *images, capfd):
    use_profile(recipes, machine)
    stub(*images)
    capfd.readouterr()
    img, dec = choose.choose_template(str(recipes / "Projects" / rel))
    return img, dec, capfd.readouterr().err


def test_og_v_shows_the_sbx_call_the_template_choice_makes(recipes, stub, capfd, monkeypatch):
    monkeypatch.setenv("OG_VERBOSE", "1")
    assert "$ sbx template ls" in pick(recipes, stub, "home", "personal/plain", "ogun-home", capfd=capfd)[2]


def test_a_repo_entrys_template_wins_and_the_choice_is_said_with_its_reason(recipes, stub, capfd):
    img, _, err = pick(recipes, stub, "home", "initech/printer", "ogun-work", "ogun-home", capfd=capfd)
    assert img == "ogun-work:latest"
    assert "template ogun-work:latest ('work', from the registry.json entry 'printer')" in err


def test_not_built_says_so_with_the_build_command_and_falls_through_to_the_macs(recipes, stub, capfd):
    img, _, err = pick(recipes, stub, "home", "initech/printer", "ogun-home", capfd=capfd)
    assert img == "ogun-home:latest"
    assert ("template 'work' (the registry.json entry 'printer') not built — run: og template work; "
            "trying 'home' (this Mac's profile 'home')") in err
    assert "template ogun-home:latest ('home', from this Mac's profile 'home')" in err


def test_with_no_profile_only_the_repos_template_is_tried_then_sbxs_default(recipes, stub, capfd):
    img, dec, err = pick(recipes, stub, None, "initech/printer", "ogun-home", capfd=capfd)
    assert img == "" and [p["name"] for p in dec["passed"]] == ["work"]
    assert "using the sbx default" in err and "trying ''" not in err


def test_neither_built_every_fall_through_is_said_and_sbxs_default_is_used(recipes, stub, capfd):
    img, _, err = pick(recipes, stub, "home", "initech/printer", capfd=capfd)
    assert img == ""
    assert "template 'work' (the registry.json entry 'printer') not built — run: og template work; trying 'home'" in err
    assert "template 'home' (this Mac's profile 'home') not built — run: og template home; using the sbx default" in err
    assert "template: the sbx default image" in err


def test_no_repo_template_the_one_named_after_the_machine(recipes, stub, capfd):
    img, _, err = pick(recipes, stub, "work", "personal/plain", "ogun-work", "ogun-home", capfd=capfd)
    assert img == "ogun-work:latest" and "('work', from this Mac's profile 'work')" in err


def test_a_profiles_template_not_built_is_sbxs_default_never_another_profiles(recipes, stub, capfd):
    img, _, err = pick(recipes, stub, "work", "personal/plain", "ogun-home", capfd=capfd)
    assert img == ""
    assert "template 'work' (this Mac's profile 'work') not built — run: og template work; using the sbx default" in err


def test_a_repo_template_equal_to_the_profiles_is_tried_once(recipes, stub, capfd):
    assert pick(recipes, stub, "work", "initech/printer", capfd=capfd)[2].count("template 'work'") == 1


@pytest.mark.parametrize(("images", "says"), [
    (["desk"], ""),                                                  # an image no recipe makes, whatever its name
    (["ogun-work-old"], "template 'work' (this Mac's profile 'work') not built"),   # only starts with the template's name
])
def test_an_image_that_isnt_a_recipes_is_never_picked(recipes, stub, capfd, images, says):
    img, _, err = pick(recipes, stub, "work" if says else "home", "personal/plain", *images, capfd=capfd)
    assert img == "" and says in err


def test_a_repo_template_with_no_recipe_says_so_and_falls_through(recipes, stub, capfd):
    img, _, err = pick(recipes, stub, "home", "personal/odd", "ogun-home", capfd=capfd)
    assert img == "ogun-home:latest"
    assert "template 'nope' (the registry.json entry 'odd') has no recipe (~/.config/ogun/templates/nope.sh)" in err


@pytest.mark.parametrize(("rel", "says"), [
    ("personal/printer", "for owner 'initech', but this sandbox's owner is 'personal'"),   # basename collision
    ("personal/loose", "declares no `owner`"),
    ("initech/printer/sub/printer", "not the repo it describes"),
], ids=["another owner", "no owner", "a subfolder named like it"])
def test_the_owner_gate_holds_for_the_template_key(recipes, stub, capfd, rel, says):
    img, _, err = pick(recipes, stub, "home", rel, "ogun-work", "ogun-home", capfd=capfd)
    assert img == "ogun-home:latest" and says in err


# ── a team's plugin: mounted under the profile that names it, not another, skipped when not cloned ──

@pytest.fixture
def clone(recipes):
    c = recipes / "Projects/initech/plugins"
    (c / ".claude-plugin").mkdir(parents=True)
    (c / ".claude-plugin/marketplace.json").write_text('{"name":"initech-kit"}')
    return c


def mounts_for(recipes, machine, rel):
    use_profile(recipes, machine)
    return choose.marketplaces(str(recipes / "Projects" / rel))


def test_a_marketplace_the_registry_asks_for_that_marketplaces_json_lacks_names_the_file_og_read(recipes, capfd):
    (recipes / ".config/ogun/marketplaces.json").write_text('{"marketplaces": {}}')
    assert mounts_for(recipes, "home", "initech/printer") == []
    assert "'initech-kit' (registry entry 'printer'): not defined in ~/.config/ogun/marketplaces.json; skipped" in capfd.readouterr().err


def test_a_profile_given_a_marketplace_without_its_clone_warns_and_mounts_nothing(recipes, capfd):
    assert mounts_for(recipes, "work", "personal/plain") == []
    assert ("marketplace 'initech-kit' (profile 'work'): no clone at ~/Projects/initech/plugins — not mounted"
            in capfd.readouterr().err)


def test_the_profile_a_marketplace_names_mounts_its_clone_another_doesnt(recipes, clone):
    assert mounts_for(recipes, "work", "personal/plain") == [str(clone)]
    assert mounts_for(recipes, "home", "personal/plain") == []


def test_a_profile_named_unlike_any_template_still_gets_its_marketplaces(recipes, clone):
    # a dot is fine in a profile's name, never in a template's: only the template is passed over
    (recipes / ".config/ogun").mkdir(parents=True, exist_ok=True)
    (recipes / ".config/ogun/config.toml").write_text('[profiles."team.dev"]\n')
    (recipes / ".config/ogun/marketplaces.json").write_text(
        '{"marketplaces": {"initech-kit": {"path": "~/Projects/initech/plugins", "profiles": ["team.dev"]}}}')
    assert mounts_for(recipes, "team.dev", "personal/plain") == [str(clone)]


def test_unless_the_repos_entry_asks_for_it_behind_the_owner_gate(recipes, clone, capfd):
    assert mounts_for(recipes, "home", "initech/printer") == [str(clone)]
    capfd.readouterr()
    assert mounts_for(recipes, "home", "personal/printer") == []
    assert "basename collision" in capfd.readouterr().err


# ── a create, end to end against the stub ──

def made(recipes, stub, machine, rel="personal/plain", name="", appa=False, item="", **knobs):
    """A create of <rel>, a repo with a commit; its exit, what it said, sbx's calls."""
    use_profile(recipes, machine)
    d = recipes / "Projects" / rel
    if not (d / ".git").exists():
        subprocess.run(["git", "init", "-q", str(d)], check=True)
        subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                        "commit", "-q", "--allow-empty", "-m", "i"], check=True)
    s = stub(*knobs.pop("images", ("ogun-work", "ogun-home")), **knobs)
    n = len(s.calls)
    ok = create.create(name or f"e2e-{machine}", "personal", str(d), "session", item, appa)
    return ok, d, s.calls[n:]


def yaml(d) -> list[str]:
    return (d / ".sbxenv.yaml").read_text().splitlines()


def read_only(lines, path) -> bool:
    i = lines.index(f'  - path: "{path}"')
    return lines[i + 1] == "    readOnly: true"


def test_a_create_under_the_named_profile_mounts_the_clone_read_only_and_names_its_template(recipes, stub, clone, capfd):
    ok, d, _ = made(recipes, stub, "work")
    assert ok and read_only(yaml(d), clone) and "  template: ogun-work:latest" in yaml(d)


def test_a_create_under_another_profile_mounts_no_clone_and_names_its_own_template(recipes, stub, clone):
    ok, d, _ = made(recipes, stub, "home")
    assert ok and not any(str(clone) in x for x in yaml(d)) and "  template: ogun-home:latest" in yaml(d)


def test_a_create_under_the_named_profile_without_the_clone_warns_mounts_nothing_and_still_succeeds(recipes, stub, capfd):
    ok, d, _ = made(recipes, stub, "work")
    assert ok and "no clone at" in "".join(capfd.readouterr())
    assert not any("initech/plugins" in x for x in yaml(d))


def test_a_workspace_path_is_quoted_in_the_environment_file(recipes, stub):
    ok, d, _ = made(recipes, stub, "home", "personal/Work #2: y", name="e2e-q", images=("ogun-home",))
    assert ok and f'  path: "{d}"' in yaml(d)


def test_host_read_only_mounts_a_glob_mounts_every_match_a_missing_entry_is_skipped(recipes, stub, monkeypatch):
    f = recipes / "hfonts"
    for x in ("user", "assets/Font8", "assets/Font9"):
        (f / x).mkdir(parents=True)
    monkeypatch.setenv("OG_HOST_RO_MOUNTS", f"{f}/user:{f}/assets/Font*:{f}/absent")
    ok, d, _ = made(recipes, stub, "home")
    lines = yaml(d)
    assert ok and all(read_only(lines, f / x) for x in ("user", "assets/Font8", "assets/Font9"))
    assert not any("absent" in x or "Font*" in x for x in lines)


# ── the create's record: the template decision, the mounts, the runtime egress ──

def rec(name) -> dict:
    return records.read_record(name)


def tmpl(name) -> dict:
    t = rec(name)["template"]
    return {k: t[k] for k in ("name", "image", "reason", "project", "profile", "passed")}


def test_a_create_records_its_template_and_why_where_no_sandbox_reaches_0600_0700(recipes, stub):
    ok, d, _ = made(recipes, stub, "work", name="rec-desk")
    assert ok
    assert tmpl("rec-desk") == {"name": "work", "image": "ogun-work:latest", "reason": "profile", "project": "",
                                "profile": "work", "passed": []}
    r = rec("rec-desk")
    assert (r["sandbox"], r["kind"], r["workspace"]) == ("rec-desk", "session", str(d))
    f = records.record_file("rec-desk")
    assert f.stat().st_mode & 0o777 == 0o600 and f.parent.stat().st_mode & 0o777 == 0o700


def test_and_every_mount_its_sbxenv_named_in_order_read_only_or_not(recipes, stub):
    ok, d, _ = made(recipes, stub, "work", name="rec-desk")
    assert ok
    m = rec("rec-desk")["mounts"]
    cfg, out = str(recipes / "agent-config"), str(recipes / "exchange/boxes/rec-desk/out")
    assert next(x for x in m if x["path"] == cfg)["read_only"] is True   # a host mount, as host_ro_mounts names it
    assert next(x for x in m if x["path"] == out)["read_only"] is False
    assert len(m) == sum(x.startswith("  - path: ") for x in yaml(d))


def test_its_templates_runtime_egress_is_allowed_for_it_alone_once_it_exists_and_recorded(recipes, stub, capfd):
    ok, d, calls = made(recipes, stub, "work", name="rec-desk")
    assert ok
    joined = [" ".join(c) for c in calls]
    create_at = next(i for i, c in enumerate(joined) if c.startswith(f"env create {d}/.sbxenv.yaml"))
    allow_at = joined.index("policy allow network --sandbox rec-desk index.crates.io,static.crates.io,*.rust-lang.org")
    assert create_at < allow_at
    assert rec("rec-desk")["egress"] == ["index.crates.io", "static.crates.io", "*.rust-lang.org"]
    assert "runtime egress of its template (rec-desk only)" in "".join(capfd.readouterr())
    assert [f"{d}/.sbxenv.yaml", "--force"] == next(c[2:] for c in calls if c[:2] == ["env", "create"])


def test_a_repo_entrys_template_records_the_project_and_a_fall_through_what_was_passed(recipes, stub):
    assert made(recipes, stub, "home", "initech/printer", name="rec-tile")[0]
    assert tmpl("rec-tile") == {"name": "work", "image": "ogun-work:latest", "reason": "project", "project": "printer",
                                "profile": "home", "passed": []}
    assert made(recipes, stub, "home", "initech/printer", name="rec-fall", images=("ogun-home",))[0]
    assert tmpl("rec-fall") == {"name": "home", "image": "ogun-home:latest", "reason": "profile", "project": "",
                                "profile": "home", "passed": [{"name": "work", "reason": "project", "why": "not built"}]}


def test_sbxs_default_is_recorded_as_such_with_every_template_passed_over(recipes, stub):
    ok, d, calls = made(recipes, stub, "work", "personal/odd", name="rec-def", images=())
    assert ok and tmpl("rec-def") == {"name": "", "image": "", "reason": "default", "project": "", "profile": "work",
                                      "passed": [{"name": "nope", "reason": "project", "why": "no recipe"},
                                                 {"name": "work", "reason": "profile", "why": "not built"}]}
    assert not any(x.lstrip().startswith("template:") for x in yaml(d))
    assert rec("rec-def")["egress"] == [] and not any(c[:4] == ["policy", "allow", "network", "--sandbox"] for c in calls)


def test_a_template_with_no_runtime_egress_allows_and_records_none(recipes, stub):
    ok, _, calls = made(recipes, stub, "home", name="rec-per", images=("ogun-home",))
    assert ok and rec("rec-per")["egress"] == []
    assert not any(c[:4] == ["policy", "allow", "network", "--sandbox"] and "rec-per" in c for c in calls)


def test_a_runtime_egress_sbx_refuses_is_warned_with_the_repair_recorded_as_none_and_the_create_goes_on(recipes, stub, capfd):
    ok, _, _ = made(recipes, stub, "work", name="rec-pol", images=("ogun-work",), policy_fail=True)
    out = "".join(capfd.readouterr())
    assert ok and rec("rec-pol")["egress"] == []
    assert "could not allow it; by hand:" in out and any(x.strip().startswith("og allow rec-pol index.crates.io static.crates.io *.rust-lang.org")
                                                         for x in out.splitlines())


def test_a_runtime_egress_value_off_a_domains_shape_allows_none_and_says_so(recipes, stub, capfd):
    f = recipes / ".config/ogun/templates/work.sh"
    f.write_text(re.sub(r"(?m)^# runtime-egress: .*$", "# runtime-egress: index.crates.io evil;rm", f.read_text()))
    ok, _, calls = made(recipes, stub, "work", name="rec-bad", images=("ogun-work",))
    assert ok and rec("rec-bad")["egress"] == []
    assert not any(c[:4] == ["policy", "allow", "network", "--sandbox"] for c in calls)
    assert "template 'work' declares runtime egress 'evil;rm' — not a domain; none allowed" in "".join(capfd.readouterr())


def test_a_create_that_fails_records_nothing_leaves_no_decision_file_and_says_what_sbx_said(recipes, stub, capfd, tmp_path,
                                                                                           monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    ok, _, _ = made(recipes, stub, "work", name="rec-fail", images=("ogun-work",), create_fail=True)
    out = "".join(capfd.readouterr())
    assert not ok and rec("rec-fail") is None and list((tmp_path / "tmp").iterdir()) == []
    assert "sbx couldn't create 'rec-fail'" in out and "disk full" in out and "needs your approval" in out


def test_a_baseline_og_cant_read_stops_a_create_before_anything_is_made(recipes, stub):
    # read after the sandbox exists, it would leave one half set up
    s = stub("ogun-work", "ogun-home")
    (recipes / ".config/ogun/config.toml").write_text('[baseline]\ndomains = "unlisted"\n')
    with pytest.raises(settings.Unreadable, match=r"baseline\.domains"):
        made(recipes, stub, "work", name="bl-bad")
    c = recipes / ".config/ogun/config.toml"   # what's checked below reads settings too
    c.write_text(c.read_text().replace('[baseline]\ndomains = "unlisted"\n', ""))
    assert not [c for c in s.calls if c[:2] == ["env", "create"]]
    assert rec("bl-bad") is None and not folders.box("bl-bad")


def test_a_create_that_works_shows_ogs_list_of_its_mounts_not_sbxs_plan_unless_vv(recipes, stub, capfd, monkeypatch):
    made(recipes, stub, "work", name="rec-plan", images=("ogun-work",))
    out = "".join(capfd.readouterr())
    assert "needs your approval" not in out and "folders mounted besides the workspace" in out
    assert f"{recipes / 'agent-config'} (read-only)" in out
    monkeypatch.setenv("OG_VERBOSE", "2")
    made(recipes, stub, "work", name="rec-plan2", images=("ogun-work",))
    assert "needs your approval" in "".join(capfd.readouterr())


def test_a_new_sandboxs_name_is_added_to_the_ones_tab_completion_offers(recipes, stub):
    from ogun.core import paths
    f = paths.state_dir() / "sandbox-names"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("other\n")
    assert made(recipes, stub, "work", name="rec-named", images=("ogun-work",))[0]
    assert f.read_text().splitlines()[-1] == "rec-named"


def test_the_mounts_recorded_are_this_creates_though_another_create_rewrites_the_file_meanwhile(recipes, stub, monkeypatch):
    from ogun.core import sbx
    real = sbx.run

    def clobbering(*args, **kw):
        p = real(*args, **kw)
        if args[:2] == ("env", "create"):   # another create from the same workspace writes its own file
            Path(args[2]).write_text('schemaVersion: "1"\nname: other\nadditionalWorkspaces:\n  - path: /clobbered/by-other\n')
        return p

    monkeypatch.setattr(sbx, "run", clobbering)
    assert made(recipes, stub, "work", name="rec-clob", images=("ogun-work",))[0]
    m = [x["path"] for x in rec("rec-clob")["mounts"]]
    assert "/clobbered/by-other" not in m and str(recipes / "exchange/boxes/rec-clob/out") in m


def test_a_create_that_stops_early_makes_no_sandbox_and_no_record(recipes, stub, monkeypatch):
    (recipes / "exchange/boxes").write_text("")   # its exchange folders can't be made
    ok, _, calls = made(recipes, stub, "work", name="rec-early", images=("ogun-work",))
    assert not ok and not [c for c in calls if c[:2] == ["env", "create"]] and rec("rec-early") is None
    (recipes / "exchange/boxes").unlink()
    monkeypatch.setattr("ogun.sandbox.create.skills_store", lambda: Path("/dev/null/store"))   # the skills mirror can't write its store
    ok, _, calls = made(recipes, stub, "work", name="rec-early2", images=("ogun-work",))
    assert not ok and not [c for c in calls if c[:2] == ["env", "create"]] and rec("rec-early2") is None


def test_a_create_with_no_copy_of_its_sbxenv_writes_no_record_and_says_that(recipes, capfd):
    assert not facts.record("nosnap", "session", str(recipes / "Projects/personal/plain"), None, "", [""])
    err = "".join(capfd.readouterr())
    assert "no copy of its .sbxenv.yaml" in err and "another sandbox" not in err
    assert records.read_record("nosnap") is None


def test_og_rm_removes_the_record_with_the_sandbox_and_only_its_own(recipes, stub):
    from ogun.sandbox import remove
    assert made(recipes, stub, "work", name="rec-desk", images=("ogun-work",))[0]
    assert made(recipes, stub, "home", "initech/printer", name="rec-tile")[0]
    assert remove.rm_clean("rec-desk", True)
    assert rec("rec-desk") is None and rec("rec-tile") is not None


# ── a folder that isn't a repo: offered one, on a yes at a terminal only ──

@pytest.fixture
def ask(recipes, tmp_path, monkeypatch):
    """offer_init with this answer typed at the terminal (None: no terminal); a git
    identity for the first commit."""
    for k in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{k}_NAME", "t")
        monkeypatch.setenv(f"GIT_{k}_EMAIL", "t@t")

    def at(d, answer):
        if answer is None:   # stdin a pipe that would say yes, and no menu: never asked
            monkeypatch.delenv("OG_MENU_IN", raising=False)
            monkeypatch.setattr(sys, "stdin", io.StringIO("y\n"))
        else:
            (tmp_path / "menu").write_text(answer + "\n")
            monkeypatch.setenv("OG_MENU_IN", str(tmp_path / "menu"))
        return init.offer_init(str(d))

    return at


def commits(d) -> int:
    return int(subprocess.run(["git", "-C", str(d), "rev-list", "--count", "HEAD"], capture_output=True, text=True).stdout or 0)


def test_on_a_yes_it_becomes_a_repo_with_one_empty_commit_its_files_left_uncommitted(recipes, ask, capfd):
    d = recipes / "Projects/personal/newproj"
    d.mkdir()
    (d / "notes.md").write_text("n\n")
    assert ask(d, "y")
    assert commits(d) == 1
    assert subprocess.run(["git", "-C", str(d), "ls-files"], capture_output=True, text=True).stdout == ""
    assert "readable inside at /run/sandbox/source" in "".join(capfd.readouterr())


def test_no_or_no_terminal_is_refused_and_the_folder_left_as_it_was(recipes, ask, capfd):
    d = recipes / "Projects/personal/noproj"
    d.mkdir()
    assert not ask(d, "n") and not (d / ".git").exists() and "nothing created" in "".join(capfd.readouterr())
    assert not ask(d, None) and not (d / ".git").exists()
    assert "do it yourself (git init, then a first commit)" in "".join(capfd.readouterr())


@pytest.mark.parametrize("where", ["Projects", "Projects/personal", "", ".secrets/x", "exchange/inbox", ".."],
                         ids=["Projects root", "an owner's folder", "home", "a hidden home folder", "the exchange", "above home"])
def test_never_in_a_folder_too_broad_to_be_a_workspace(recipes, ask, capfd, where):
    d = (recipes / where).resolve() if where else recipes
    d.mkdir(parents=True, exist_ok=True)
    assert not ask(d, "y") and not (d / ".git").exists()
    assert "can't be a sandbox's workspace" in "".join(capfd.readouterr())


@pytest.mark.parametrize(("where", "why"), [
    ("Work", "every project"), ("Code", "every project"), ("", "your whole home"),
    ("Code/umbrella", "an owner's folder"), ("Work/api", ""), ("Code/umbrella/shop", ""),
    ("dev", "every project"), ("dev/More/umbrella", "an owner's folder"), ("dev/More/umbrella/shop", ""),
])
def test_every_project_folder_is_too_broad_and_so_is_a_per_owner_ones_owner_folder(recipes, monkeypatch, where, why):
    # Work: fixed to acme, so a folder right in it is one repo, not an owner's folder;
    # dev holds the second per-owner folder
    monkeypatch.setenv("OG_PROJECTS", f"{recipes}/Code:{recipes}/Work=acme:{recipes}/dev/More")
    d = recipes / where
    d.mkdir(parents=True, exist_ok=True)
    got = init.too_broad(str(d.resolve()))
    assert (why in got and got) if why else got == ""


def test_a_repo_with_a_commit_is_ready_nothing_asked(recipes, ask):
    d = recipes / "Projects/personal/committed"
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-q", "--allow-empty", "-m", "i"], check=True)
    assert ask(d, None)


def test_a_first_commit_that_fails_undoes_the_init_so_the_next_try_starts_clean(recipes, ask, capfd, monkeypatch):
    d = recipes / "Projects/personal/failproj"
    d.mkdir()
    for k, v in (("COUNT", "2"), ("KEY_0", "commit.gpgsign"), ("VALUE_0", "true"), ("KEY_1", "gpg.program"), ("VALUE_1", "false")):
        monkeypatch.setenv(f"GIT_CONFIG_{k}", v)
    assert not ask(d, "y") and not (d / ".git").exists() and "the init was undone" in "".join(capfd.readouterr())
    monkeypatch.delenv("GIT_CONFIG_COUNT")
    assert ask(d, "y") and commits(d) == 1


def test_a_repo_with_no_commit_yet_is_offered_the_empty_first_commit_and_what_was_staged_stays(recipes, ask):
    d = recipes / "Projects/personal/staged"
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    assert not ask(d, "n")
    (d / "w").write_text("w\n")
    subprocess.run(["git", "-C", str(d), "add", "w"], check=True)
    assert ask(d, "y") and commits(d) == 1
    assert subprocess.run(["git", "-C", str(d), "ls-tree", "-r", "HEAD"], capture_output=True, text=True).stdout == ""
    assert subprocess.run(["git", "-C", str(d), "status", "--porcelain"], capture_output=True, text=True).stdout == "A  w\n"


def test_a_repo_at_home_hands_out_neither_its_aws_folder_nor_a_folder_under_it(recipes, ask, capfd, monkeypatch, tmp_path):
    h = tmp_path / "home2"
    for d in (".aws", "stuff/proj", ".notes"):
        (h / d).mkdir(parents=True)
    for r in (h, h / ".notes"):
        subprocess.run(["git", "init", "-q", str(r)], check=True)
        subprocess.run(["git", "-C", str(r), "commit", "-q", "--allow-empty", "-m", "i"], check=True)
    monkeypatch.setenv("HOME", str(h))
    for d in (h / ".aws", h / "stuff/proj"):
        assert not ask(d, None)
        out = "".join(capfd.readouterr())
        assert f"in the repo at {h}: it holds your whole home" in out or "it is in ~/.aws" in out
    assert ask(h / ".notes", None)   # a hidden folder with a repo of its own is fine


# ── OpenAPPA at create: installed only where asked, the sandbox removed when it can't be ──

def appa_v() -> str:
    from ogun.sandbox import appa
    return appa.lock("version")


def appa_made(recipes, stub, name, appa=False, rel="personal/plain", **knobs):
    return made(recipes, stub, "home", rel, name=name, appa=appa, images=("ogun-home",), **knobs)


def has(calls, text) -> bool:
    return any(text in " ".join(c) for c in calls)


@pytest.mark.parametrize(("line", "want"), [("# appa: on", (0, "on")), ("", (1, "")), ("# appa: yes", (2, "yes")),
                                            ("# appa: on off", (2, "on off"))])
def test_a_recipes_header_says_whether_it_asks_for_appa(recipes, line, want):
    recipe = recipes / ".config/ogun/templates/home.sh"
    if line:
        with_header(recipe, line)
    assert create.template_appa(recipe) == want


def test_without_appa_a_create_downloads_allows_and_records_nothing_of_it(recipes, stub):
    ok, _, calls = appa_made(recipes, stub, "ap-off")
    assert ok and not has(calls, "release-assets") and not has(calls, "releases/download")
    assert "appa" not in rec("ap-off")


def test_appa_the_release_host_for_it_alone_the_pinned_install_activation_and_the_record(recipes, stub):
    ok, d, calls = appa_made(recipes, stub, "ap-on", appa=True)
    assert ok
    assert ["policy", "allow", "network", "--sandbox", "ap-on", "release-assets.githubusercontent.com"] in calls
    assert has(calls, "releases/download") and has(calls, f"_ {appa_v()} ")
    assert rec("ap-on")["appa"]["version"] == appa_v()
    assert not [c for c in calls if c[:1] == ["rm"]]
    assert has(calls, f"activate.sh {appa_v()} {d}")


@pytest.mark.parametrize(("knob", "says"), [("appa_fail", "could not be installed in ap-x"),
                                            ("activate_fail", "OpenAPPA couldn't be turned on in 'ap-x'")])
def test_an_install_or_activation_that_fails_removes_the_new_sandbox_and_stops(recipes, stub, capfd, knob, says):
    ok, _, calls = appa_made(recipes, stub, "ap-x", appa=True, **{knob: True})
    assert not ok and [c for c in calls if c[:2] == ["rm", "ap-x"]]
    assert rec("ap-x") is None or "appa" not in rec("ap-x")
    assert says in "".join(capfd.readouterr())


def test_activation_gets_the_workspace_and_each_read_only_related_repo(recipes, stub):
    (recipes / "Projects/personal/notes").mkdir()
    (recipes / "Projects/personal/withnotes").mkdir()
    ok, d, calls = appa_made(recipes, stub, "ap-ro", appa=True, rel="personal/withnotes")
    assert ok and has(calls, f"activate.sh {appa_v()} {d} {recipes / 'Projects/personal/notes'}")


def test_the_token_is_set_before_the_install_once_without_openappa(recipes, stub):
    ok, _, calls = appa_made(recipes, stub, "ap-tok1", appa=True)
    sets = [i for i, c in enumerate(calls) if c[:4] == ["secret", "set", "-f", "github"]]
    install = next(i for i, c in enumerate(calls) if "releases/download" in " ".join(c))
    assert ok and sets and sets[0] < install
    ok, _, calls = appa_made(recipes, stub, "ap-tok0")
    assert ok and len([c for c in calls if c[:4] == ["secret", "set", "-f", "github"]]) == 1


def test_a_token_that_cant_be_set_removes_the_new_sandbox_before_any_install(recipes, stub):
    ok, _, calls = appa_made(recipes, stub, "ap-tok1", appa=True, op_fail=True)
    assert not ok and [c for c in calls if c[:2] == ["rm", "ap-tok1"]] and not has(calls, "releases/download")


def test_a_templates_appa_on_installs_it_with_no_flag(recipes, stub):
    with_header(recipes / ".config/ogun/templates/home.sh", "# appa: on")
    ok, _, calls = appa_made(recipes, stub, "ap-tpl")
    assert ok and has(calls, "releases/download") and rec("ap-tpl")["appa"]["version"] == appa_v()


def test_any_other_appa_value_refuses_the_create_before_anything_is_made(recipes, stub, capfd):
    with_header(recipes / ".config/ogun/templates/home.sh", "# appa: yes")
    ok, _, calls = appa_made(recipes, stub, "ap-bad")
    assert not ok and not [c for c in calls if c[:2] == ["env", "create"]]
    assert "declares appa 'yes' — the only value is on" in "".join(capfd.readouterr())


def test_a_protected_create_hands_the_registrys_private_places_to_activation_shown(recipes, stub, capfd):
    (recipes / "Projects/personal/notes").mkdir()
    (recipes / "Projects/personal/archive").mkdir()
    ok, d, calls = appa_made(recipes, stub, "ap-pv", appa=True, rel="personal/archive")
    assert ok and has(calls, f"activate.sh {appa_v()} {d} --private gitlab.example.com/me/fixtures "
                             f"{recipes / 'Projects/personal/notes'}")
    assert "other private places" in "".join(capfd.readouterr())


@pytest.mark.parametrize(("origin", "private", "appa", "warned", "asked"), [
    ("https://github.com/octocat/secret.git", "true", False, True, True),
    ("git@github.com:octocat/open.git", "false", False, False, True),
    ("https://gitlab.example.com/acme/orders.git", "true", False, False, False),   # off GitHub: never asked
    ("https://github.com/octocat/secret.git", "true", True, False, False),        # made with OpenAPPA
], ids=["private on GitHub", "public", "off GitHub", "with OpenAPPA"])
def test_a_private_github_repo_made_without_openappa_gets_a_no_openappa_block(recipes, stub, capfd, origin, private,
                                                                                appa, warned, asked):
    ok, _, calls = appa_made(recipes, stub, "ap-rem", appa=appa, origin=origin, private=private)
    out = "".join(capfd.readouterr())
    assert ok and ("NO OPENAPPA ON A PRIVATE REPO" in out) == warned and has(calls, "gh api") == asked
    if warned:
        assert "octocat/secret is private" in out and re.search(r"og rm \S+, then og --appa", out)
        assert has(calls, "gh api repos/octocat/secret --jq .private")


def test_the_record_tells_a_sandbox_with_openappa_from_one_without(recipes, stub):
    assert appa_made(recipes, stub, "ap-on", appa=True)[0] and appa_made(recipes, stub, "ap-off")[0]
    assert facts.has_appa("ap-on") and not facts.has_appa("ap-off") and not facts.has_appa("nope")


# ── a create's parts, each on its own ──

@pytest.mark.parametrize(("name", "says"), [
    (".hidden", "invalid sandbox name '.hidden'"),
    ("inbox", "'inbox' is a reserved exchange name"),
    ("golden-home", "golden-home is the template build's own sandbox"),
])
def test_a_name_og_wont_make_is_refused_with_why(recipes, capfd, name, says):
    assert create.name_refused(name)
    assert says in capfd.readouterr().err


def test_a_name_another_folds_onto_is_refused(recipes, capfd):
    from ogun.exchange import folders
    assert not folders.dirs("Taken")
    assert create.name_refused("taken")
    assert "case-folds to the existing exchange dir 'Taken'" in capfd.readouterr().err


def test_a_good_name_passes_silently_and_a_repo_called_golden_something_is_one(recipes, capfd):
    assert not create.name_refused("fine") and not create.name_refused("golden-gate")
    assert capfd.readouterr().err == ""


@pytest.mark.parametrize(("decision", "want"), [
    ({"name": "orders"}, (0, "on")), ({"name": "home"}, (1, "")), ({"name": ""}, (1, "")),
    ({"name": "absent"}, (1, "")), ({"name": "../orders"}, (1, ""))])
def test_the_chosen_recipes_appa_says_on_nothing_or_what_it_said(recipes, decision, want):
    assert create.recipe_appa(decision) == want


def test_sbx_creates_it_and_tab_completion_learns_its_name(home, fakes):
    from ogun.core import paths
    (paths.state_dir() / "sandbox-names").write_text("other\n")
    assert create.env_create("mk", Path("/w/.sbxenv.yaml"))
    assert ["env", "create", "/w/.sbxenv.yaml", "--force"] in fakes.sbx.calls
    assert "mk" in (paths.state_dir() / "sandbox-names").read_text().split()


def test_a_create_sbx_refuses_signed_out_gets_the_sign_in_line(home, fakes, capfd):
    fakes.sbx.answer(["env", "create"], stderr=SIGNED_OUT, code=1)
    assert not create.env_create("mk", Path("/w/.sbxenv.yaml"))
    assert "sbx login" in capfd.readouterr().err


def test_any_other_create_failure_says_what_sbx_said(home, fakes, capfd):
    fakes.sbx.answer(["env", "create"], stderr="disk full", code=1)
    assert not create.env_create("mk", Path("/w/.sbxenv.yaml"))
    err = capfd.readouterr().err
    assert "sbx couldn't create 'mk'" in err and "disk full" in err


def test_no_runtime_egress_asks_sbx_nothing(home, fakes, monkeypatch):
    monkeypatch.setattr(choose, "runtime_egress", lambda decision: [])
    assert create.allow_runtime_egress("rt", {}) == [] and fakes.sbx.calls == []


def test_runtime_egress_is_allowed_for_the_sandbox_alone(home, fakes, monkeypatch):
    monkeypatch.setattr(choose, "runtime_egress", lambda decision: ["a.io", "b.io"])
    assert create.allow_runtime_egress("rt", {}) == ["a.io", "b.io"]
    assert fakes.sbx.calls == [["policy", "allow", "network", "--sandbox", "rt", "a.io,b.io"]]


def test_runtime_egress_sbx_refuses_is_none_with_the_repair(home, fakes, monkeypatch, capfd):
    monkeypatch.setattr(choose, "runtime_egress", lambda decision: ["a.io"])
    fakes.sbx.answer(["policy", "allow"], code=1)
    assert create.allow_runtime_egress("rt", {}) == []
    assert "og allow rt a.io" in "".join(capfd.readouterr())


@pytest.fixture
def appa_parts(monkeypatch):
    """OpenAPPA's steps for turn_on_appa, each answering as set; the removals made."""
    from ogun.sandbox import appa
    from ogun.secrets import github
    state = {"token": True, "install": True, "activate": True, "record": True, "removed": []}
    monkeypatch.setattr(github, "set_token", lambda name, org, item: state["token"])
    monkeypatch.setattr(appa, "install", lambda name: state["install"])
    monkeypatch.setattr(appa, "activate", lambda name, d, rel: state["activate"])
    monkeypatch.setattr(facts, "record_appa", lambda name: state["record"])
    monkeypatch.setattr(create, "fail_removed", lambda name: state["removed"].append(name))
    return state


def test_openappa_on_token_install_activation_and_record_nothing_removed(appa_parts):
    assert create.turn_on_appa("ap", "personal", "", "/w", []) and appa_parts["removed"] == []


@pytest.mark.parametrize("step", ["token", "install", "activate"])
def test_openappa_any_step_that_fails_removes_the_sandbox(appa_parts, step):
    appa_parts[step] = False
    assert not create.turn_on_appa("ap", "personal", "", "/w", []) and appa_parts["removed"] == ["ap"]


def test_openappa_on_but_unrecorded_is_warned_not_removed(appa_parts, capfd):
    appa_parts["record"] = False
    assert create.turn_on_appa("ap", "personal", "", "/w", []) and appa_parts["removed"] == []
    assert "the sandbox's record doesn't say so" in capfd.readouterr().out


@pytest.fixture
def after(monkeypatch):
    """Every step after sbx made the sandbox, each recording its call and
    answering as set (True unless the test says otherwise)."""
    from ogun import mcp
    from ogun.net import baseline, egress, pushrules
    from ogun.sandbox import base, session
    from ogun.secrets import github, grants, sshkeys
    said, ran = {}, []

    def step(name, mod, attr):
        monkeypatch.setattr(mod, attr, lambda *a, **k: (ran.append(name), said.get(name, True))[1])

    for name, mod, attr in [("agent_absent", sshkeys, "agent_absent"), ("mcp", mcp, "refresh"),
                            ("baseline", baseline, "baseline"), ("setup", base, "setup"),
                            ("appa", create, "turn_on_appa"), ("remotes", session, "https_remotes"),
                            ("push_repos", pushrules, "push_repos"), ("push_rules", pushrules, "push_rules"),
                            ("grants", grants, "give"), ("egress", egress, "egress_sync"),
                            ("token", github, "set_token"), ("remind", create, "appa_remind"),
                            ("removed", create, "fail_removed")]:
        step(name, mod, attr)
    return said, ran


def test_after_the_create_every_step_in_order_and_the_token_last(after):
    _said, ran = after
    assert create.finish("fin", "personal", "", "/w", [], [], False)
    assert ran == ["agent_absent", "mcp", "baseline", "setup", "remotes", "push_repos", "push_rules", "grants", "egress",
                   "token", "remind"]


def test_a_sandbox_that_still_sees_the_agent_is_removed_before_anything_runs_in_it(after):
    said, ran = after
    said["agent_absent"] = False
    assert not create.finish("fin", "personal", "", "/w", [], [], False)
    assert ran == ["agent_absent", "removed"]


def test_with_openappa_its_token_comes_from_turning_it_on_never_set_twice_nor_reminded(after):
    _said, ran = after
    assert create.finish("fin", "personal", "", "/w", [], [], True)
    assert ran.index("appa") == ran.index("setup") + 1 and "token" not in ran and "remind" not in ran


@pytest.mark.parametrize("step", ["setup", "appa", "token"])
def test_a_setup_openappa_or_token_that_fails_fails_the_create(after, step):
    said, _ran = after
    said[step] = False
    assert not create.finish("fin", "personal", "", "/w", [], [], step == "appa")


def test_no_github_remote_no_push_rules_said_once(after, capfd):
    said, ran = after
    said["push_repos"] = False
    assert create.finish("fin", "personal", "", "/w", [], [], False) and "push_rules" not in ran
    assert "GitHub pushes: none (no GitHub remote)" in capfd.readouterr().out


@pytest.mark.parametrize(("step", "warns"), [("baseline", "could not apply baseline policy"),
                                             ("push_rules", "could not allow every push rule"),
                                             ("grants", "not every secret grant was applied"),
                                             ("egress", "not every domain its registry entry lists")])
def test_a_baseline_push_rule_grant_or_egress_that_fails_is_warned_and_the_create_goes_on(after, capfd, step, warns):
    said, ran = after
    said[step] = False
    assert create.finish("fin", "personal", "", "/w", [], [], False) and ran[-1] == "remind"
    assert warns in capfd.readouterr().out


def test_a_create_asks_for_approvals_before_anything_is_made_then_gives_what_was_approved(recipes, stub, fakes,
                                                                                         monkeypatch):
    from ogun.exchange import folders
    from ogun.secrets import approval, grants
    seen = {}

    def approved(d):
        seen["made"] = [c for c in fakes.sbx.calls if c[:2] == ["env", "create"]]
        seen["box"] = folders.box("ap-ask")
        return ["the approved"]

    monkeypatch.setattr(approval, "approved", approved)
    monkeypatch.setattr(grants, "give", lambda name, given: seen.setdefault("given", given) is not None)
    ok, _, calls = made(recipes, stub, "home", name="ap-ask")
    assert ok and seen["made"] == [] and seen["box"] is None and [c for c in calls if c[:2] == ["env", "create"]]
    assert seen["given"] == ["the approved"]
