"""The owner rules: whose GitHub token a sandbox for a folder gets, whether the
folder's path named that owner or it's a guess, and whether the folder is exactly
the repo a registry entry describes. A wrong answer hands one owner's credential
to another's sandbox."""

import pytest

from ogun.core import paths, settings


@pytest.fixture
def tree(home, registry):
    """~/Projects with owner folders, a symlink across owners, and repos placed by
    the registry's exact path outside it."""
    p = home / "Projects"
    for d in ("umbrella/shop", "personal/sub/deeper", "direct", "personal/lookalike"):
        (p / d).mkdir(parents=True)
    for d in (".hidden-repo/sub", ".tilde", "misnamed", "ownerless", "elsewhere/.hidden-repo"):
        (home / d).mkdir(parents=True)
    (p / "personal/link-to-umbrella").symlink_to(p / "umbrella/shop")
    registry({
        ".hidden-repo": {"owner": "umbrella", "path": str(home / ".hidden-repo")},
        ".tilde": {"owner": "umbrella", "path": "~/.tilde"},
        "wrongkey": {"owner": "umbrella", "path": str(home / "misnamed")},
        "ownerless": {"path": str(home / "ownerless")},
        "sub": {"owner": "umbrella", "path": str(p / "personal/sub")},
        "lookalike": {"owner": "umbrella", "path": str(p / "personal/lookalike")},
    })
    return home


# folder (from the scratch home), owner, whether the path named it, whether it's placed
OWNERS = [
    ("Projects/umbrella/shop", "umbrella", True, True),
    ("Projects/personal/sub", "personal", True, True),
    ("Projects/personal/sub/deeper", "personal", True, False),
    ("Projects/direct", "personal", False, False),
    ("Projects/personal/link-to-umbrella", "umbrella", True, True),
    (".hidden-repo", "umbrella", True, True),
    (".hidden-repo/sub", "personal", False, False),
    ("misnamed", "personal", False, False),
    ("elsewhere", "personal", False, False),
    ("Projects", "personal", False, False),
]


@pytest.mark.parametrize(("folder", "owner", "explicit", "placed"), OWNERS)
def test_owner_explicit_and_placed(tree, folder, owner, explicit, placed):
    d = str(tree / folder)
    assert (paths.org_from_path(d), paths.org_explicit(d), paths.placed(d)) == (owner, explicit, placed)


def test_a_symlink_is_its_targets_owner_not_the_folder_it_sits_in(tree):
    assert paths.org_from_path(str(tree / "Projects/personal/link-to-umbrella")) == "umbrella"


def test_a_declared_path_outside_projects_names_its_owner(tree):
    assert paths.path_owner(str(tree / ".hidden-repo")) == "umbrella"


def test_a_tilde_path_is_your_home(tree):
    d = str(tree / ".tilde")
    assert (paths.org_from_path(d), paths.org_explicit(d)) == ("umbrella", True)


def test_only_the_exact_declared_path_names_an_owner_not_a_subfolder(tree):
    assert paths.org_explicit(str(tree / ".hidden-repo/sub")) is False


def test_an_entry_keyed_by_another_name_than_the_paths_basename_names_nobody(tree):
    assert paths.org_explicit(str(tree / "misnamed")) is False


def test_an_entry_without_an_owner_names_nobody(tree):
    assert paths.org_explicit(str(tree / "ownerless")) is False


def test_inside_projects_the_folder_decides_and_the_registry_does_not_answer(tree):
    d = str(tree / "Projects/personal/lookalike")
    assert paths.org_from_path(d) == "personal"
    assert paths.path_owner(d) is None


def test_a_same_named_folder_elsewhere_gets_no_owner(tree):
    d = str(tree / "elsewhere/.hidden-repo")
    assert (paths.org_from_path(d), paths.org_explicit(d), paths.placed(d)) == ("personal", False, False)


def test_a_missing_folder_is_never_placed_or_owned_by_the_registry(tree):
    d = str(tree / "gone")
    assert (paths.placed(d), paths.path_owner(d)) == (False, None)


def test_an_unreadable_registry_stops_og_never_names_an_owner(tree):
    (tree / ".config/ogun/registry.json").write_text("{not json")
    with pytest.raises(settings.Unreadable, match=r"registry\.json"):
        paths.path_owner(str(tree / ".hidden-repo"))


