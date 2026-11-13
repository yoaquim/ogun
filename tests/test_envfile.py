"""envfile: a new sandbox's .sbxenv.yaml, every folder it mounts and which are
read-only, written into the workspace with og's files kept out of git."""

import subprocess

import pytest

from ogun.sandbox import envfile


def env_lines(home, name="ef", d=None, **kw) -> list[str]:
    from ogun.exchange import folders
    d = d or str(home / "Projects/personal/ef")
    return envfile.env_yaml(name, d, folders.exchange() / "boxes" / name, **kw).splitlines()


def test_the_env_file_starts_with_the_workspace_and_mounts_no_host_folder_of_its_own(home, monkeypatch):
    # a host folder is mounted only when host_ro_mounts names it (test_provision.py)
    (home / "agent-config").mkdir()
    monkeypatch.setenv("OG_HOST_RO_MOUNTS", "")
    lines = env_lines(home)
    assert lines[:6] == ['schemaVersion: "1"', "name: ef", "agent: claude", "workspace:",
                         f'  path: "{home}/Projects/personal/ef"', "  clone: true"]
    assert not any("agent-config" in x for x in lines)


def test_a_workspace_that_is_a_host_mount_isnt_mounted_twice(home, monkeypatch):
    (home / "agent-config").mkdir()
    monkeypatch.setenv("OG_HOST_RO_MOUNTS", f"{home}/agent-config")
    lines = env_lines(home, d=str(home / "agent-config"))
    assert sum("agent-config" in x for x in lines) == 1


def test_related_marketplaces_and_ssh_keys_read_only_the_workspace_never_again(home, monkeypatch):
    monkeypatch.setenv("OG_HOST_RO_MOUNTS", "")
    d = str(home / "Projects/personal/ef")
    lines = env_lines(home, d=d, related=[d, "/r/one"], marketplaces=["/m/#1"], ssh_keys="/k")
    for p in ('"/k"', "/r/one", '"/m/#1"'):
        assert lines[lines.index(f"  - path: {p}") + 1] == "    readOnly: true"
    assert lines.count(f'  path: "{d}"') == 1 and f"  - path: {d}" not in lines


def test_the_exchange_its_own_out_and_shared_folder_writable_the_rest_read_only(home, monkeypatch):
    from ogun.exchange import folders
    monkeypatch.setenv("OG_HOST_RO_MOUNTS", "")
    lines, ex = env_lines(home), folders.exchange()
    ro = {x: lines[lines.index(f'  - path: "{x}"') + 1] == "    readOnly: true"
          for x in (f"{ex}/inbox", f"{ex}/shared", f"{ex}/shared/ef", f"{ex}/boxes/ef/out", f"{ex}/boxes/ef/in")}
    assert ro == {f"{ex}/inbox": True, f"{ex}/shared": True, f"{ex}/shared/ef": False, f"{ex}/boxes/ef/out": False,
                  f"{ex}/boxes/ef/in": True}


def test_a_host_mount_another_rule_already_mounts_is_skipped(home, monkeypatch):
    (home / "reference").mkdir()
    monkeypatch.setenv("OG_HOST_RO_MOUNTS", f"{home}/reference:{home}/Projects/personal/rel")
    (home / "Projects/personal/rel").mkdir(parents=True)
    lines = env_lines(home, related=[str(home / "Projects/personal/rel")])
    assert f'  - path: "{home}/reference"' in lines and f'  - path: "{home}/Projects/personal/rel"' not in lines


def test_a_template_image_only_when_there_is_one(home, monkeypatch):
    monkeypatch.setenv("OG_HOST_RO_MOUNTS", "")
    assert env_lines(home, image="ogun-work:latest")[-2:] == ["sandboxOptions:", "  template: ogun-work:latest"]
    assert "sandboxOptions:" not in env_lines(home)


def test_the_env_file_written_its_mounts_said_and_the_inbox_made(home, real_git, capfd):
    d = home / "Projects/personal/w"
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    env = envfile.write_env(str(d), "workspace:\nadditionalWorkspaces:\n  - path: /x\n")
    assert env == d / ".sbxenv.yaml" and env.read_text().endswith("  - path: /x\n") and (d / ".inbox").is_dir()
    assert "1 folders mounted besides the workspace" in capfd.readouterr().out


