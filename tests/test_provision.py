"""Provisioning: what og does to a new sandbox beyond its own setup is settings, each
unset by default. SBX_PROVISION: a command run inside it at create and on every
attach. SBX_SKILLS_DIR: a folder mirrored into sbx's shared skills store. A host
folder to mount read-only (a team's agent config, say) is an entry in SBX_HOST_RO_MOUNTS.
Unset, og does none of it and says so once."""

import pytest

from ogun.core import config
from ogun.sandbox import base, create, envfile, session
from ogun.secrets import sshkeys


@pytest.fixture
def box(fakes, home, monkeypatch):
    """Sandbox box, reaching no agent, with no key folder; nothing said yet."""
    monkeypatch.setenv("SBX_SSH_DIR", str(home / "ssh"))
    monkeypatch.setenv("SBX_EXCHANGE", str(home / "exchange"))
    monkeypatch.setattr(config, "_said", set())
    fakes.sbx.answer(["exec", "box"], stdout="agent:none\n", has=sshkeys.PROBE)
    return fakes.sbx


def provisions(s) -> list[list[str]]:
    return [c for c in s.calls if c[:4] == ["exec", "box", "bash", "-lc"] and "run-me" in c[4]]


# ── the provision command ──

def test_unset_setup_runs_no_provision_command_and_says_so_once(box, capfd):
    assert base.setup("box") and base.setup("box")
    assert provisions(box) == []
    assert "".join(capfd.readouterr()).count("no provision command (SBX_PROVISION)") == 1


def test_set_it_runs_inside_the_sandbox_a_leading_tilde_your_macs_home(box, home, monkeypatch):
    monkeypatch.setenv("SBX_PROVISION", "~/setup-repo/run-me --all")
    assert base.setup("box")
    assert [c[4] for c in provisions(box)] == [f"{home}/setup-repo/run-me --all"]


def test_a_failing_provision_command_stops_setup_nothing_after_it_runs(box, monkeypatch, capfd):
    monkeypatch.setenv("SBX_PROVISION", "run-me")
    box.answer(["exec", "box"], code=1, has="run-me")
    assert base.setup("box") is False
    assert "the provision command failed (SBX_PROVISION)" in "".join(capfd.readouterr())
    assert not any("sandbox-docker.sh" in " ".join(c) for c in box.calls)


def test_every_attach_runs_it_again_and_a_failure_only_warns(box, monkeypatch, capfd):
    monkeypatch.setenv("SBX_PROVISION", "run-me")
    box.answer(["exec", "box"], code=1, has="run-me")
    session.upkeep("box", "", existed=True)
    assert len(provisions(box)) == 1
    assert "the provision command failed" in "".join(capfd.readouterr())


def ship_writes(box) -> list[str]:
    """What each call that writes og ship's script into the sandbox sent it."""
    return [box.stdin[i] for i, c in enumerate(box.calls) if "workflow-push-request.sh" in " ".join(c)]


def test_every_attach_and_setup_put_ogs_own_ship_script_on_the_sandboxs_path(box):
    from ogun.core import paths
    mine = (paths.SCRIPTS / "workflow-push-request.sh").read_text()
    session.upkeep("box", "", existed=True)
    assert ship_writes(box) == [mine]
    assert base.setup("box") and ship_writes(box) == [mine, mine]
    assert any("~/.local/bin/workflow-push-request.sh" in " ".join(c) for c in box.calls)


def test_a_ship_script_that_cant_be_written_warns_and_the_rest_goes_on(box, capfd):
    box.answer(["exec", "-i", "box"], code=1, has="workflow-push-request.sh")
    session.upkeep("box", "", existed=True)
    assert "couldn't put og ship's script in box" in "".join(capfd.readouterr())


def test_unset_an_attach_runs_none(box):
    session.upkeep("box", "", existed=True)
    assert provisions(box) == []


# ── the skills mirror ──

@pytest.fixture
def skills(home, monkeypatch):
    monkeypatch.setattr(config, "_said", set())
    monkeypatch.setenv("SBX_SKILLS_STORE", str(home / "store"))
    (home / "my-skills/outline").mkdir(parents=True)
    (home / "my-skills/outline/SKILL.md").write_text("outline\n")
    yield home
    import subprocess
    subprocess.run(["chmod", "-R", "u+w", str(home / "store")], capture_output=True)


def test_unset_no_skills_are_mirrored_said_once_and_a_create_goes_on(skills, capfd):
    assert create.skills() and create.skills()
    assert not (skills / "store").exists()
    assert "".join(capfd.readouterr()).count("no skills folder (SBX_SKILLS_DIR)") == 1


def test_set_that_folder_is_mirrored_a_leading_tilde_home(skills, monkeypatch):
    monkeypatch.setenv("SBX_SKILLS_DIR", "~/my-skills")
    assert create.skills() and (skills / "store/outline/SKILL.md").read_text() == "outline\n"


def test_a_skills_folder_that_isnt_there_fails_it(skills, monkeypatch, capfd):
    monkeypatch.setenv("SBX_SKILLS_DIR", "~/none")
    assert create.skills() is False and "SBX_SKILLS_DIR" in "".join(capfd.readouterr())


def test_og_skills_with_none_set_says_so_and_fails(og, skills):
    code, out, err = og("skills")
    assert code == 1 and "SBX_SKILLS_DIR" in out + err


# ── a host folder's mount: an entry in SBX_HOST_RO_MOUNTS, nothing of its own ──

def env(home, d=None):
    from ogun.exchange import folders
    d = d or str(home / "Projects/personal/ef")
    return envfile.env_yaml("ef", d, folders.exchange() / "boxes" / "ef").splitlines()


def test_no_host_folder_mount_unless_the_read_only_mounts_name_it(home, monkeypatch):
    (home / "agent-config").mkdir()
    monkeypatch.setenv("SBX_HOST_RO_MOUNTS", str(home / "reference"))
    assert not any("agent-config" in x for x in env(home))


def test_named_with_a_leading_tilde_it_mounts_read_only(home, monkeypatch):
    (home / "agent-config").mkdir()
    monkeypatch.setenv("SBX_HOST_RO_MOUNTS", "~/agent-config")
    lines = env(home)
    i = lines.index(f'  - path: "{home}/agent-config"')
    assert lines[i + 1] == "    readOnly: true"


def test_a_workspace_that_is_one_of_them_is_mounted_once(home, monkeypatch):
    (home / "agent-config").mkdir()
    monkeypatch.setenv("SBX_HOST_RO_MOUNTS", "~/agent-config")
    assert sum("agent-config" in x for x in env(home, d=str(home / "agent-config"))) == 1
