"""cli: og as a command from anywhere, cron's bare PATH included: Homebrew's
folders go ahead of a PATH that lacks them, so sbx, op and the tools og runs are
found; a folder already on PATH stays where it is."""

import os

from ogun import cli


def brew(tmp_path, *have):
    dirs = tuple(str(tmp_path / d) for d in ("usr-local-bin", "opt-homebrew-bin"))
    for d in have:
        (tmp_path / d).mkdir()
    return dirs


def test_a_bare_path_gets_homebrews_folders_ahead_the_native_one_frontmost(tmp_path):
    local, native = brew(tmp_path, "usr-local-bin", "opt-homebrew-bin")
    assert cli.with_brew("/usr/bin:/bin", (local, native)) == f"{native}:{local}:/usr/bin:/bin"


def test_a_folder_already_on_path_stays_where_it_is(tmp_path):
    local, native = brew(tmp_path, "usr-local-bin", "opt-homebrew-bin")
    assert cli.with_brew(f"/usr/bin:{native}", (local, native)) == f"{local}:/usr/bin:{native}"


def test_a_folder_this_mac_doesnt_have_is_left_out(tmp_path):
    local, native = brew(tmp_path, "opt-homebrew-bin")
    assert cli.with_brew("/usr/bin", (local, native)) == f"{native}:/usr/bin"


def test_an_empty_path_is_only_homebrews(tmp_path):
    local, native = brew(tmp_path, "opt-homebrew-bin")
    assert cli.with_brew("", (local, native)) == native


def test_og_runs_with_them_on_its_path(og, tmp_path, monkeypatch):
    local, native = brew(tmp_path, "opt-homebrew-bin")
    monkeypatch.setattr(cli, "BREW", (local, native))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    og("help")
    assert os.environ["PATH"].split(":")[0] == native


def test_the_record_names_the_command_as_typed_whatever_the_environment_says(og, monkeypatch):
    from ogun.core import log
    monkeypatch.setenv("OGUN_COMMAND", "something else")
    og("help")
    assert log.COMMAND == "og help"