def test_an_env_file_that_cant_be_written_is_said_and_nothing_follows(home, capfd):
    assert envfile.write_env(str(home / "nowhere"), "x\n") is None
    assert "couldn't write" in capfd.readouterr().err


def test_ogs_files_go_in_the_repos_own_exclude_once_from_a_subfolder_and_a_linked_worktree(recipes, tmp_path):
    d, wt = recipes / "Projects/personal/exrepo", tmp_path / "exwt"
    (d / "sub").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i"],
                   check=True)
    subprocess.run(["git", "-C", str(d), "worktree", "add", "-q", str(wt)], check=True, capture_output=True)
    ex = d / ".git/info/exclude"
    envfile.git_excludes(str(d))
    envfile.git_excludes(str(d))
    lines = ex.read_text().splitlines()
    assert lines.count(".sbxenv.yaml") == 1 and lines.count(".inbox/") == 1
    ex.write_text("")
    envfile.git_excludes(str(d / "sub"))
    assert not (d / "sub/.git").exists() and ".inbox/" in ex.read_text().splitlines()
    ex.write_text("")
    envfile.git_excludes(str(wt))
    assert (wt / ".git").is_file() and ".sbxenv.yaml" in ex.read_text().splitlines()


# ── a mount reached through a link: the real path mounted, the link kept to make inside ──

def test_a_host_mount_named_through_a_link_mounts_its_real_path(home, monkeypatch):
    (home / "dotfiles/claude").mkdir(parents=True)
    (home / "sandbox-setup").symlink_to(home / "dotfiles/claude")
    monkeypatch.setenv("OG_HOST_RO_MOUNTS", "~/sandbox-setup")
    d = str(home / "Projects/personal/ef")
    assert envfile.host_mounts(d) == [(str(home / "sandbox-setup"), str(home / "dotfiles/claude"))]
    assert f'  - path: "{home}/dotfiles/claude"' in env_lines(home) and not any("sandbox-setup" in x for x in env_lines(home))
    assert envfile.linked(str(home / "sandbox-setup")) == (str(home / "sandbox-setup"), str(home / "dotfiles/claude"))


def test_a_plain_folder_has_no_link(home):
    (home / "plain").mkdir()
    assert envfile.linked(str(home / "plain")) is None


# ── a link in a mounted folder whose target no mount covers: said, never mounted ──

@pytest.fixture
def setup_dir(home):
    s = home / "dotfiles/claude"
    (s / ".git").mkdir(parents=True)
    (home / "notes").mkdir()
    (home / "notes/agent.md").write_text("x")
    (s / "CLAUDE.md").symlink_to(home / "notes/agent.md")      # outside every mount
    (s / "inside.md").write_text("y")
    (s / "same.md").symlink_to(s / "inside.md")                # inside the mount
    (s / ".git/hook").symlink_to(home / "notes/agent.md")      # in .git: never looked at
    (s / "gone.md").symlink_to(home / "nowhere")               # nothing there on the Mac either
    return s


def test_only_a_link_to_something_outside_every_mount_is_found(setup_dir, home):
    found, cut = envfile.outside_links([str(setup_dir)], [str(setup_dir)])
    assert found == [(str(setup_dir / "CLAUDE.md"), str(home / "notes/agent.md"))] and not cut


def test_a_target_another_mount_covers_isnt_found(setup_dir, home):
    assert envfile.outside_links([str(setup_dir)], [str(setup_dir), str(home / "notes")])[0] == []


def test_looking_stops_after_the_cap_and_says_so(setup_dir):
    assert envfile.outside_links([str(setup_dir)], [str(setup_dir)], cap=1)[1] is True


def test_each_outside_link_is_said_with_the_folder_that_would_cover_it(setup_dir, capfd):
    envfile.say_outside_links([str(setup_dir)], [str(setup_dir)])
    err = capfd.readouterr().err
    assert "~/dotfiles/claude/CLAUDE.md links to ~/notes/agent.md, which this sandbox doesn't mount" in err
    assert "add ~/notes to host_ro_mounts" in err
