"""bare: the bare og. The sandbox name a folder gets by default, its options
(refused before anything runs when they don't parse), the owner it picks and says, a default name that is another folder's sandbox refused,
--appa on a sandbox made without it refused, and --org replacing a token."""

import subprocess

import pytest

from conftest import use_profile
from ogun.secrets import bare


@pytest.mark.parametrize(("folder", "name"), [
    ("/srv/me/.settings", "settings"),   # a leading dot would hide its exchange folders
    ("/x/-my repo!", "myrepo"),            # a leading dash goes, and characters a name can't hold
    ("/x/...", ""),                        # nothing usable gives nothing, not a bad name
])
def test_a_folders_default_sandbox_name(folder, name):
    assert bare.dir_name(folder) == name


# ── the bare og: its options, the owner it picks, an existing sandbox ──

@pytest.fixture
def bare_og(home, registry, fakes, og, real_git, monkeypatch):
    """og with no command, run in a folder: personal/app under ~/Projects, a folder
    outside it, and the same basename elsewhere. sbx lists what it's given; op reads
    a token, curl never answers. No terminal."""
    use_profile(home, "home")
    app, plain = home / "Projects/personal/app", home / "flat/plain"
    (home / "other/app").mkdir(parents=True)
    for r in (app, plain):
        subprocess.run(["git", "init", "-q", str(r)], check=True)
        subprocess.run(["git", "-C", str(r), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                        "commit", "-q", "--allow-empty", "-m", "i"], check=True)
    (home / ".config/sbx").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SBX_VAULT", "Sandbox")
    monkeypatch.setenv("SBX_SSH_DIR", str(home / "ssh"))
    fakes.op.answer([], stdout="tok")
    fakes.curl.answer([], code=1)

    def run(where, *args, listed="", signed_out=False):
        s = fakes.sbx
        s.clear()
        rows = "SANDBOX  AGENT   STATUS   WORKSPACE\n" + (f"{listed}\n" if listed else "")
        if signed_out:   # the first read answers; the create's own sign-in check then finds it signed out
            s.answer(["ls"], stdout=rows, once=True)
            s.answer(["ls"], stderr="401 Unauthorized: not signed in\n", code=1)
        else:
            s.answer(["ls"], stdout=rows)
        s.answer(["secret", "ls"], stdout="SCOPE  TYPE     NAME\nbox    service  github\n")
        s.answer(["settings", "get"], stdout="false\n")
        n = len(s.calls)
        monkeypatch.chdir(where)
        code, out, err = og(*args, stdin="")
        return code, out + err, s.calls[n:]

    return run, app, plain, home


@pytest.mark.parametrize(("says", "args"), [
    ("--item needs a vault item", ["--item", "notes"]),
    ("--item and --org together", ["--item", "github-pat-acme-desk", "--org", "acme"]),   # the item names its owner
    ("--org needs a GitHub owner slug", ["--org"]),                                          # no value
    ("--name needs a name, got '--sync'", ["--name", "--sync"]),                             # another option where it goes
    ("unknown option --bogus", ["--bogus"]),
    ("got two names ('a', 'b')", ["a", "b"]),
], ids=["not an item", "--item with --org", "no value", "an option as its value", "unknown option", "two names"])
def test_options_that_dont_parse_are_refused_before_any_sbx_call(bare_og, says, args):
    run, app, _, _ = bare_og
    code, out, calls = run(app, *args)
    assert code == 1 and says in out and calls == []


def test_help_anywhere_among_the_flags_prints_the_help_and_runs_nothing(bare_og):
    run, app, _, _ = bare_og
    code, out, calls = run(app, "--sync", "--help")
    assert code == 0 and "usage: og [<name>]" in out and calls == []


@pytest.mark.parametrize(("args", "says"), [
    ([], "app · token owner: personal (from path)"),                                       # named for its folder
    (["--org", "acme", "--name", "box2"], "box2 · token owner: acme (--org)"),
    (["--item", "github-pat-umbrella-work"], "app · token owner: umbrella (--item github-pat-umbrella-work)"),
], ids=["from the path", "--org and --name", "--item"])
def test_a_new_sandbox_says_its_name_and_owner_and_where_that_came_from_then_is_made(bare_og, args, says):
    run, app, _, _ = bare_og
    code, out, _ = run(app, *args, "--no-attach", signed_out=True)
    assert code == 1 and says in out and "not signed in" in out   # made: the create's sign-in check stops it here


def test_a_folder_outside_projects_with_no_terminal_for_the_menu_says_its_owner_is_the_default(bare_og):
    run, _, plain, home = bare_og
    _, out, _ = run(plain, "--no-attach", signed_out=True)
    assert f"plain · token owner: personal (default: outside {home / 'Projects'})" in out
    assert "which GitHub token" not in out


