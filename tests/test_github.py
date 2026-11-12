"""github: whose token a sandbox gets. The path's owner, unless the placed repo's
registry entry, under that same owner, names another GitHub account; and the
line you audit at create, saying where the owner came from."""

import json

import pytest

from conftest import use_profile
from ogun.secrets import github


def _d(home, rel):
    return str(home / rel)


@pytest.mark.parametrize(("folder", "owner"), [
    ("Projects/personal/oddball", "oddball-org"),   # an entry's github override
    ("Projects/personal/plain", "personal"),        # no override: the path's owner
    ("elsewhere/oddball", "personal"),              # the path names nobody: an override there is a credential on a guess
    (".hidden-repo", "hidden-org"),                          # a repo placed by path takes its entry's override
])
def test_the_token_owner(world, folder, owner):
    assert github.org_resolve(_d(world, folder)) == owner


def test_a_subfolder_named_like_an_entry_gets_no_override(world):
    (world / "Projects/personal/plain/oddball").mkdir()
    assert github.org_resolve(_d(world, "Projects/personal/plain/oddball")) == "personal"


@pytest.mark.parametrize(("folder", "source"), [
    (".hidden-repo", "registry github override"),
    (".tilde", "registry path"),
    ("Projects/personal/plain", "from path"),
])
def test_where_the_owner_came_from(world, folder, source):
    d = _d(world, folder)
    assert github.org_source(d, github.org_resolve(d)) == source


def test_anywhere_else_the_owner_is_the_fallback_it_is(world):
    d = _d(world, "tmp/.hidden-repo")
    assert github.org_source(d, github.org_resolve(d)) == f"default: outside {world / 'Projects'}"


def test_a_fixed_owner_folders_repo_is_from_path_and_the_fallback_names_every_folder(world, monkeypatch):
    (world / "Work/api").mkdir(parents=True)
    monkeypatch.setenv("SBX_PROJECTS", f"{world}/Projects:{world}/Work=acme")
    d = _d(world, "Work/api")
    assert (github.org_resolve(d), github.org_source(d, "acme")) == ("acme", "from path")
    d = _d(world, "tmp/.hidden-repo")
    assert github.org_source(d, github.org_resolve(d)) == f"default: outside {world / 'Projects'}, {world / 'Work'}"


# ── the token on attach: kept when right, set again when not, --sync read fresh ──

OWNERS = ("acme", "someone", "umbrella", "quill-labs", "personal")
EXPIRY = "HTTP/2 200\r\ngithub-authentication-token-expiration: 2027-01-15 10:00:00 UTC\r\n"


class Token:
    """Sandbox tk: sbx lists its github token unless told it has none; op answers
    tok-<item> for every item but the missing ones; curl answers as GitHub's API
    does, with the token's expiry."""

    def __init__(self, home, fakes):
        self.home, self.fakes = home, fakes
        self.profile("home")
        self.sbx()
        self.op()
        fakes.curl.answer([], stdout=EXPIRY)

    def profile(self, p):
        """This Mac's og profile: home, work, or none."""
        use_profile(self.home, p)

    def sbx(self, none=False, global_=False, set_code=0):
        s = self.fakes.sbx
        s.clear()
        listed = "SCOPE  TYPE     NAME\n" + ("" if none else "tk     service  github\n")
        s.answer(["secret", "ls", "--sandbox", "tk"], stdout=listed)
        s.answer(["secret", "ls"], stdout=listed + ("(global)  service  github\n" if global_ else ""))
        s.answer(["secret", "set"], code=set_code)

    def op(self, missing=(), items="[]"):
        o = self.fakes.op
        o.clear()
        o.answer(["item", "list"], stdout=items)
        for owner in OWNERS:
            for m in ("desk", "work", "old"):
                it = f"github-pat-{owner}-{m}"
                o.answer(["read", "-n", f"op://Sandbox/{it}/credential"], stdout="" if it in missing else f"tok-{it}",
                         code=1 if it in missing else 0)

    def record(self, owner, it, at=".config/sbx/ogun/tokens"):
        (self.home / at).mkdir(parents=True, exist_ok=True)
        for kind, v in (("owner", owner), ("item", it)):
            f = self.home / at / f"tk.{kind}"
            f.unlink(missing_ok=True) if v is None else f.write_text(v + "\n")

    def rec(self):
        return f"{github.token_owner('tk')}/{github.token_item('tk')}"

    def sets(self):
        return [c for c in self.fakes.sbx.calls if c[:2] == ["secret", "set"]]

    def reads(self):
        return [c[2].split("/")[3] for c in self.fakes.op.calls if c[:1] == ["read"]]

    def set_to(self, it):
        return ["secret", "set", "-f", "github", "--sandbox", "tk", "-t", f"tok-{it}"] in self.sets()


