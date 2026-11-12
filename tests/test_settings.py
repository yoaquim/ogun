"""settings: og's settings come from ~/.config/ogun/config.toml (under
$XDG_CONFIG_HOME when that's set), each one overridden by an environment variable
OG_<NAME>, and fall back to its default when neither sets it. Never from a
shell profile. A file og can't read as its settings stops og: a vault name it
misread, or a typo'd key, would otherwise go quietly back to the default."""

import os
from pathlib import Path

import pytest

from ogun.core import paths, settings
from ogun.exchange import folders, screen
from ogun.net import egress
from ogun.sandbox import appa, base, create, envfile, remove, session
from ogun.secrets import approval, github, sshkeys, token


def conf(home: Path, text: str) -> Path:
    f = home / ".config/ogun/config.toml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    return f


# each setting, through the code that uses it:
# (setting, its reader, its default with HOME as h, a value to set)
H = "<home>"
READERS = [
    ("vault", github.vault, "Sandbox", "Other"),
    ("vault", approval.grants_vault, "Sandbox", "Other"),
    ("projects", paths.projects, f"{H}/Projects", "/x/code"),
    ("exchange", folders.exchange, f"{H}/sandboxes.noindex", "/x/ex"),
    ("take_dest", screen.take_dest, f"{H}/Downloads", "/x/dl"),
    ("host_ro_mounts", lambda: ":".join(envfile.host_ro_mounts()), "", "/x/a:/x/b"),
    ("apt_tools", lambda: " ".join(base.apt_tools_list().split()[len(base.OWN_TOOLS.split()):]), "", "make"),
    ("token_name", github.token_name, "", "home"),
    ("token_suffix", github.token_suffix, "", "-work"),
    ("provision", session.provision_command, "", "/x/provision.sh"),
    ("skills_dir", create.skills_dir, "", "/x/skills-src"),
    ("github_owners", lambda: " ".join(f"{k}={v}" for k, v in token.github_owners().items()), "", "acme=acme-corp"),
    ("protected_keys", lambda: ":".join(str(p) for p in sshkeys.protected_keys()), f"{H}/.ssh/allowed_signers",
     "/x/signer:/x/signers"),
]
IDS = [f"{r[0]}-{i}" for i, r in enumerate(READERS)]

# og's own internals: fixed, never a setting (HOME as h)
INTERNALS = [
    (paths.state_dir, f"{H}/.local/state/ogun"),
    (sshkeys.ssh_dir, f"{H}/.ssh"),
    (create.skills_store, f"{H}/Library/Application Support/com.docker.sandboxes/sandboxes/agent-skills"),
    (appa.lock_file, f"{H}/.config/ogun/appa.lock"),
    (approval.approved_file, f"{H}/.local/state/ogun/approved-secrets"),
    (egress._approvals, f"{H}/.local/state/ogun/approved-egress"),
    (lambda: remove.probe_timeout(stopped=False), 120),
    (lambda: remove.probe_timeout(stopped=True), 400),
    (base.update_timeout, 300),
    (base.update_log, "/tmp/ogun-claude-update.log"),
]


def read(reader, home: Path):
    v = reader()
    return v if isinstance(v, int) else str(v).replace(str(home), H)