def test_a_folder_that_isnt_a_repo_with_no_terminal_to_ask_is_left_as_it_was(bare_og):
    run, _, _, home = bare_og
    loose = home / "flat/loose"
    loose.mkdir(parents=True)
    code, out, calls = run(loose)
    assert code == 1 and "not a git repo" in out and not (loose / ".git").exists()
    assert not [c for c in calls if c[:2] == ["env", "create"]]


def test_a_default_name_whose_sandbox_is_another_folders_is_refused_before_any_token(bare_og):
    run, app, _, home = bare_og
    code, out, calls = run(app, listed=f"app  claude  running  {home / 'other/app'}")
    assert code == 1
    assert f"sandbox 'app' belongs to {home / 'other/app'}, not {app}" in out and "og --name personal-app" in out
    assert not [c for c in calls if c[:2] == ["secret", "set"]]


def test_named_on_purpose_it_attaches_from_anywhere(bare_og):
    run, app, _, home = bare_og
    (home / ".config/sbx/ogun/tokens").mkdir(parents=True, exist_ok=True)
    (home / ".config/sbx/ogun/tokens/app.owner").write_text("personal\n")   # as its create left it: that folder names no owner
    (home / ".config/sbx/ogun/tokens/app.item").write_text("github-pat-personal-desk\n")
    code, out, _ = run(app, "app", "--no-attach", listed=f"app  claude  running  {home / 'other/app'}")
    assert code == 0 and "'app' exists — attaching" in out and "'app' is ready" in out


def test_appa_on_a_sandbox_made_without_it_is_refused_before_the_attach(bare_og):
    run, app, _, _ = bare_og
    code, out, calls = run(app, "--appa", listed=f"app  claude  running  {app}")
    assert code == 1 and "created without OpenAPPA" in out and "exists — attaching" not in out
    assert not [c for c in calls if c[:2] == ["secret", "set"]]


def test_org_on_an_existing_sandbox_replaces_its_token(bare_og):
    run, app, _, _ = bare_og
    code, _, calls = run(app, "--org", "acme", "--no-attach", listed=f"app  claude  running  {app}")
    assert code == 0 and any(c[:5] == ["secret", "set", "-f", "github", "--sandbox"] and c[5] == "app" for c in calls)


# ── the bare og's parts, each on its own ──

def test_flags_parse_into_what_was_asked_for():
    assert bare.parse(["box", "--org", "acme", "--sync", "--rm", "--no-attach", "--appa"]) == {
        "org": "acme", "item": "", "name": "box", "rm": True, "sync": True, "attach": False, "appa": True}


def test_nothing_asked_for_is_a_new_attaching_sandbox_named_for_its_folder():
    assert bare.parse([]) == {"org": "", "item": "", "name": "", "rm": False, "sync": False, "attach": True,
                              "appa": False}


def test_an_item_names_its_owner(home):
    use_profile(home, "home")   # an item's owner is what's left of it before one of the profiles' endings
    o = bare.parse(["--item", "github-pat-umbrella-desk"])
    assert (o["item"], o["org"]) == ("github-pat-umbrella-desk", "umbrella")


@pytest.mark.parametrize(("args", "says"), [
    (["--item", "notes"], "--item needs a vault item"),
    (["--item", "github-pat-acme-desk", "--org", "acme"], "--item and --org together"),
    (["--name", "-x"], "--name needs a name, got '-x'"),
    (["--bogus"], "unknown option --bogus"), (["a", "b"], "got two names ('a', 'b')")])
def test_flags_that_dont_parse_are_one_and_say_why(home, capfd, args, says):
    use_profile(home, "home")
    assert bare.parse(args) == 1 and says in "".join(capfd.readouterr())


def test_an_item_flag_with_no_value_names_the_vault_og_reads(home, capfd, monkeypatch):
    use_profile(home, "home")
    monkeypatch.setenv("SBX_VAULT", "Shared")
    assert bare.parse(["--item"]) == 1 and "--item needs an item name from vault 'Shared'" in "".join(capfd.readouterr())


def test_help_is_zero_and_prints_the_page(capfd):
    assert bare.parse(["--sync", "-h"]) == 0 and "usage: og [<name>]" in "".join(capfd.readouterr())


def test_the_owner_from_an_item_from_org_or_from_the_path(home):
    d = str(home / "Projects/umbrella/app")
    assert bare.owner(d, "umbrella", "github-pat-umbrella-desk") == ("umbrella", "--item github-pat-umbrella-desk")
    assert bare.owner(d, "acme", "") == ("acme", "--org")
    assert bare.owner(d, "", "") == ("umbrella", "from path")


