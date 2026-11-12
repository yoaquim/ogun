"""settings: og's settings come from ~/.config/ogun/config.toml (under
$XDG_CONFIG_HOME when that's set), each one overridden by an environment variable
of the same name, and fall back to its default when neither sets it. Never from a
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
    ("SBX_VAULT", github.vault, "Sandbox", "Other"),
    ("SBX_VAULT", approval.grants_vault, "Sandbox", "Other"),
    ("SBX_PROJECTS", paths.projects, f"{H}/Projects", "/x/code"),
    ("SBX_OGUN_DIR", paths.state_dir, f"{H}/.config/sbx/ogun", "/x/state"),
    ("SBX_EXCHANGE", folders.exchange, f"{H}/sandboxes.noindex", "/x/ex"),
    ("SBX_TAKE_DEST", screen.take_dest, f"{H}/Downloads", "/x/dl"),
    ("SBX_SSH_DIR", sshkeys.ssh_dir, f"{H}/.ssh", "/x/ssh"),
    ("SBX_SKILLS_STORE", create.skills_store,
     f"{H}/Library/Application Support/com.docker.sandboxes/sandboxes/agent-skills", "/x/skills"),
    ("SBX_HOST_RO_MOUNTS", lambda: ":".join(envfile.host_ro_mounts()), "", "/x/a:/x/b"),
    ("SBX_APT_TOOLS", lambda: " ".join(base.apt_tools_list().split()[len(base.OWN_TOOLS.split()):]), "", "make"),
    ("SBX_APPA_LOCK", appa.lock_file, f"{H}/.config/ogun/appa.lock", "/x/appa.lock"),
    ("SBX_SECRETS_APPROVED", approval.approved_file, f"{H}/.config/sbx/ogun/approved-secrets", "/x/secrets"),
    ("SBX_EGRESS_APPROVED", egress._approvals, f"{H}/.config/sbx/ogun/approved-egress", "/x/egress"),
    ("SBX_RM_PROBE_TIMEOUT", lambda: remove.probe_timeout(stopped=False), 120, "9"),
    ("SBX_RM_BOOT_TIMEOUT", lambda: remove.probe_timeout(stopped=True), 400, "9"),
    ("SBX_CLAUDE_UPDATE_TIMEOUT", base.update_timeout, 300, "9"),
    ("SBX_CLAUDE_UPDATE_LOG", base.update_log, "/tmp/ogun-claude-update.log", "/x/update.log"),
    ("SBX_TOKEN_NAME", github.token_name, "", "home"),
    ("SBX_TOKEN_SUFFIX", github.token_suffix, "", "-work"),
    ("SBX_PROVISION", session.provision_command, "", "/x/provision.sh"),
    ("SBX_SKILLS_DIR", create.skills_dir, "", "/x/skills-src"),
    ("SBX_GITHUB_OWNERS", lambda: " ".join(f"{k}={v}" for k, v in token.github_owners().items()), "", "acme=acme-corp"),
    ("SBX_PROTECTED_KEYS", lambda: ":".join(str(p) for p in sshkeys.protected_keys()), f"{H}/.ssh/allowed_signers",
     "/x/signer:/x/signers"),
]


def read(reader, home: Path):
    v = reader()
    return v if isinstance(v, int) else str(v).replace(str(home), H)


def want(value):
    return int(value) if value.isdigit() else value


@pytest.fixture
def bare(home, monkeypatch):
    """No setting from the environment, not even the ones the home fixture sets."""
    for n in settings.NAMES:
        monkeypatch.delenv(n, raising=False)
    return home


@pytest.mark.parametrize(("name", "reader", "default", "value"), READERS, ids=[f"{r[0]}-{i}" for i, r in enumerate(READERS)])
def test_a_setting_neither_the_file_nor_the_environment_sets_is_its_default(bare, name, reader, default, value):
    assert read(reader, bare) == default


@pytest.mark.parametrize(("name", "reader", "default", "value"), READERS, ids=[f"{r[0]}-{i}" for i, r in enumerate(READERS)])
def test_the_file_sets_it(bare, name, reader, default, value):
    conf(bare, f'{name} = "{value}"\n')
    assert read(reader, bare) == want(value)


@pytest.mark.parametrize(("name", "reader", "default", "value"), READERS, ids=[f"{r[0]}-{i}" for i, r in enumerate(READERS)])
def test_the_environment_wins_over_the_file(bare, monkeypatch, name, reader, default, value):
    conf(bare, f'{name} = "/from/the/file"\n' if not value.isdigit() else f"{name} = 77\n")
    monkeypatch.setenv(name, value)
    assert read(reader, bare) == want(value)


def test_the_file_takes_every_setting_og_reads():
    # every setting og reads from the environment, the file takes too
    assert set(settings.NAMES) == {r[0] for r in READERS}


def test_an_empty_environment_variable_is_unset_so_the_file_still_answers(bare, monkeypatch):
    conf(bare, 'SBX_VAULT = "FromFile"\n')
    monkeypatch.setenv("SBX_VAULT", "")
    assert github.vault() == "FromFile"


def test_a_number_in_the_file_is_a_number(bare):
    conf(bare, "SBX_RM_PROBE_TIMEOUT = 30\n")
    assert remove.probe_timeout(stopped=False) == 30


def test_the_file_lives_under_xdg_config_home_when_that_is_set(bare, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    conf(bare, 'SBX_VAULT = "Ignored"\n')
    (tmp_path / "xdg/ogun").mkdir(parents=True)
    (tmp_path / "xdg/ogun/config.toml").write_text('SBX_VAULT = "Xdg"\n')
    assert github.vault() == "Xdg"


def test_a_tilde_in_a_path_from_the_file_is_home(bare):
    conf(bare, 'SBX_EXCHANGE = "~/ex"\n')
    assert folders.exchange() == bare / "ex"


def test_no_file_is_every_default(bare):
    assert not (bare / ".config/ogun/config.toml").exists()
    assert github.vault() == "Sandbox"


# ── a file og can't take as its settings stops og ──

@pytest.mark.parametrize(("text", "said"), [
    ("SBX_VAULT = \n", "isn't valid TOML"),
    ('SBX_VALT = "Other"\n', "SBX_VALT isn't a setting og has"),
    ('SBX_VAULT = ["a"]\n', "SBX_VAULT must be text or a number"),
    ('[SBX_VAULT]\nx = "a"\n', "SBX_VAULT must be text or a number"),
])
def test_a_file_og_cant_read_as_its_settings_is_an_error_naming_the_file(bare, text, said):
    f = conf(bare, text)
    with pytest.raises(settings.Unreadable) as e:
        github.vault()
    assert said in str(e.value) and str(f).replace(str(bare), "~") in str(e.value)


def test_a_broken_file_stops_og_even_where_the_environment_sets_the_setting_asked_for(bare, monkeypatch):
    conf(bare, 'SBX_VALT = "Other"\n')
    monkeypatch.setenv("SBX_VAULT", "FromEnv")
    with pytest.raises(settings.Unreadable):
        github.vault()


def test_and_og_stops_on_it_saying_why_running_nothing(og, bare, fakes):
    conf(bare, 'SBX_VALT = "Other"\n')
    code, _, err = og("pass", "cub", "TOKEN")
    assert code == 1 and "~/.config/ogun/config.toml" in err and "SBX_VALT" in err
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
        for n in settings.NAMES:
            assert f'environ.get("{n}"' not in text and f'environ["{n}"]' not in text, f"{f.name} reads {n}"
    assert "_env_path" not in Path(remove.__file__).read_text() and "def _secs" not in Path(remove.__file__).read_text()


# ── what the shell's completion and og's install look at: og's own answer ──

def test_og_internal_paths_is_each_folder_the_shell_looks_in_as_og_resolves_it(og, bare):
    conf(bare, 'SBX_EXCHANGE = "~/ex"\nSBX_PROJECTS = "/x/code"\n')
    code, out, _ = og("internal", "paths")
    assert code == 0 and dict(line.split("\t") for line in out.splitlines()) == {
        "SBX_EXCHANGE": f"{bare}/ex", "SBX_PROJECTS": "/x/code",
        "SBX_OGUN_DIR": f"{bare}/.config/sbx/ogun", "TEMPLATES": f"{bare}/.config/ogun/templates"}


def test_and_every_project_folder_with_its_fixed_owner_as_the_setting_writes_them(og, bare):
    conf(bare, 'SBX_PROJECTS = "~/code:/x/team=acme"\n')
    code, out, _ = og("internal", "paths")
    assert code == 0 and dict(line.split("\t") for line in out.splitlines())["SBX_PROJECTS"] == f"{bare}/code:/x/team=acme"


def test_and_a_broken_file_fails_it(og, bare):
    conf(bare, "SBX_EXCHANGE = \n")
    code, out, _ = og("internal", "paths")
    assert code == 1 and out == ""


# ── the 1Password vault: one default, read the same way by tokens and grants ──

def test_the_default_vault_is_defined_once():
    found = [f"{f.relative_to(paths.OGUN)}: {line.strip()}" for f in sorted((paths.OGUN / "src").rglob("*.py"))
             for line in f.read_text().splitlines() if 'or "Sandbox"' in line]
    assert len(found) == 1, found


def test_tokens_and_grants_read_one_vault(monkeypatch):
    from ogun.secrets import approval, github
    monkeypatch.delenv("SBX_VAULT", raising=False)
    assert github.vault() == approval.grants_vault() == settings.vault() == "Sandbox"
    monkeypatch.setenv("SBX_VAULT", "Shared")
    assert github.vault() == approval.grants_vault() == settings.vault() == "Shared"


