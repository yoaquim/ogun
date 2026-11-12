"""og's examples are invented: every name its tests and docs give an owner, a repo, a
profile, a host, a vault, a token item, a marketplace, a plugin, an MCP server or a
recipe is made only of words from one list, VOCABULARY, kept here. A name built from
anything else, a real one or a light disguise of one, fails until it is replaced or,
when it is truly invented, its words are added here on purpose.

The real services og talks to (GitHub, PyPI, Docker…) are named
in PUBLIC, whole: they are what og reaches, not examples."""

import re
from pathlib import Path

from ogun.core import paths

# The words og's examples are made of. Each is invented or plain English, and means
# nothing of anyone's setup; a new one is added here on purpose, with the name using it.
VOCABULARY = frozenset({
    "a", "a2", "accept", "awork", "access", "acme", "ads", "alias", "api", "app", "archive", "appa", "away",
    "b", "b2", "bad", "bigco", "box", "broken", "builds", "byhand", "c", "cdn", "classic", "code",
    "claude", "cloud", "com", "committed", "common", "corp", "cub", "custom", "db", "customvault", "demo", "den", "denied",
    "desk", "deskx", "dev", "dl", "docs", "early", "ef", "env", "escapee", "evil", "example", "exrepo",
    "extra", "failproj", "fern", "files", "foo", "fork", "from", "fromenv", "fromfile", "g", "get", "git",
    "github", "gitlab", "globex", "h", "has", "helper", "here", "hidden", "home", "hooli", "i", "ignored", "io",
    "initech", "it", "item", "keep", "kept", "key", "keys", "kit", "l", "labs", "hmoe", "late", "legacy", "pages", "link",
    "long", "lookalike", "mailer", "mcp", "me", "mirror", "name", "new", "newproj", "newrepo", "nope", "noproj",
    "nosuchrecipe", "notes", "notgithub", "nothing", "octocat", "oddball", "office", "ok", "old", "only", "open", "orders", "org", "other",
    "pat", "path", "personal", "plain", "plainlink", "pkg", "plugins", "printer", "projects", "quill", "private", "r", "rather", "rel", "related", "reloads",
    "repository", "sandbox", "sec", "secret", "shop", "shared", "signing", "site", "someone", "sprocket", "sso", "staged", "staging", "stray", "sub", "ta",
    "takes", "tapi", "team", "telemetry", "test", "tests", "to", "token", "tokens", "widgets",
    "tools", "tracker", "tst", "tup", "u", "umbrella", "up", "uploads", "v1", "vault", "w", "web", "with",
    "withnotes", "work", "x", "xdg", "y", "z", "zeta",
})

# Words fine in one role and not in another: personal is og's own owner word (the
# personal token), so never a profile's or a recipe's name, where it would read as one
NOT_AS = {"a profile": frozenset({"personal"}), "a recipe": frozenset({"personal"})}

# hosts og really talks to, the documentation it links, or a real installer an example recipe
# downloads from: named whole, never examples
PUBLIC = frozenset({
    "github.com", "api.github.com", "gitlab.com", "pypi.org", "files.pythonhosted.org",
    "objects.githubusercontent.com", "index.crates.io", "static.crates.io", "static.rust-lang.org", "*.rust-lang.org",
    "gateway.docker.internal", "www.openappa.com", "www.rust-lang.org", "www.w3.org", "archestra-ai", "openappa",
    "sh.rustup.rs", "docker", "sbx-releases", "astral-sh", "uv", "settings", "personal-access-tokens",
})

