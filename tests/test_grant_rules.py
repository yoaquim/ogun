"""The secret-grant rules (ogun.secrets.rules): which grant is valid and which a
sandbox gets (docs/secrets.md#secret-grants)."""

import json

import pytest

from ogun.secrets import rules

OK = {"env": "API_KEY", "hosts": ["api.example.com"], "item": "api-x"}


def checked(g):
    said = []
    return rules.check(g, "here", said.append), said


# ── one grant: valid, or refused with why ──

def test_a_valid_grant_its_hosts_lowercased_trimmed_sorted_once_and_field_credential_by_default():
    got, said = checked({**OK, "hosts": [" B.example.com", "a.example.com", "b.EXAMPLE.com"]})
    assert got == ("API_KEY", "a.example.com,b.example.com", "api-x", "credential") and said == []
    assert checked({**OK, "field": "token"})[0][3] == "token"


@pytest.mark.parametrize("g", [
    "not an object", ["a", "list"],
])
def test_a_grant_that_isnt_an_object_is_skipped(g):
    got, said = checked(g)
    assert got is None and said == ["here: a grant must be an object — skipped"]


@pytest.mark.parametrize("bad", [
    {"env": "lower"}, {"env": "9LEADING_DIGIT"}, {"env": "X; rm -rf /"}, {"env": "A" * 65}, {"env": 1},
    {"item": "has space"}, {"item": ""}, {"item": "i" * 129}, {"item": None},
    {"field": "has/slash"}, {"field": 2},
    {"hosts": "api.example.com"}, {"hosts": ["api.example.com", 3]}, {"hosts": None},
])
def test_a_malformed_grant_is_skipped(bad):
    got, said = checked({**OK, **bad})
    assert got is None
    assert said == ["here: a malformed grant (env A-Z0-9_, item and field plain names, hosts a list) — skipped"]


def test_the_longest_names_allowed_are_valid():
    assert checked({**OK, "env": "A" * 64, "item": "i" * 128, "field": "f" * 128})[0]


@pytest.mark.parametrize("env", ["GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"])
def test_a_variable_gh_and_git_read_as_a_github_credential_is_refused(env):
    got, said = checked({**OK, "env": env})
    assert got is None and said == [f"here: {env} is what gh and git read as a GitHub credential — refused"]


def test_a_grant_naming_no_host_is_refused():
    got, said = checked({**OK, "hosts": []})
    assert got is None
    assert said == ["here: API_KEY names no host — refused (the proxy swaps a value in only on named hosts)"]


@pytest.mark.parametrize("host", ["github.com", "api.github.com", "GitHub.com", "objects.githubusercontent.com",
                                  "githubusercontent.com"])
def test_a_github_host_is_refused(host):
    got, said = checked({**OK, "hosts": ["ok.example.com", host]})
    assert got is None
    assert said == [f"here: API_KEY names a GitHub host ({host}) — refused (one GitHub identity per sandbox)"]


@pytest.mark.parametrize("host", ["*.example.com", "localhost", "a..example.com", "-a.example.com", "a-.example.com",
                                  "a.example.com.", "a_b.example.com", "x" * 64 + ".example.com"])
def test_a_host_that_isnt_an_exact_name_is_refused(host):
    got, said = checked({**OK, "hosts": [host]})
    assert got is None and said == [f"here: API_KEY: '{host}' is not an exact host name — refused (no wildcards)"]


def test_not_github_lookalikes_are_hosts_like_any_other():
    assert checked({**OK, "hosts": ["notgithub.com", "github.com.example.org"]})[0]


# ── which grants one sandbox gets ──

TOP_P = {"env": "TYPE_KEY", "hosts": ["api.example.com"], "item": "api-x", "profiles": ["home"]}
TOP_W = {"env": "WORK_KEY", "hosts": ["api.work.example"], "item": "c", "profiles": ["work"]}
ORDERS_G = {"env": "ORDERS_API_KEY", "hosts": ["api.orders.example"], "item": "orders-staging-key"}
ALL_TYPE = "*@home\tTYPE_KEY\tapi.example.com\tapi-x\tcredential"
ORDERS = "personal/orders\tORDERS_API_KEY\tapi.orders.example\torders-staging-key\tcredential"


@pytest.fixture
def reg(tmp_path):
    f = tmp_path / "registry.json"

    def write(repos=None, top=None, raw=None):
        f.write_text(raw if raw is not None else json.dumps(
            {"repos": {"orders": {"owner": "personal", "secrets": [ORDERS_G]}} if repos is None else repos,
             "secrets": [TOP_P, TOP_W] if top is None else top}))
        return f
    return write