@pytest.fixture
def tk(home, registry, fakes, monkeypatch):
    monkeypatch.setenv("SBX_VAULT", "Sandbox")
    registry({"quill": {"owner": "acme", "github": "quill-labs"}})
    for d in ("Projects/acme/app", "Projects/acme/quill", "flat/app"):
        (home / d).mkdir(parents=True)
    github.records_dir().mkdir(parents=True)
    return Token(home, fakes)


def ws(home, rel="Projects/acme/app"):
    return str(home / rel)


def refresh(tk, owner, it, *, sync=False, at="Projects/acme/app"):
    tk.record(owner, it)
    return github.token_refresh("tk", sync, ws(tk.home, at) if at else "")


def test_an_owners_items_name_the_owner_this_macs_first_a_suffixed_profile_has_only_its_own(tk):
    assert github.items("personal") == ["github-pat-personal-desk", "github-pat-personal-work"]
    assert github.items("umbrella") == ["github-pat-umbrella-desk", "github-pat-umbrella-work"]
    tk.profile("work")
    assert github.items("umbrella") == ["github-pat-umbrella-work"]


def test_attach_keeps_a_token_from_the_right_owner_and_item_no_1password_read(tk):
    assert refresh(tk, "acme", "github-pat-acme-desk")
    assert tk.sets() == [] and tk.reads() == []


def test_another_profiles_item_an_unsuffixed_profile_may_use_stands_too(tk):
    assert refresh(tk, "acme", "github-pat-acme-work")
    assert tk.sets() == []


def test_sync_reads_it_fresh_from_the_item_it_holds_so_a_client_one_stays_client(tk):
    assert refresh(tk, "acme", "github-pat-acme-work", sync=True)
    assert len(tk.sets()) == 1 and tk.reads() == ["github-pat-acme-work"]
    assert tk.set_to("github-pat-acme-work")


def test_sync_reads_this_macs_own_item_when_the_one_on_record_no_longer_fits(tk):
    assert refresh(tk, "acme", "github-pat-acme-old", sync=True)
    assert len(tk.sets()) == 1 and tk.reads() == ["github-pat-acme-desk"]
    assert tk.rec() == "acme/github-pat-acme-desk"


@pytest.mark.parametrize("sync", [False, True])
def test_a_sandbox_with_no_token_gets_one_once(tk, sync):
    tk.sbx(none=True)
    assert refresh(tk, "acme", "github-pat-acme-desk", sync=sync)
    assert len(tk.sets()) == 1


def test_another_owners_token_is_replaced_by_its_workspaces_owners_and_said(tk, capfd):
    assert refresh(tk, "someone", "github-pat-someone-desk")
    assert len(tk.sets()) == 1 and tk.rec() == "acme/github-pat-acme-desk"
    assert "token owner on record: someone; from its workspace: acme" in capfd.readouterr().out


def test_no_owner_record_in_a_folder_naming_no_owner_is_refused_no_guessed_owners_token(tk, capfd):
    assert not refresh(tk, None, None, at="flat/app")
    assert tk.sets() == [] and tk.reads() == []
    assert "has a GitHub token og holds no owner record for, and its workspace" in capfd.readouterr().err