@pytest.fixture
def bare(home, monkeypatch):
    """No setting from the environment, not even the ones the home fixture sets."""
    for n in settings.NAMES:
        monkeypatch.delenv(settings.env_name(n), raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    return home


@pytest.mark.parametrize(("name", "reader", "default", "value"), READERS, ids=IDS)
def test_a_setting_neither_the_file_nor_the_environment_sets_is_its_default(bare, name, reader, default, value):
    assert read(reader, bare) == default


@pytest.mark.parametrize(("name", "reader", "default", "value"), READERS, ids=IDS)
def test_the_file_sets_it_by_its_plain_name(bare, name, reader, default, value):
    conf(bare, f'{name} = "{value}"\n')
    assert read(reader, bare) == value


@pytest.mark.parametrize(("name", "reader", "default", "value"), READERS, ids=IDS)
def test_og_and_its_name_in_capitals_wins_over_the_file(bare, monkeypatch, name, reader, default, value):
    conf(bare, f'{name} = "/from/the/file"\n')
    monkeypatch.setenv("OG_" + name.upper(), value)
    assert read(reader, bare) == value


def test_the_readers_cover_every_setting():
    assert set(settings.NAMES) == {r[0] for r in READERS}


@pytest.mark.parametrize(("reader", "where"), INTERNALS)
def test_ogs_internals_have_fixed_homes(bare, reader, where):
    assert read(reader, bare) == where


@pytest.mark.parametrize("key", ["SBX_VAULT", "VAULT", "ogun_dir", "ssh_dir", "rm_probe_timeout"])
def test_a_key_that_isnt_one_of_the_settings_stops_og_naming_it(bare, key):
    conf(bare, f'{key} = "x"\n')
    with pytest.raises(settings.Unreadable, match=f"{key} isn't a setting og has"):
        settings.get("vault")


def test_og_state_lives_under_xdg_state_home_when_that_is_set(bare, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xstate"))
    assert paths.state_dir() == tmp_path / "xstate/ogun"


def test_an_empty_environment_variable_is_unset_so_the_file_still_answers(bare, monkeypatch):
    conf(bare, 'vault = "FromFile"\n')
    monkeypatch.setenv("OG_VAULT", "")
    assert github.vault() == "FromFile"


def test_a_number_in_the_file_reads_as_text(bare):
    conf(bare, "token_suffix = 30\n")
    assert settings.get("token_suffix") == "30"


def test_the_file_lives_under_xdg_config_home_when_that_is_set(bare, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    conf(bare, 'vault = "Ignored"\n')
    (tmp_path / "xdg/ogun").mkdir(parents=True)
    (tmp_path / "xdg/ogun/config.toml").write_text('vault = "Xdg"\n')
    assert github.vault() == "Xdg"


def test_a_tilde_in_a_path_from_the_file_is_home(bare):
    conf(bare, 'exchange = "~/ex"\n')
    assert folders.exchange() == bare / "ex"


def test_no_file_is_every_default(bare):
    assert not (bare / ".config/ogun/config.toml").exists()
    assert github.vault() == "Sandbox"


# ── a file og can't take as its settings stops og ──

@pytest.mark.parametrize(("text", "said"), [
    ("vault = \n", "isn't valid TOML"),
    ('valt = "Other"\n', "valt isn't a setting og has"),
    ('vault = ["a"]\n', "vault must be text or a number"),
    ('[vault]\nx = "a"\n', "vault must be text or a number"),
])
def test_a_file_og_cant_read_as_its_settings_is_an_error_naming_the_file(bare, text, said):
    f = conf(bare, text)
    with pytest.raises(settings.Unreadable) as e:
        github.vault()
    assert said in str(e.value) and str(f).replace(str(bare), "~") in str(e.value)


def test_a_broken_file_stops_og_even_where_the_environment_sets_the_setting_asked_for(bare, monkeypatch):
    conf(bare, 'valt = "Other"\n')
    monkeypatch.setenv("OG_VAULT", "FromEnv")
    with pytest.raises(settings.Unreadable):
        github.vault()


def test_and_og_stops_on_it_saying_why_running_nothing(og, bare, fakes):
    conf(bare, 'valt = "Other"\n')
    code, _, err = og("pass", "cub", "TOKEN")
    assert code == 1 and "~/.config/ogun/config.toml" in err and "valt" in err
    assert fakes.sbx.calls == [] and fakes.op.calls == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file whatever its mode")
def test_a_file_og_cant_open_is_the_same_error(bare):
    f = conf(bare, "")
    f.chmod(0)
    try:
        with pytest.raises(settings.Unreadable):
            github.vault()
    finally:
        f.chmod(0o600)


# ── nothing reads a setting past this ──

def test_no_module_reads_a_setting_from_the_environment_itself():
    src = paths.OGUN / "src/ogun"
    for f in src.rglob("*.py"):
        if f.name == "settings.py":
            continue
        text = f.read_text()
        for n in map(settings.env_name, settings.NAMES):
            assert f'environ.get("{n}"' not in text and f'environ["{n}"]' not in text, f"{f.name} reads {n}"
    assert "_env_path" not in Path(remove.__file__).read_text() and "def _secs" not in Path(remove.__file__).read_text()


# ── what the shell's completion and og's install look at: og's own answer ──

def test_og_internal_paths_is_each_folder_the_shell_looks_in_as_og_resolves_it(og, bare):
    conf(bare, 'exchange = "~/ex"\nprojects = "/x/code"\n')
    code, out, _ = og("internal", "paths")
    assert code == 0 and dict(line.split("\t") for line in out.splitlines()) == {
        "EXCHANGE": f"{bare}/ex", "PROJECTS": "/x/code",
        "STATE": f"{bare}/.local/state/ogun", "TEMPLATES": f"{bare}/.config/ogun/templates"}


def test_and_every_project_folder_with_its_fixed_owner_as_the_setting_writes_them(og, bare):
    conf(bare, 'projects = "~/code:/x/team=acme"\n')
    code, out, _ = og("internal", "paths")
    assert code == 0 and dict(line.split("\t") for line in out.splitlines())["PROJECTS"] == f"{bare}/code:/x/team=acme"


def test_and_a_broken_file_fails_it(og, bare):
    conf(bare, "exchange = \n")
    code, out, _ = og("internal", "paths")
    assert code == 1 and out == ""


# ── the 1Password vault: one default, read the same way by tokens and grants ──

def test_the_default_vault_is_defined_once():
    found = [f"{f.relative_to(paths.OGUN)}: {line.strip()}" for f in sorted((paths.OGUN / "src").rglob("*.py"))
             for line in f.read_text().splitlines() if 'or "Sandbox"' in line]
    assert len(found) == 1, found


def test_tokens_and_grants_read_one_vault(monkeypatch):
    from ogun.secrets import approval, github
    monkeypatch.delenv("OG_VAULT", raising=False)
    assert github.vault() == approval.grants_vault() == settings.vault() == "Sandbox"
    monkeypatch.setenv("OG_VAULT", "Shared")
    assert github.vault() == approval.grants_vault() == settings.vault() == "Shared"