@pytest.fixture
def attach(home, monkeypatch):
    """attach_existing with every step it takes recorded, each answering as set."""
    from ogun.net import baseline
    from ogun.sandbox import base, create, facts, session
    from ogun.secrets import github, grants
    said, ran = {"has_appa": False}, []

    def step(name, mod, attr):
        monkeypatch.setattr(mod, attr, lambda *a, **k: (ran.append(name), said.get(name, True))[1])

    for name, mod, attr in [("has_appa", facts, "has_appa"), ("set_token", github, "set_token"),
                            ("token_refresh", github, "token_refresh"), ("skills", create, "skills"),
                            ("setup", base, "setup"), ("remotes", session, "https_remotes"),
                            ("catch_up", grants, "catch_up"), ("default_rules_off", baseline, "default_rules_off")]:
        step(name, mod, attr)
    ws = home / "Projects/personal/app"
    ws.mkdir(parents=True)

    def run(*, explicit=False, ws=str(ws), d=str(ws), **opts):
        o = {**bare.parse([]), **opts}
        return bare.attach_existing("app", d, ws, explicit, o, o["org"] or "personal")

    return run, said, ran, home


def test_an_attach_refreshes_its_token_catches_up_on_grants_then_takes_sbxs_default_rules_out(attach):
    run, _, ran, _ = attach
    assert run() and ran == ["token_refresh", "catch_up", "default_rules_off"]


def test_a_default_name_another_folder_owns_is_refused_before_any_token(attach, capfd):
    run, _, ran, home = attach
    other = home / "other/app"
    other.mkdir(parents=True)
    assert not run(ws=str(other)) and ran == []
    assert f"belongs to {other}" in capfd.readouterr().err


def test_named_on_purpose_it_attaches_to_another_folders_sandbox(attach):
    run, _, ran, home = attach
    (home / "other/app").mkdir(parents=True)
    assert run(ws=str(home / "other/app"), explicit=True) and "token_refresh" in ran


def test_appa_asked_of_a_sandbox_made_without_it_is_refused(attach, capfd):
    run, _, ran, _ = attach
    assert not run(appa=True) and ran == ["has_appa"]
    assert "created without OpenAPPA" in capfd.readouterr().err


def test_org_replaces_the_token_instead_of_refreshing_it(attach):
    run, _, ran, _ = attach
    assert run(org="acme") and "set_token" in ran and "token_refresh" not in ran


def test_sync_reruns_the_skills_setup_and_remotes(attach):
    run, _, ran, _ = attach
    assert run(sync=True) and ran[1:4] == ["skills", "setup", "remotes"]


@pytest.mark.parametrize("step", ["token_refresh", "set_token", "skills", "default_rules_off"])
def test_a_step_that_fails_stops_the_attach(attach, step):
    run, said, _, _ = attach
    said[step] = False
    assert not run(org="acme" if step == "set_token" else "", sync=step == "skills")


def test_a_new_sandbox_needs_a_repo_to_make_it_from(home, real_git, monkeypatch, capfd):
    from ogun.sandbox import create
    made = []
    monkeypatch.setattr(create, "create", lambda *a: made.append(a) or True)
    loose = home / "loose"
    loose.mkdir()
    assert not bare.create_new("box", "personal", str(loose), "", False) and made == []
    assert "is not a git repo" in capfd.readouterr().err
    subprocess.run(["git", "init", "-q", str(loose)], check=True)
    assert bare.create_new("box", "personal", str(loose), "item", True)
    assert made == [("box", "personal", str(loose), "session", "item", True)]


@pytest.fixture
def upped(home, monkeypatch):
    """bare.up in personal/app with sbx's listing, the attach, the create and the
    session faked: what the session was handed, and which path ran."""
    from ogun.core import sbx
    from ogun.sandbox import init, session
    from ogun.secrets import github
    app = home / "Projects/personal/app"
    app.mkdir(parents=True)
    monkeypatch.chdir(app)
    seen = {"listed": []}
    monkeypatch.setattr(sbx, "ls", lambda: "listing")
    monkeypatch.setattr(sbx, "names", lambda listing: seen["listed"])
    monkeypatch.setattr(sbx, "workspace", lambda name, listing: str(app))
    monkeypatch.setattr(init, "offer_init", lambda d: True)
    monkeypatch.setattr(github, "warnings", lambda: None)
    monkeypatch.setattr(bare, "attach_existing", lambda *a: seen.setdefault("path", "attach") == "attach")
    monkeypatch.setattr(bare, "create_new", lambda *a: seen.setdefault("path", "create") == "create")
    monkeypatch.setattr(session, "session", lambda *a: seen.setdefault("session", a) and 0)
    return seen


@pytest.mark.parametrize(("listed", "path", "args", "session"), [
    ([], "create", [], ("app", False, False)),
    (["app"], "attach", ["--rm"], ("app", True, True)),
], ids=["a new sandbox", "an existing one, --rm"])
def test_both_paths_end_in_the_session_told_whether_it_existed_and_about_rm(upped, listed, path, args, session):
    upped["listed"] = listed
    assert bare.up(args) == 0 and upped["path"] == path and upped["session"] == session


def test_no_attach_ends_ready_with_no_session(upped, capfd):
    assert bare.up(["--no-attach"]) == 0 and "session" not in upped
    assert "'app' is ready" in capfd.readouterr().out