def test_with_a_record_there_the_owner_on_record_stands(tk):
    assert refresh(tk, "umbrella", "github-pat-umbrella-desk", at="flat/app")
    assert tk.sets() == []


def test_no_owner_record_in_a_folder_that_names_one_is_set_from_that_owners_item(tk):
    assert refresh(tk, None, None)
    assert len(tk.sets()) == 1 and tk.rec() == "acme/github-pat-acme-desk"


def test_no_item_record_is_set_again_from_this_macs_item_to_record_its_source(tk, capfd):
    assert refresh(tk, "acme", None)
    assert len(tk.sets()) == 1 and tk.rec() == "acme/github-pat-acme-desk"
    assert "token with no item on record; setting it again from this Mac's item" in capfd.readouterr().out


def test_under_a_suffix_another_profiles_item_is_replaced_from_its_own(tk):
    tk.profile("work")
    assert refresh(tk, "acme", "github-pat-acme-desk")
    assert len(tk.sets()) == 1 and tk.reads() == ["github-pat-acme-work"]
    assert tk.rec() == "acme/github-pat-acme-work"


def test_an_item_1password_doesnt_have_falls_back_to_the_next_and_the_record_names_it(tk):
    tk.sbx(none=True)
    tk.op(missing={"github-pat-acme-desk"})
    assert refresh(tk, "acme", None)
    assert tk.reads() == ["github-pat-acme-desk", "github-pat-acme-work"]
    assert tk.rec() == "acme/github-pat-acme-work"


def test_no_item_read_is_refused_before_sbx_is_asked_the_record_unchanged(tk, capfd):
    tk.sbx(none=True)
    tk.op(missing={"github-pat-acme-desk", "github-pat-acme-work"})
    assert not refresh(tk, "acme", "github-pat-acme-desk")
    assert tk.sets() == [] and tk.rec() == "acme/github-pat-acme-desk"
    err = capfd.readouterr().err
    assert "1Password returned no token for 'github-pat-acme-desk'" in err
    assert "og token acme" in [x.strip() for x in err.splitlines()]


def test_a_token_sbx_refuses_leaves_no_record_that_it_was_set(tk):
    tk.sbx(none=True, set_code=1)
    assert not refresh(tk, None, None)
    assert tk.rec() == "/"


def test_the_placed_repos_registry_github_override_names_the_owner(tk):
    tk.sbx(none=True)
    assert refresh(tk, None, None, at="Projects/acme/quill")
    assert tk.rec() == "quill-labs/github-pat-quill-labs-desk"


def test_a_sandbox_whose_workspace_is_unknown_is_refused(tk, capfd):
    assert not refresh(tk, "acme", "github-pat-acme-desk", at="")
    assert tk.sets() == []
    assert "workspace unknown" in capfd.readouterr().err


def test_vv_shows_the_set_call_never_the_token(tk, capfd, monkeypatch):
    monkeypatch.setenv("OGUN_VERBOSE", "2")
    tk.sbx(none=True)
    assert refresh(tk, "acme", "github-pat-acme-desk")
    out = "".join(capfd.readouterr())
    assert "sbx secret set" in out and "tok-github" not in out


def test_an_item_given_by_the_menu_or_item_is_the_only_one_read(tk):
    assert github.set_token("tk", "acme", "github-pat-acme-work")
    assert tk.reads() == ["github-pat-acme-work"] and tk.set_to("github-pat-acme-work")
    assert tk.rec() == "acme/github-pat-acme-work"


# ── where its records live: og's state folder ──

def test_a_sandboxs_token_records_go_in_ogs_state_folder(tk, monkeypatch):
    monkeypatch.setenv("SBX_OGUN_DIR", str(tk.home / "state"))
    tk.sbx(none=True)
    assert github.set_token("tk", "acme", "github-pat-acme-work")
    got = {f.name: f.read_text() for f in (tk.home / "state/tokens").iterdir()}
    assert got == {"tk.owner": "acme\n", "tk.item": "github-pat-acme-work\n", "github-acme.expires": "2027-01-15\n"}


