"""Editing the registry (og project add): the grant is written to the one file it
was read from."""

import json
import re
import subprocess

import pytest

from ogun.core import registry as reg
from ogun.core import settings


def test_a_grant_is_written_to_the_registry_it_was_read_from(registry):
    f = registry({"web": {"owner": "umbrella", "description": "café"}})
    assert reg.record("web", "umbrella", "umbrella/api", "read") is True
    assert json.loads(f.read_text())["repos"]["web"] == {
        "owner": "umbrella", "description": "café", "repos": {"read": ["umbrella/api"], "write": []}}
    assert f.read_text().endswith("}\n") and "café" in f.read_text()


def test_a_registry_that_doesnt_parse_is_refused_and_left_alone(home):
    f = home / ".config/ogun/registry.json"
    f.write_text("{not json")
    with pytest.raises(settings.Unreadable, match=r"registry\.json isn.t valid JSON"):
        reg.record("web", "umbrella", "umbrella/api", "read")
    assert f.read_text() == "{not json"


# ── the world og project and the related mounts read ──

def _p(home, rel):
    return str(home / "Projects" / rel)


# ── related mounts: read and write both mount, read-only is the mount's job ──

def test_a_read_grant_mounts(world):
    assert _p(world, "umbrella/shop-b") in reg.related(_p(world, "umbrella/shop-a"))


def test_a_write_grant_mounts_too(world):
    assert reg.related(_p(world, "umbrella/shop-b")) == [_p(world, "umbrella/shop-a")]


def test_a_dotdot_segment_in_a_grant_is_skipped(world):
    assert not any("sneak" in m for m in reg.related(_p(world, "umbrella/shop-a")))


def test_a_two_part_grant_with_a_dotdot_segment_is_refused_as_not_owner_slash_repo(world, registry, capsys):
    registry({"shop-a": {"owner": "umbrella", "repos": {"read": ["umbrella/.."], "write": []}}})
    assert reg.related(_p(world, "umbrella/shop-a")) == []
    assert ("'shop-a' reads 'umbrella/..', which isn't <owner>/<repo> "
            f"(a folder under {world / 'Projects'})") in capsys.readouterr().err.replace("~", str(world))


def test_another_owners_same_named_repo_gets_none_of_the_entrys_grants(world):
    (world / "Projects/personal/shop-a").mkdir()
    assert reg.related(_p(world, "personal/shop-a")) == []


def test_the_placed_repo_gets_its_entrys_mounts_and_a_lookalike_doesnt(world):
    assert reg.related(str(world / ".hidden-repo")) == [_p(world, "umbrella/shop-b")]
    assert reg.related(str(world / "tmp/.hidden-repo")) == []


def test_a_subfolder_of_another_checkout_named_like_a_repo_gets_no_mounts(world):
    (world / "Projects/umbrella/shop-b/shop-a").mkdir()
    assert reg.related(_p(world, "umbrella/shop-b/shop-a")) == []


def test_a_repo_named_with_dotdot_inside_mounts(world, og, monkeypatch):
    _git(world / "Projects/personal/plain")
    (world / "Projects/personal/pkg..name/.git").mkdir(parents=True)
    monkeypatch.chdir(world / "Projects/personal/plain")
    assert og("project", "add", "pkg..name")[0] == 0
    assert _p(world, "personal/pkg..name") in reg.related(_p(world, "personal/plain"))


# ── og project add: stand in the repo that gets the mount ──

# ── related's parts: the entry's grants once checked, its push list, its mounts ──

def test_a_placed_entry_with_its_owner_gives_its_grants(world):
    assert reg.entry_grants(_p(world, "umbrella/shop-b"), "", False) == \
        ("shop-b", "umbrella", "umbrella", {"read": [], "write": ["umbrella/shop-a"]})
    assert reg.entry_grants("", "", False) is None


@pytest.mark.parametrize(("where", "said"), [
    ("tmp/.hidden-repo", "this directory is not the repo it describes"),
    ("Projects/personal/shop-a", "is umbrella's repo, but this sandbox's owner is personal"),
])
def test_an_unplaced_or_foreign_entry_gives_none_said_except_for_the_push_list(world, capsys, where, said):
    (world / where).mkdir(parents=True, exist_ok=True)
    assert reg.entry_grants(str(world / where), "", False) is None and said in capsys.readouterr().err
    assert reg.entry_grants(str(world / where), "push", False) is None and capsys.readouterr().err == ""
    assert reg.entry_grants(str(world / where), "", True) is None and capsys.readouterr().err == ""