# Each, a pattern and what it finds a name in: its one group is the name, or, marked
# many, a list of them (a JSON list, an egress header, a line of hosts, owner pairs)
ROLES = (
    (r"Projects/([a-z0-9][\w.-]*)/", "an owner folder"),
    (r"Projects/[a-z0-9][\w.-]*/([a-z0-9][\w.-]*)", "a repo folder"),
    (r"github\.com[:/]([A-Za-z0-9][\w.-]*)/", "a GitHub owner"),
    (r"github\.com[:/][A-Za-z0-9][\w.-]*/([A-Za-z0-9][\w-]*)", "a GitHub repo"),
    (r"[\"']owner[\"']:\s*[\"']([^\"']+)[\"']", "an owner"),
    (r"\[profiles\.([\w-]+)\]", "a profile"),
    (r"use_profile\([^,()]+,\s*[\"']([\w-]+)[\"']", "a profile"),
    (r"[.]machine\([\"']([\w-]+)[\"']\)", "a profile"),
    (r"[\"']profiles[\"']:\s*\[([^\]]*)\]", "a profile", "many"),
    (r"https?://([A-Za-z0-9.-]+\.[A-Za-z]{2,})", "a host"),
    (r"(?<![\w-])([a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:example|example\.com|example\.org|example\.net))\b", "a host"),
    (r"[\"']hosts[\"']:\s*\[([^\]]*)\]", "a host", "many"),
    (r"#\s*(?:runtime-)?egress:\s*([^\n]+)", "a host", "many"),
    (r"\bog (?:allow|net) \S+ ([^\n|]+)", "a host", "many"),
    (r"\bog pass (?!-)\S+ \S+ ((?:(?:[a-z0-9-]+\.)+[a-z]{2,}[, ]*)+)", "a host", "many"),
    (r"(?:\bOG_VAULT[\"']?\s*[=,]|(?<![\w.-])vault = )\s*[\"']([^\"'{]+)[\"']", "a vault"),
    (r"op://([^/\s\"'{]+)/", "a vault"),
    (r"(github-pat-[a-z0-9-]*[a-z0-9])", "a token item"),
    (r"[\"']item[\"']:\s*[\"']([^\"'{]+)[\"']", "a token item"),
    (r"--item [\"']([^\"']+)[\"']", "a token item", "many"),
    (r"\bog(?:un)? (?:[^\s:]+ )*--item ([a-z][\w-]*)(?![\w-])", "a token item"),
    (r"[\"']marketplaces[\"']:\s*\[([^\]]*)\]", "a marketplace", "many"),
    (r"[\"']marketplaces[\"']:\s*\{\s*[\"']([\w-]+)[\"']", "a marketplace"),
    (r"[\"']plugins[\"']:\s*\[([^\]]*)\]", "a plugin", "many"),
    (r"(?:enabledPlugins[^\n]*?|plugin install )[\"']?([\w-]+)@[\w-]+", "a plugin", "many"),
    (r"(?:enabledPlugins[^\n]*?|plugin install )[\"']?[\w-]+@([\w-]+)", "a marketplace", "many"),
    (r"[\"']mcp[\"']:\s*\[([^\]]*)\]", "an MCP server", "many"),
    (r"mcp (?:add|auth) ([a-z][\w-]*)", "an MCP server"),
    (r"templates/([\w-]+)\.sh", "a recipe"),
    (r"\bog template (?:rm )?(?!ls\b|rm\b|--)([a-z][\w-]*)", "a recipe"),
    (r"[\"']template[\"']:\s*[\"']([\w-]+)[\"']", "a recipe"),
    (r"(?:\bOG_GITHUB_OWNERS[\"']?\s*|(?<![\w.-])github_owners )=\s*[\"']([^\"']+)[\"']", "a GitHub owner", "many"),
    (r"(?:\bOG_PROJECTS[\"']?\s*|(?<![\w.-])projects )=\s*[\"']([^\"']+)[\"']", "a project folder", "many"),
    (r"\bog(?:un)? (?:[^\s:]+ )*--org ([a-z][\w-]*)(?![\w-])", "an owner"),
    (r"\bog token ([a-z][\w-]*)(?![\w-])(?! +[a-z])", "an owner"),
    (r"\[(?:profile|sso-session) ([\w-]+)\]", "an AWS profile"),
)
ROLES_RE = [(re.compile(r[0]), r[1], len(r) > 2) for r in ROLES]
# a flag, a placeholder (<owner>, $HOME, {name}), a setting's own name (OG_PROJECTS) or
# a message (a name with a space in it) is no example
NOT_A_NAME = re.compile(r"^[-<$`{%]|[<>()]|^[A-Z][A-Z0-9_]+$|\S\s+\S")
# what a host looks like, once its scheme is off: dotted, maybe a * in front, maybe a path
HOST = re.compile(r"^\*?[\w-]+(?:\.[\w-]+)+(?:/\S*)?$")