# ── when a token dies: GitHub's own date, whenever og reads the token ──

def test_setting_a_token_records_its_expiry_the_token_on_curls_stdin_never_its_arguments(tk):
    tk.sbx(none=True)
    assert refresh(tk, "acme", None)
    assert github.expiry_file("acme").read_text() == "2027-01-15\n"
    assert tk.fakes.curl.stdin == ["Authorization: Bearer tok-github-pat-acme-desk\n"]
    assert not any("tok-" in a for c in tk.fakes.curl.calls for a in c)


@pytest.mark.parametrize("curl", [{"code": 7}, {"stdout": "HTTP/2 200\r\n"}], ids=["no answer", "no date"])
def test_no_answer_from_github_or_no_date_in_it_leaves_the_date_as_it_was(tk, curl):
    github.expiry_file("acme").write_text("2026-01-01\n")
    tk.fakes.curl.clear()
    tk.fakes.curl.answer([], **curl)
    tk.sbx(none=True)
    assert refresh(tk, "acme", None)
    assert github.expiry_file("acme").read_text() == "2026-01-01\n"


def test_an_expired_token_and_one_dying_within_a_week_are_warned_with_og_token_a_later_one_isnt(tk, capfd):
    import datetime
    github.expiry_file("umbrella").write_text("2020-01-01\n")
    github.expiry_file("acme").write_text(f"{datetime.date.today() + datetime.timedelta(days=3)}\n")
    github.expiry_file("far").write_text("2099-01-01\n")
    github.warnings()
    out = "".join(capfd.readouterr())
    assert "⚠ GitHub token 'umbrella' expired 2020-01-01" in out and "⚠ GitHub token 'acme' expires " in out
    assert "far" not in out
    assert "    og token umbrella" in out.splitlines()


def test_a_global_github_secret_is_warned_none_otherwise(tk, capfd):
    tk.sbx(global_=True)
    github.warnings()
    assert "a global github secret exists" in "".join(capfd.readouterr())
    tk.sbx()
    github.warnings()
    assert "".join(capfd.readouterr()) == ""


# ── the menu: a folder whose path names no owner ──

ITEMS = json.dumps([{"title": "github-pat-acme-work"}, {"title": "github-pat-personal-desk"},
                    {"title": "github-pat-umbrella-desk"}, {"title": "notes"}])


@pytest.fixture
def pick(tk, tmp_path, monkeypatch, capfd):
    """The menu answered with these lines, on a Mac whose profile is home: the item picked
    and what it said."""
    tk.profile("home")
    tk.op(items=ITEMS)

    def answer(lines: str) -> tuple[str, str]:
        f = tmp_path / "menu"
        f.write_text(lines)
        monkeypatch.setenv("SBX_MENU_IN", str(f))
        capfd.readouterr()
        return github.pick_item(), capfd.readouterr().err

    return answer


def test_the_menu_lists_the_vaults_tokens_this_mac_may_use_each_with_its_owner(pick):
    _, err = pick("1\n")
    assert "1) github-pat-acme-work  (owner: acme)" in err and "3) github-pat-umbrella-desk  (owner: umbrella)" in err
    assert "notes" not in err


@pytest.mark.parametrize(("lines", "picked"), [
    ("3\n", "github-pat-umbrella-desk"),        # a number picks that exact item
    ("\n", "github-pat-personal-desk"),      # Enter: this Mac's personal item
    ("x\ny\nz\n1\n", ""),                     # three misses pick nothing, never personal by accident
    ("", ""),                                 # nor does the end of input
])
def test_the_menus_answers(pick, lines, picked):
    assert pick(lines)[0] == picked


def test_a_typo_or_a_number_out_of_range_asks_again_and_the_next_line_answers(pick):
    picked, err = pick("x\n9\n2\n")
    assert picked == "github-pat-personal-desk"
    assert "not a number from 1 to 3: 'x'" in err
    assert err.index("'x'") < err.index("'9'")