def test_an_entry_thats_no_object_gives_none(world, registry, capsys):
    registry({"plain": {"owner": "personal", "repos": ["personal/x"]}})
    assert reg.entry_grants(_p(world, "personal/plain"), "", False) is None
    assert "is not an object with a `repos` object" in capsys.readouterr().err


def test_the_push_list_is_each_github_address_without_dot_git_others_skipped(capsys):
    lists = {"push": ["https://github.com/me/a.git", "https://gitlab.com/me/b", 7, "https://github.com/me/c/"]}
    assert reg.push_list("x", "me", lists, False) == ["https://github.com/me/a", "https://github.com/me/c"]
    assert capsys.readouterr().err.count("isn't a GitHub repo's address") == 2


def test_an_entry_with_no_owner_pushes_nowhere(capsys):
    assert reg.push_list("x", None, {"push": ["https://github.com/me/a"]}, False) == []
    assert "declares no owner — its push list is skipped" in capsys.readouterr().err
    assert reg.push_list("x", None, {}, False) == [] and capsys.readouterr().err == ""


def test_mounts_are_read_then_write_once_each_write_alone_for_write(world):
    lists = {"read": ["umbrella/shop-b"], "write": ["umbrella/shop-a", "umbrella/shop-b"]}
    assert reg.mounts("x", "umbrella", lists, "", False) == [_p(world, "umbrella/shop-b"), _p(world, "umbrella/shop-a")]
    assert reg.mounts("x", "umbrella", lists, "write", False) == [_p(world, "umbrella/shop-a"), _p(world, "umbrella/shop-b")]


@pytest.mark.parametrize(("grant", "said"), [
    ("umbrella/../sneak", "isn't <owner>/<repo>"), ("umbrella", "isn't <owner>/<repo>"), (7, "isn't <owner>/<repo>"),
    ("personal/plain", "belongs to another owner"), ("umbrella/none", "isn't checked out at"),
    ("umbrella/link", "outside"),
])
def test_a_mount_out_of_shape_anothers_not_there_or_leading_out_is_skipped_and_said(world, capsys, grant, said):
    (world / "Projects/umbrella/link").symlink_to(world / "Projects/personal/plain")
    assert reg.mounts("x", "umbrella", {"read": [grant]}, "", False) == [] and said in capsys.readouterr().err
    assert reg.mounts("x", "umbrella", {"read": [grant]}, "", True) == [] and capsys.readouterr().err == ""


def test_a_link_into_a_folder_whose_name_starts_like_the_owners_is_outside_it(world, capsys):
    (world / "Projects/umbrella-evil/y").mkdir(parents=True)
    (world / "Projects/umbrella/evil").symlink_to(world / "Projects/umbrella-evil/y")
    assert reg.mounts("x", "umbrella", {"read": ["umbrella/evil"]}, "", False) == [] and "outside" in capsys.readouterr().err


# a project folder inside another, in each shape a mount could cross owners by: around
# a related checkout, in its place, or inside it. og stops before any mount or grant
@pytest.mark.parametrize("inner", ["umbrella", "umbrella/shop-b", "umbrella/shop-b/vendor"])
def test_nested_project_folders_stop_og_before_any_related_mount_or_grant(world, monkeypatch, inner):
    (world / "Projects/umbrella/shop-b/.git").mkdir(exist_ok=True)
    monkeypatch.setenv("SBX_PROJECTS", f"{world}/Projects:{world}/Projects/{inner}=globex")
    with pytest.raises(settings.Unreadable, match="can't nest"):
        reg.mounts("x", "umbrella", {"read": ["umbrella/shop-b"]}, "", True)
    with pytest.raises(settings.Unreadable, match="can't nest"):
        reg.grant_id("umbrella/shop-b", "umbrella", "x", "read")


def test_a_link_inside_the_owners_folder_mounts_what_it_points_at_never_the_link(world):
    (world / "Projects/umbrella/alias").symlink_to(world / "Projects/umbrella/shop-b")
    assert reg.mounts("x", "umbrella", {"read": ["umbrella/alias"]}, "", False) == [_p(world, "umbrella/shop-b")]


def _git(d):
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(d)], check=True)


def _grants(home, repo):
    e = json.loads((home / ".config/ogun/registry.json").read_text())["repos"].get(repo) or {}
    return e.get("repos") or {}