def resolved(path, repo="orders", owner="personal", placed=True, machine="home"):
    said = []
    return rules.resolve(path, repo, owner, placed, machine, said.append), said


def test_the_repos_own_grant_and_this_macs_top_level_ones_a_line_each(reg):
    assert resolved(reg()) == ([ALL_TYPE, ORDERS], [])


def test_a_top_level_grant_reaches_only_the_profiles_it_names_and_none_without_one(reg):
    assert resolved(reg(), machine="work")[0] == ["*@work\tWORK_KEY\tapi.work.example\tc\tcredential", ORDERS]
    assert resolved(reg(), machine="")[0] == [ORDERS]
    assert resolved(reg(top=[{**TOP_P, "profiles": "home"}]))[0] == [ORDERS]
    assert resolved(reg(top=[{**TOP_P, "profiles": None}]))[0] == [ORDERS]


def test_a_machine_named_blank_matches_no_mac_not_even_one_with_no_machine(reg):
    assert resolved(reg(top=[{**TOP_P, "profiles": [""]}]), machine="")[0] == [ORDERS]


@pytest.mark.parametrize("top", [{"env": "X"}, 5, "secrets"])
def test_a_top_level_list_that_isnt_one_grants_nothing(reg, top):
    assert resolved(reg(top=top))[0] == [ORDERS]


def test_a_repo_with_no_entry_gets_only_the_top_level_grants(reg):
    assert resolved(reg(), repo="plain") == ([ALL_TYPE], [])


def test_a_repos_grant_needs_the_directory_to_be_the_repo(reg):
    got, said = resolved(reg(), placed=False)
    assert got == [ALL_TYPE]
    assert said == ["repo 'orders' grants secrets, but this directory is not the repo it describes "
                    "(a project folder's <owner>/orders, or the entry's `path`) — skipped"]


def test_a_repos_grant_needs_a_declared_owner(reg):
    got, said = resolved(reg(repos={"orders": {"secrets": [ORDERS_G]}}))
    assert got == [ALL_TYPE] and said == ["repo 'orders' grants secrets but declares no `owner` — skipped"]


def test_a_repos_grant_needs_its_owner_to_be_the_sandboxs(reg):
    got, said = resolved(reg(), owner="initech")
    assert got == [ALL_TYPE]
    assert said == ["repo 'orders' grants secrets for owner 'personal', but this sandbox's owner is 'initech' — "
                    "skipped (basename collision across owners)"]


def test_a_refused_grant_is_named_by_where_it_is_and_the_rest_still_apply(reg):
    got, said = resolved(reg(repos={"orders": {"owner": "personal", "secrets": [{**ORDERS_G, "hosts": []}, ORDERS_G]}},
                             top=[{**TOP_P, "env": "GH_TOKEN"}]))
    assert got == [ORDERS]
    assert said == ["top-level grant #1: GH_TOKEN is what gh and git read as a GitHub credential — refused",
                    "repo 'orders' grant #1: ORDERS_API_KEY names no host — refused (the proxy swaps a value in only on named hosts)"]


def test_one_variable_granted_two_ways_is_refused_outright(reg):
    got, said = resolved(reg(repos={"orders": {"owner": "personal", "secrets": [{**TOP_P, "item": "other"}]}}))
    assert got == []
    assert said == ["TYPE_KEY is granted twice, differently (top-level, personal/orders) — refused, none applied"]


def test_the_same_grant_twice_hosts_in_any_case_is_applied_once(reg):
    same = {"env": "TYPE_KEY", "hosts": ["API.example.com"], "item": "api-x", "field": "credential"}
    assert resolved(reg(repos={"orders": {"owner": "personal", "secrets": [same]}})) == ([ALL_TYPE], [])


@pytest.mark.parametrize("raw", ["{", "[]", "null"])
def test_a_registry_that_doesnt_parse_grants_nothing_and_says_so(reg, raw):
    f = reg(raw=raw)
    got, said = resolved(f)
    assert got == [] and len(said) == 1 and said[0].startswith(f"{f} doesn't parse (") and said[0].endswith(") — no grants")


def test_a_missing_registry_grants_nothing_and_says_so(tmp_path):
    got, said = resolved(tmp_path / "none.json")
    assert got == [] and said[0].startswith(f"{tmp_path / 'none.json'} doesn't parse (")


def test_by_default_what_it_says_goes_to_stderr_marked_as_the_secrets(reg, capfd):
    assert rules.resolve(reg(), "orders", "personal", False, "home") == [ALL_TYPE]
    assert capfd.readouterr().err.startswith("  ! secrets: repo 'orders' grants secrets, but this directory")