def test_under_a_suffix_only_its_own_tokens_are_offered(pick, tk):
    tk.profile("work")
    picked, err = pick("1\n")
    assert picked == "github-pat-acme-work" and "desk" not in err


def test_a_vault_with_none_picks_nothing(pick, tk, monkeypatch):
    tk.op(items="[]")
    monkeypatch.setenv("SBX_MENU_IN", "/dev/null")
    assert github.pick_item() == ""


def test_an_empty_menu_says_the_vault_holds_none_this_mac_may_use(pick, tk, monkeypatch, capfd):
    tk.op(items="[]")
    monkeypatch.setenv("SBX_MENU_IN", "/dev/null")
    capfd.readouterr()
    assert github.pick_item() == ""
    err = capfd.readouterr().err
    assert "vault 'Sandbox'" in err and "github-pat-" in err and "1Password" in err


def test_with_no_profile_or_token_name_the_empty_menu_says_that_instead(pick, tk, monkeypatch, capfd):
    # no profile anywhere in the config, so no ending to tell a token item by
    tk.profile(None)
    (tk.home / ".config/ogun/config.toml").unlink()
    monkeypatch.setenv("SBX_MENU_IN", "/dev/null")
    capfd.readouterr()
    assert github.pick_item() == ""
    err = capfd.readouterr().err
    assert "SBX_TOKEN_NAME" in err and "profile" in err and "vault" not in err


# ── a token's item, its owner, and the items a Mac may use: what og token mints into and og reads ──

@pytest.mark.parametrize(("machine", "it"), [("work", "github-pat-acme-work"), ("home", "github-pat-acme-desk")])
def test_a_tokens_item_for_this_mac(tk, machine, it):
    tk.profile(machine)
    assert github.item("acme") == it


@pytest.mark.parametrize(("it", "owner"), [
    ("github-pat-personal-desk", "personal"), ("github-pat-foo-work-desk", "foo-work"), ("github-pat-acme-work", "acme"),
    ("github-pat-desk", None), ("github-pat--work", None), ("github-pat-a-b-c-work", "a-b-c"),
    ("x-github-pat-a-desk", None), ("github-pat-a-deskx", None), ("github-pat-a b-work", "a b"), ("", None)])
def test_an_items_owner_exactly_one_machine_word_off(home, it, owner):
    use_profile(home, "home")
    assert github.item_owner(it) == owner


@pytest.mark.parametrize(("machine", "kept"), [
    ("home", ["github-pat-acme-work", "github-pat-personal-desk", "github-pat-zeta-desk"]),
    ("work", ["github-pat-acme-work"])])
def test_the_vaults_items_a_mac_may_use_sorted(tk, machine, kept):
    tk.profile(machine)
    tk.op(items=json.dumps([{"title": t} for t in ("github-pat-zeta-desk", "github-pat-acme-work", "github-pat-desk-x",
                                                   "github-pat-desk", "github-pat-Up-desk", "github-pat-personal-desk",
                                                   "notes")] + [{"name": "no-title"}]))
    assert github.vault_items() == kept


def test_the_line_says_what_gave_the_owner_through_a_linked_folder_and_below_a_fixed_owners_repo(world, monkeypatch):
    (world / "Work/api/sub").mkdir(parents=True)
    (world / "wl").symlink_to(world / "Work")
    monkeypatch.setenv("SBX_PROJECTS", f"{world}/Projects:{world}/wl=acme")
    d = _d(world, "Work/api")
    assert (github.org_resolve(d), github.org_source(d, "acme")) == ("acme", "from path")
    d = _d(world, "Work/api/sub")
    assert github.org_resolve(d) == "personal"
    assert github.org_source(d, "personal") == f"default: no owner from {world / 'Projects'}, {world / 'wl'}"


def test_a_folder_in_projects_naming_no_owner_says_so_not_from_path(world):
    (world / "Projects/loose").mkdir()
    d = _d(world, "Projects/loose")
    assert github.org_source(d, github.org_resolve(d)) == f"default: no owner from {world / 'Projects'}"