@pytest.fixture
def in_plain(world, monkeypatch):
    for d in ("personal/planner", "personal/extra"):
        (world / "Projects" / d / ".git").mkdir(parents=True)
    (world / "Projects/personal/notes").mkdir()
    _git(world / "Projects/personal/plain")
    monkeypatch.chdir(world / "Projects/personal/plain")
    return world


def test_a_bare_name_grants_the_same_owner_sibling_and_says_what_next(in_plain, og):
    code, out, _ = og("project", "add", "planner")
    assert code == 0
    assert _grants(in_plain, "plain")["read"] == ["personal/planner"]
    assert "✓ plain now reads personal/planner" in out
    assert "next: plain's sandboxes get the mount when recreated (the change is in ~/.config/ogun/registry.json)" in out


def test_write_moves_the_grant_never_duplicates_it(in_plain, og):
    og("project", "add", "planner")
    out = og("project", "add", "planner", "--write")[1]
    assert _grants(in_plain, "plain") == {"read": [], "write": ["personal/planner"]}
    assert "✓ plain reads personal/planner and may push to it" in out


def test_owner_slash_name_moves_the_same_grant_back_to_read(in_plain, og):
    og("project", "add", "planner", "--write")
    og("project", "add", "personal/planner")
    assert _grants(in_plain, "plain") == {"read": ["personal/planner"], "write": []}


def test_a_full_path_names_the_same_grant(in_plain, og):
    og("project", "add", "planner")
    code, out, _ = og("project", "add", _p(in_plain, "personal/planner"))
    assert code == 0
    assert "plain already has personal/planner: nothing to change" in out


def test_a_full_path_through_a_symlinked_projects_root_still_resolves(in_plain, og, monkeypatch):
    og("project", "add", "planner")
    (in_plain / "plink").symlink_to(in_plain / "Projects")
    monkeypatch.setenv("SBX_PROJECTS", str(in_plain / "plink"))
    code, out, _ = og("project", "add", str(in_plain / "plink/personal/planner"))
    assert code == 0
    assert "plain already has personal/planner: nothing to change" in out


def test_a_cross_owner_grant_is_refused_and_nothing_recorded(in_plain, og):
    code, _, err = og("project", "add", "umbrella/shop-b")
    assert code != 0
    assert "a repo can only read its own owner's repos" in err
    assert "umbrella/shop-b" not in json.dumps(_grants(in_plain, "plain"))


@pytest.mark.parametrize("target", ["ghost", "notes", "plain"])
def test_no_checkout_not_a_checkout_and_the_repo_itself_are_refused(in_plain, og, target):
    assert og("project", "add", target)[0] == 1
    assert target not in json.dumps(_grants(in_plain, "plain"))


def test_a_github_address_goes_in_the_push_list_without_dot_git(in_plain, og):
    code, out, _ = og("project", "add", "https://github.com/octocat/sprocket.git")
    assert code == 0
    assert _grants(in_plain, "plain")["push"] == ["https://github.com/octocat/sprocket"]
    assert ("✓ plain may push to https://github.com/octocat/sprocket\n"
            "next: plain's sandboxes get it at their next attach (the change is in ~/.config/ogun/registry.json)") in out
    assert reg.related(_p(in_plain, "personal/plain"), "push") == ["https://github.com/octocat/sprocket"]


def test_the_same_github_repo_again_is_already_there(in_plain, og):
    og("project", "add", "https://github.com/octocat/sprocket.git")
    code, out, _ = og("project", "add", "https://github.com/octocat/sprocket/")
    assert code == 0
    assert "plain already has https://github.com/octocat/sprocket: nothing to change" in out


@pytest.mark.parametrize("url", ["https://gitlab.com/me/x", "https://github.com/octocat"])
def test_an_address_off_github_or_naming_no_repo_is_refused(in_plain, og, url):
    assert og("project", "add", url)[0] == 1
    assert "push" not in _grants(in_plain, "plain")


def test_project_ls_shows_a_push_grant(in_plain, og):
    og("project", "add", "https://github.com/octocat/sprocket.git")
    out = og("project", "ls")[1]
    assert any(line.startswith("plain ") and "push: https://github.com/octocat/sprocket" in line for line in out.splitlines())


def test_a_symlinked_name_resolving_outside_the_owner_tree_is_refused(in_plain, og):
    (in_plain / "elsewhere/escapee/.git").mkdir(parents=True)
    (in_plain / "Projects/personal/escapee").symlink_to(in_plain / "elsewhere/escapee")
    assert og("project", "add", "escapee")[0] != 0
    assert "escapee" not in json.dumps(_grants(in_plain, "plain"))