@pytest.mark.parametrize("owner", ["", "-lead", "has space", "../up", "x" * 62])
def test_an_owner_that_isnt_a_plain_name_is_ignored(tree, registry, owner):
    registry({".hidden-repo": {"owner": owner, "path": str(tree / ".hidden-repo")}})
    assert paths.path_owner(str(tree / ".hidden-repo")) is None


# ── project folders (SBX_PROJECTS): per-owner, or one fixed owner ──

@pytest.fixture
def roots(tree, monkeypatch):
    """~/Projects per-owner as before and ~/Work fixed to acme; set as
    SBX_PROJECTS, or the listing given."""
    for d in ("Work/api/sub", "Work/.hidden", "outside/real"):
        (tree / d).mkdir(parents=True)
    (tree / "Work/link-out").symlink_to(tree / "outside/real")
    (tree / "outside/link-in").symlink_to(tree / "Work/api")

    def use(v=f"{tree}/Projects:{tree}/Work=acme"):
        monkeypatch.setenv("SBX_PROJECTS", v)
        return tree
    return use


ROOTS = [
    ("Work/api", "acme", True, True),                        # <root>/<repo>: the root's owner
    ("Work/api/sub", "personal", False, False),              # nothing deeper
    ("Work", "personal", False, False),                      # nor the root itself
    ("Work/link-out", "personal", False, False),             # a link in the root to a folder outside it
    ("outside/link-in", "acme", True, True),                 # the folder it is, wherever it's reached from
    ("Projects/umbrella/shop", "umbrella", True, True),           # per-owner as before
    ("Projects/personal/sub/deeper", "personal", True, False),
    (".hidden-repo", "umbrella", True, True),                          # a registry path outside every folder still names its owner
]


@pytest.mark.parametrize(("folder", "owner", "explicit", "placed"), ROOTS)
def test_each_project_folder_gives_owners_by_its_own_rule(roots, folder, owner, explicit, placed):
    d = str(roots() / folder)
    assert (paths.org_from_path(d), paths.org_explicit(d), paths.placed(d)) == (owner, explicit, placed)


def test_a_folder_reached_through_a_link_is_compared_physically(roots, tree):
    (tree / "work-link").symlink_to(tree / "Work")
    roots(f"{tree}/work-link=acme")
    assert paths.org_from_path(str(tree / "Work/api")) == "acme"


def test_a_registry_path_inside_any_project_folder_is_never_asked(roots, tree, registry):
    registry({"api": {"owner": "umbrella", "path": str(tree / "Work/api")}})
    roots()
    assert paths.path_owner(str(tree / "Work/api")) is None
    assert paths.org_from_path(str(tree / "Work/api")) == "acme"


def test_a_registry_path_that_is_a_project_folder_itself_is_never_asked(roots, tree, registry):
    registry({"Work": {"owner": "umbrella", "path": str(tree / "Work")}})
    roots()
    assert paths.path_owner(str(tree / "Work")) is None


def test_unset_is_projects_per_owner_and_one_folder_is_that_folder_per_owner(home, monkeypatch):
    monkeypatch.delenv("SBX_PROJECTS")
    assert paths.roots() == [(str(home / "Projects"), None)] and paths.projects() == str(home / "Projects")
    monkeypatch.setenv("SBX_PROJECTS", "~/Code")
    assert paths.roots() == [(str(home / "Code"), None)] and paths.projects() == str(home / "Code")


def test_the_projects_folder_the_other_commands_use_is_the_first_per_owner_one(roots, tree):
    roots(f"{tree}/Work=acme:{tree}/Code:{tree}/Projects")
    assert paths.projects() == str(tree / "Code")
    roots(f"{tree}/Work=acme")
    assert paths.projects() == str(tree / "Projects")


def test_a_message_names_the_project_folders_og_reads_not_always_projects(roots, tree, monkeypatch):
    monkeypatch.delenv("SBX_PROJECTS")
    assert paths.shown_projects() == "~/Projects" and paths.shown_repo("x") == "~/Projects/<owner>/x"
    roots(f"{tree}/Code:{tree}/Work=acme")
    assert paths.shown_projects() == "~/Code or ~/Work"
    assert paths.shown_repo("x") == "~/Code/<owner>/x or ~/Work/x"
    assert paths.shown_repo() == "~/Code/<owner>/<repo> or ~/Work/<repo>"


