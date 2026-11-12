"""The owner gate every per-repo capability passes: the folder is exactly the repo
the registry entry describes, and the entry declares the path's owner. A repo's
template, marketplaces, private places, MCP servers, related mounts and egress
each refuse in their own words; those words are pinned here."""

import pytest

from ogun import mcp
from ogun.core import paths, registry
from ogun.sandbox import appa, choose

# what each capability asks for in the entry, and how to ask for it
ASKS = {
    "template": ({"template": "dev"}, choose.template_project),
    "marketplaces": ({"marketplaces": ["tools"]}, choose.marketplaces),
    "appa": ({"appa": {"private": ["gitlab.com/umbrella/web"]}}, appa.private),
    "mcp": ({"mcp": ["tracker"]}, mcp.servers),
    "related": ({"repos": {"read": ["umbrella/api"], "write": []}}, registry.related),
    "egress": ({"egress": [{"hosts": ["example.com"], "write": False, "for": "docs"}]}, registry.egress),
}

UNPLACED = {
    "template": "template: repo 'web' asks for 'dev', but this directory is not the repo it describes "
                "(~/Projects/<owner>/web, or the entry's `path`); skipped",
    "marketplaces": "marketplaces: repo 'web' asks for ['tools'], but this directory is not the repo it describes; skipped",
    "appa": "appa: repo 'web' names private places, but this folder is not the repo it describes "
            "(~/Projects/<owner>/web, or the entry's `path`); skipped",
    "mcp": "  ! mcp: web lists servers, but its folder isn't under ~/Projects/<owner>/, so they're skipped",
    "related": "entry 'web' has grants, but this directory is not the repo it describes "
               "(~/Projects/<owner>/web, or the entry's `path`) — its grants are skipped",
    "egress": "entry 'web' lists domains, but this directory is not the repo it describes "
              "(~/Projects/<owner>/web, or the entry's `path`) — none allowed",
}

OWNERLESS = {
    "template": "template: repo 'web' asks for 'dev' but declares no `owner`; skipped "
                "(add \"owner\": \"umbrella\" to the entry to enable it)",
    "marketplaces": "marketplaces: repo 'web' asks for ['tools'] but declares no `owner`; skipped "
                    "(add \"owner\": \"umbrella\" to the entry to enable it)",
    "appa": "appa: repo 'web' names private places for owner 'None', but this sandbox's owner is "
            "'umbrella'; skipped (add or fix the entry's `owner`)",
    "mcp": "  ! mcp: web lists servers but no owner, so they're skipped; add \"owner\": \"umbrella\" to its entry",
    "related": None,   # related mounts don't need a declared owner, only a matching one
    "egress": "entry 'web' lists domains but no `owner` — none allowed",
}

FOREIGN = {
    "template": "template: repo 'web' asks for 'dev' for owner 'other', but this sandbox's owner is "
                "'umbrella'; skipped (basename collision across owners)",
    "marketplaces": "marketplaces: repo 'web' asks for ['tools'] for owner 'other', but this sandbox's owner is "
                    "'umbrella'; skipped (basename collision across owners)",
    "appa": "appa: repo 'web' names private places for owner 'other', but this sandbox's owner is "
            "'umbrella'; skipped (add or fix the entry's `owner`)",
    "mcp": "  ! mcp: web's servers are for other, not umbrella, so they're skipped",
    "related": "entry 'web' is other's repo, but this sandbox's owner is umbrella — its grants are skipped "
               "(two owners have a repo named web)",
    "egress": "entry 'web' is for owner 'other', but this sandbox's owner is 'umbrella' — none of its domains allowed "
              "(two owners have a repo named web)",
}


@pytest.fixture
def repos(home, registry):
    """umbrella/web under ~/Projects (placed), a same-named folder elsewhere (not), and
    a registry writer for web's entry."""
    for d in ("Projects/umbrella/web", "Projects/umbrella/api", "elsewhere/web"):
        (home / d).mkdir(parents=True)
    (home / ".config/ogun/marketplaces.json").write_text('{"marketplaces": {}}')

    def entry(**e):
        registry({"web": e})

    return {"placed": str(home / "Projects/umbrella/web"), "unplaced": str(home / "elsewhere/web"), "entry": entry}


def _run(capsys, repos, what, folder, **owner):
    ask, fn = ASKS[what]
    repos["entry"](**ask, **owner)
    out = fn(repos[folder])
    return out, capsys.readouterr().err


@pytest.mark.parametrize("what", ASKS)
def test_a_folder_that_isnt_the_repo_is_refused(capsys, repos, what):
    out, err = _run(capsys, repos, what, "unplaced", owner="umbrella")
    assert UNPLACED[what] in err
    assert not out


@pytest.mark.parametrize("what", [w for w in ASKS if "~/Projects" in UNPLACED[w]])
def test_and_the_refusal_names_the_project_folders_og_reads(capsys, repos, monkeypatch, what):
    monkeypatch.setenv("SBX_PROJECTS", "~/Projects:~/Work=umbrella")
    _, err = _run(capsys, repos, what, "unplaced", owner="umbrella")
    assert UNPLACED[what].replace("~/Projects/<owner>/web", "~/Projects/<owner>/web or ~/Work/web")\
        .replace("under ~/Projects/<owner>/", "under ~/Projects/<owner>/ or ~/Work/") in err


def test_a_secret_grants_refusal_names_them_too(capfd, repos, monkeypatch):
    from ogun.secrets import approval
    monkeypatch.setenv("SBX_PROJECTS", "~/Projects:~/Work=umbrella")
    repos["entry"](owner="umbrella", secrets=[{"env": "WEB_TOKEN", "hosts": ["example.com"], "item": "web"}])
    approval.grants(repos["unplaced"])
    assert "(~/Projects/<owner>/web or ~/Work/web, or the entry's `path`) — skipped" in capfd.readouterr().err


@pytest.mark.parametrize("what", [w for w in ASKS if OWNERLESS[w]])
def test_an_entry_without_an_owner_is_refused(capsys, repos, what):
    out, err = _run(capsys, repos, what, "placed")
    assert OWNERLESS[what] in err
    assert not out


@pytest.mark.parametrize("what", ASKS)
def test_another_owners_entry_is_refused(capsys, repos, what):
    out, err = _run(capsys, repos, what, "placed", owner="other")
    assert FOREIGN[what] in err
    assert not out


@pytest.mark.parametrize("what", ["template", "mcp", "related", "egress"])
def test_the_placed_repo_with_its_owner_gets_it(capsys, repos, what):
    out, err = _run(capsys, repos, what, "placed", owner="umbrella")
    assert out
    assert "skipped" not in err and "none allowed" not in err


def test_related_mounts_need_no_declared_owner(capsys, repos):
    out, _ = _run(capsys, repos, "related", "placed")
    assert out == [str(repos["placed"]).replace("/web", "/api")]


# ── the gate itself: one answer, each caller says it its own way ──

@pytest.mark.parametrize(("folder", "owner", "answer"), [
    ("placed", "umbrella", ""),
    ("unplaced", "umbrella", "unplaced"),
    ("placed", None, "ownerless"),
    ("placed", "other", "foreign"),
])
def test_refusal(repos, folder, owner, answer):
    assert paths.refusal(repos[folder], {} if owner is None else {"owner": owner}) == answer


def test_unplaced_is_answered_before_the_owner(repos):
    assert paths.refusal(repos["unplaced"], {}) == "unplaced"