def test_a_symlink_alias_of_this_repo_is_refused(in_plain, og):
    (in_plain / "Projects/personal/plainlink").symlink_to(in_plain / "Projects/personal/plain")
    assert og("project", "add", "plainlink")[0] != 0
    assert "plainlink" not in json.dumps(_grants(in_plain, "plain"))


def test_the_picker_lists_checkouts_dot_named_ones_too_on_stderr(in_plain, og):
    (in_plain / "Projects/personal/.hidden/.git").mkdir(parents=True)
    code, out, err = og("project", "add", stdin="")
    assert code == 1
    assert out == ""
    assert err.startswith("mount which personal repo into plain's sandboxes (read)?\n")
    assert ".hidden" in err and "notes" not in err


def test_a_grant_from_a_subfolder_lands_on_the_repo_roots_entry(in_plain, og, monkeypatch):
    (in_plain / "Projects/personal/plain/tools").mkdir()
    monkeypatch.chdir(in_plain / "Projects/personal/plain/tools")
    og("project", "add", "extra")
    assert _grants(in_plain, "plain")["read"] == ["personal/extra"]
    assert "tools" not in json.loads((in_plain / ".config/ogun/registry.json").read_text())["repos"]


def test_an_unknown_repo_seeds_its_own_entry_with_the_paths_owner(in_plain, og, monkeypatch):
    _git(in_plain / "Projects/personal/newrepo")
    monkeypatch.chdir(in_plain / "Projects/personal/newrepo")
    og("project", "add", "planner")
    e = json.loads((in_plain / ".config/ogun/registry.json").read_text())["repos"]["newrepo"]
    assert e["owner"] == "personal" and "description" not in e
    assert e["repos"]["read"] == ["personal/planner"]


def test_another_owners_same_named_repo_cant_edit_the_entry(in_plain, og, monkeypatch):
    _git(in_plain / "Projects/personal/shop-a")
    monkeypatch.chdir(in_plain / "Projects/personal/shop-a")
    code, _, err = og("project", "add", "planner")
    assert code != 0
    assert "two owners have a repo named shop-a" in err
    assert "personal/planner" not in json.dumps(_grants(in_plain, "shop-a"))


def test_a_path_that_names_no_owner_gets_no_grants(in_plain, og, monkeypatch):
    _git(in_plain / "elsewhere/oddball")
    monkeypatch.chdir(in_plain / "elsewhere/oddball")
    assert og("project", "add", "plain")[0] == 1


def test_the_registry_stays_valid_json_after_edits(in_plain, og):
    for args in (["planner"], ["planner", "--write"], ["https://github.com/octocat/sprocket"]):
        og("project", "add", *args)
    json.loads((in_plain / ".config/ogun/registry.json").read_text())


# ── og project ls ──

def test_project_ls_json_carries_each_repos_grants(world, og):
    rows = json.loads(og("project", "ls", "--json")[1])
    assert rows and all({"repo", "read", "write"} <= set(r) and "description" not in r for r in rows)
    assert next(r for r in rows if r["repo"] == "shop-a")["read"][0] == "umbrella/shop-b"


@pytest.mark.parametrize("sub", [["add", "other"], ["ls"]])
def test_without_a_registry_each_project_command_says_so_without_a_traceback(home, og, monkeypatch, sub):
    assert not (home / ".config/ogun/registry.json").exists()
    _git(home / "Projects/personal/here")
    monkeypatch.chdir(home / "Projects/personal/here")
    code, out, err = og("project", *sub)
    assert code == 1
    assert "no registry.json at ~/.config/ogun/registry.json (the repos og knows" in err
    assert "Traceback" not in out + err


def test_project_ls_on_a_terminal_is_a_section_a_repo_with_its_grants_as_notes(registry, og, monkeypatch):
    from ogun.core import log
    registry({"atlas": {"owner": "x", "repos": {"read": ["hooli/charts"]}}, "cub": {"owner": "x"}, "fern": {"owner": "x"}})
    monkeypatch.setattr(log, "pretty", lambda err=False: True)
    monkeypatch.setattr(log, "console", lambda err: log.Console(stderr=err, highlight=False, soft_wrap=True,
                                                                  force_terminal=True, width=100))
    lines = [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in og("project", "ls")[1].splitlines()]
    assert lines[:2] == ["atlas", "  · reads hooli/charts"]
    assert "nothing granted" in lines and "  · cub, fern" in lines
    assert not any(line.startswith("[") for line in lines)