def test_and_one_og_cant_read_names_the_setting(monkeypatch, home):
    monkeypatch.setenv("SBX_PROJECTS", "relative")
    assert paths.shown_projects() == "a project folder (SBX_PROJECTS)"
    assert paths.shown_repo("x") == "a project folder's <owner>/x (SBX_PROJECTS)"


def test_no_message_outside_paths_names_projects_whatever_the_setting():
    import ast
    found = []
    for f in sorted((paths.OGUN / "src").rglob("*.py")):
        if f.name == "paths.py" and f.parent.name == "core":
            continue
        tree = ast.parse(f.read_text())
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        found += [f"{f.relative_to(paths.OGUN)}:{n.lineno}" for n in ast.walk(tree)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
                  and "~/Projects" in n.value]
    assert found == []


@pytest.mark.parametrize(("v", "why"), [
    ("~/Projects::~/Work=acme", "an empty folder"),
    ("relative/dir", "isn't a full path"),
    ("~/Work=", "isn't an owner"),
    ("~/Work=has space", "isn't an owner"),
    ("~/Work=../up", "isn't an owner"),
])
def test_a_project_folder_list_og_cant_read_stops_og_never_the_default(home, monkeypatch, v, why):
    monkeypatch.setenv("SBX_PROJECTS", v)
    with pytest.raises(settings.Unreadable, match=f"SBX_PROJECTS.*{why}"):
        paths.org_from_path(str(home / "Projects/umbrella/shop"))


# one folder inside another, in either order: a repo in the inner one (Projects/bigco/site), the
# inner one where the outer one's repo would be (Projects/umbrella/shop), inside an outer one's
# repo (Projects/umbrella/shop/vendor); the same folder twice, or through a link
NESTED = [
    "{t}/Projects:{t}/Projects/bigco=globex",
    "{t}/Projects/bigco=globex:{t}/Projects",
    "{t}/Projects:{t}/Projects/umbrella/shop=globex",
    "{t}/Projects:{t}/Projects/umbrella/shop/vendor=globex",
    "{t}/Work=acme:{t}/Work=globex",
    "{t}/Projects:{t}/proj-link/umbrella=globex",
]


@pytest.mark.parametrize("v", NESTED)
def test_project_folders_that_nest_stop_og_naming_both(tree, monkeypatch, v):
    (tree / "proj-link").symlink_to(tree / "Projects")
    monkeypatch.setenv("SBX_PROJECTS", v.format(t=tree))
    with pytest.raises(settings.Unreadable, match=r"SBX_PROJECTS: .* (is inside|are the same folder).*project folders can't nest"):
        paths.org_from_path(str(tree / "Projects/umbrella/shop"))


def test_folders_side_by_side_dont_nest_even_when_one_name_starts_like_the_other(tree, monkeypatch):
    (tree / "Work2").mkdir()
    monkeypatch.setenv("SBX_PROJECTS", f"{tree}/Work=acme:{tree}/Work2=globex")
    assert [o for _, o in paths.roots()] == ["acme", "globex"]


# ── reading the registry: the one place it's parsed ──

def test_the_registry_is_read_whole(home, registry):
    registry({"web": {"owner": "umbrella"}}, mcp=["tracker"])
    assert paths.read_registry() == {"mcp": ["tracker"], "repos": {"web": {"owner": "umbrella"}}}


@pytest.mark.parametrize("text", ["{not json", "[1, 2]", '"a string"'])
def test_a_registry_that_doesnt_parse_as_an_object_stops_og(home, text):
    (home / ".config/ogun/registry.json").write_text(text)
    with pytest.raises(settings.Unreadable, match=r"registry\.json"):
        paths.read_registry()


def test_a_missing_registry_reads_as_none(home):
    (home / ".config/ogun/registry.json").unlink(missing_ok=True)
    assert paths.read_registry() is None


def test_an_entry_is_looked_up_by_name(home, registry):
    registry({"web": {"owner": "umbrella"}, "odd": ["not", "an", "object"]})
    assert paths.registry_entry("web") == {"owner": "umbrella"}
    assert paths.registry_entry("odd") == ["not", "an", "object"]   # as written: the caller says what's wrong with it
    assert paths.registry_entry("none") == {}


@pytest.mark.parametrize("text", ['{"repos": ["web"]}', '{"mcp": []}'])
def test_no_readable_entries_means_an_empty_entry(home, text):
    (home / ".config/ogun/registry.json").write_text(text)
    assert paths.registry_entry("web") == {}