def names_of(group: str, role: str, many: bool) -> list[str]:
    """The names in what a role matched: the group itself, or, for a list, every quoted
    name when it holds quotes, else each at a comma, a colon or a space. A host's
    role takes only what is shaped like one: the line after `og net <name>` can be prose."""
    if not many:
        names = [group]
    elif re.search(r"[\"']", group):
        names = re.findall(r"[\"']([^\"']+)[\"']", group)
    else:
        names = re.split(r"[,:\s]+", group)
    names = [re.sub(r"^https?://", "", n.strip()).rstrip(".,;:") for n in names]
    return [n for n in names if n and not NOT_A_NAME.search(n) and (role != "a host" or HOST.match(n))]


def names_in(text: str) -> list[tuple[str, str]]:
    """Each (role, name) the text gives an example in."""
    return [(what, n) for rx, what, many in ROLES_RE for m in rx.finditer(text) for n in names_of(m.group(1), what, many)]


def words_of(name: str) -> list[str]:
    """A name's words: its letters and digits, split at anything else; a number is
    no word (an account in a test, a port)."""
    return [w for w in re.split(r"[^a-z0-9]+", name.lower()) if w and not w.isdigit()]


def off_list(name: str, role: str = "") -> list[str]:
    """The words of a name not in VOCABULARY, or not right in its role; none for a
    PUBLIC name."""
    if name.lower() in PUBLIC:
        return []
    return [w for w in words_of(name) if w not in VOCABULARY or w in NOT_AS.get(role, ())]


def og_files() -> list[Path]:
    """Every file of og's a team would read: its tests and docs, where its examples
    are; its source, with its help and usage; the scripts it sends into a sandbox; its
    setup, test runner and completion."""
    me = Path(__file__).resolve()
    found = [*(paths.OGUN / "tests").rglob("*"), *(paths.OGUN / "docs").rglob("*.md"), *(paths.OGUN / "src").rglob("*"),
             *(paths.OGUN / "sandbox-scripts").rglob("*"), *(paths.OGUN / "bin").rglob("*"),
             *(paths.OGUN / n for n in ("completion.bash", "setup.sh", "test.sh", "pyproject.toml"))]
    return sorted(f for f in found if f.is_file() and f.resolve() != me and "__pycache__" not in f.parts)


def test_every_name_in_ogs_examples_is_made_of_the_vocabulary():
    found = {}
    for f in og_files():
        try:
            text = f.read_text()
        except UnicodeDecodeError:
            continue
        bad = sorted({f"{what} {name!r}: {w}" for what, name in names_in(text) for w in off_list(name, what)})
        if bad:
            found[str(f.relative_to(paths.OGUN))] = bad[:4]
    assert found == {}


def test_every_word_of_the_vocabulary_is_in_use():
    # a word nothing uses is a way in: a real name built of it would pass unnoticed
    text = "\n".join(f.read_text(errors="replace") for f in og_files())
    assert sorted(w for w in VOCABULARY if not re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", text, re.I)) == []


# ── the check itself: each role found, a name off the list caught, the vocabulary passed ──

import pytest  # noqa: E402


@pytest.mark.parametrize(("text", "role", "name"), [
    ("~/Projects/zorbco/app", "an owner folder", "zorbco"),
    ("~/Projects/acme/zorbrepo", "a repo folder", "zorbrepo"),
    ("https://github.com/zorbco/app", "a GitHub owner", "zorbco"),
    ("git@github.com:acme/zorbrepo.git", "a GitHub repo", "zorbrepo"),
    ('{"owner": "zorbco"}', "an owner", "zorbco"),
    ("[profiles.zorbmac]", "a profile", "zorbmac"),
    ('use_profile(home, "zorbmac")', "a profile", "zorbmac"),
    ('tk.machine("zorbmac")', "a profile", "zorbmac"),
    ("https://zorb.host.io/x", "a host", "zorb.host.io"),
    ("git.zorb.example", "a host", "git.zorb.example"),
    ('vault = "Zorbvault"', "a vault", "Zorbvault"),
    ('"profiles": ["zorbmac"]', "a profile", "zorbmac"),
    ("op://Zorbvault/item/credential", "a vault", "Zorbvault"),
    ("github-pat-zorbco-home", "a token item", "github-pat-zorbco-home"),
    ('"item": "zorb-token"', "a token item", "zorb-token"),
    ('"marketplaces": ["zorb-market"]', "a marketplace", "zorb-market"),
    ('"marketplaces": {"zorb-market": {}}', "a marketplace", "zorb-market"),
    ('"plugins": ["zorbplugin"]', "a plugin", "zorbplugin"),
    ('"enabledPlugins": { "zorbplugin@acme-kit": true }', "a plugin", "zorbplugin"),
    ("claude plugin install acme@zorb-market", "a marketplace", "zorb-market"),
    ('"mcp": ["tracker-zorb"]', "an MCP server", "tracker-zorb"),
    ("sbx mcp add tracker-zorb", "an MCP server", "tracker-zorb"),
    ("templates/zorbrecipe.sh", "a recipe", "zorbrecipe"),
    ('"template": "zorbrecipe"', "a recipe", "zorbrecipe"),
    ("og template zorbrecipe", "a recipe", "zorbrecipe"),
    ("og template rm zorbrecipe", "a recipe", "zorbrecipe"),
    ('"profiles": ["home", "zorbmac"]', "a profile", "zorbmac"),
    ('"mcp": ["notes", "tracker-zorb"]', "an MCP server", "tracker-zorb"),
    ('"plugins": ["widgets", "zorbplugin"]', "a plugin", "zorbplugin"),
    ('"marketplaces": ["acme-kit", "zorb-market"]', "a marketplace", "zorb-market"),
    ('"hosts": ["api.zorb.io"]', "a host", "api.zorb.io"),
    ("# egress: dl.zorb.io, *.zorb.io", "a host", "dl.zorb.io"),
    ("# runtime-egress: api.cub.example dl.zorb.io", "a host", "dl.zorb.io"),
    ("og allow cub api.zorb.io --read-only", "a host", "api.zorb.io"),
    ("og net cub zorb.io dl.zorb.io", "a host", "dl.zorb.io"),
    ("og pass cub KEY api.zorb.io dash.zorb.io --paste", "a host", "dash.zorb.io"),
    ('--item "Zorb API Token"', "a token item", "Zorb"),
    ("og pass cub K --expose --item zorb-key", "a token item", "zorb-key"),
    ('github_owners = "personal=zorbco acme=acme-corp"', "a GitHub owner", "personal=zorbco"),
    ('projects = "~/Projects:~/Zorb=acme"', "a project folder", "~/Zorb=acme"),
    ("og cub --org zorbco --sync", "an owner", "zorbco"),
    ("og token zorbco", "an owner", "zorbco"),
    ("[profile zorb-prod]", "an AWS profile", "zorb-prod"),
    ("[sso-session zorbco]", "an AWS profile", "zorbco"),
])
def test_each_role_is_found_and_a_name_off_the_list_caught(text, role, name):
    assert (role, name) in names_in(text)
    assert "zorb" in "".join(off_list(name)) or any(w.startswith("zorb") for w in off_list(name))


@pytest.mark.parametrize("text", [
    "og allow <name> <domain>… --read-only", "og token <owner>", "og net cub --rm", 'projects = "$HOME/Projects"',
    "--item `github-pat-<owner>`", "og pass: --paste and --item are two", "an explicit --org or --item on an",
    "og: --item and --org together",
])
def test_a_placeholder_or_a_flag_is_no_example(text):
    assert names_in(text) == []


def test_the_scripts_og_sends_into_a_sandbox_and_its_setup_are_read_too():
    rel = {str(f.relative_to(paths.OGUN)) for f in og_files()}
    assert {"setup.sh", "test.sh", "bin/venv", "sandbox-scripts/sandbox-ssh.sh", "src/ogun/net/baseline.toml"} <= rel


@pytest.mark.parametrize("name", ["acme", "github-pat-acme-home", "gitlab.example.com", "pypi.org", "files.pythonhosted.org",
                                  "a-rather-long-related-repository-name-"])
def test_and_names_of_its_words_or_public_hosts_pass(name):
    assert off_list(name) == []


def test_a_name_with_words_off_the_list_names_each():
    assert off_list("tracker-zorb-free") == ["zorb", "free"]


def test_personal_is_fine_as_an_owner_but_not_as_a_profile_or_a_recipe():
    assert off_list("personal", "an owner") == [] and off_list("personal", "a profile") == ["personal"]
    assert off_list("home", "a profile") == []


def test_a_message_or_a_settings_name_is_no_example():
    assert names_in('"item": "has space"') == [] and names_in('OG_VAULT", "OG_PROJECTS"') == []
