"""config: the user's own files, named files in og's config folder (beside
config.toml): registry.json, marketplaces.json, templates/, baseline.env and
appa.lock. Each may be a link, read through. Missing means none: no registry, no
plugins, no templates, og's own baseline; a command that needs one says which
file, where og looked, and what it's for. One that can't be parsed is an error,
never skipped. A baseline.env there replaces og's default whole."""

import json
import subprocess

import pytest

from ogun.core import config, paths, settings
from ogun.net import baseline
from ogun.sandbox import appa, choose, template

THREE = 'SBX_BASELINE_DOMAINS="only.example"\nSBX_BASELINE_HTTP=""\nSBX_DEFAULT_RULES_OFF=""\n'


@pytest.fixture
def cfg(home):
    """og's config folder, empty."""
    return home / ".config/ogun"


def test_a_named_file_is_in_the_folder_config_toml_is_in(home, monkeypatch, tmp_path):
    assert config.folder() == settings.file().parent == home / ".config/ogun"
    assert config.file("registry.json") == home / ".config/ogun/registry.json"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert config.file("templates") == tmp_path / "xdg/ogun/templates"


def test_an_empty_config_folder_is_no_registry_no_plugins_no_templates_and_ogs_own_baseline(cfg):
    assert paths.read_registry() is None and paths.registry_entry("x") == {}
    assert choose.marketplaces("/x") == [] and template.recipes() == []
    assert baseline.baseline_lists() == baseline.lists_in(baseline.BASELINE_FILE.read_text())
    assert appa.lock("version") == ""


# ── read through a link ──

def test_each_file_is_read_through_a_link(cfg, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "registry.json").write_text(json.dumps({"repos": {"x": {"owner": "me"}}}))
    (real / "templates").mkdir()
    (real / "templates/work.sh").write_text("#!/bin/sh\n")
    (real / "appa.lock").write_text("version v1.2.3\n")
    (real / "baseline.env").write_text(THREE)
    for name in ("registry.json", "templates", "appa.lock", "baseline.env"):
        (cfg / name).symlink_to(real / name)
    assert paths.registry_entry("x") == {"owner": "me"} and template.recipes() == ["work"]
    assert appa.lock("version") == "v1.2.3" and baseline.baseline_lists()["SBX_BASELINE_DOMAINS"] == "only.example"


def test_a_link_to_nothing_is_missing(cfg, tmp_path):
    (cfg / "registry.json").symlink_to(tmp_path / "gone.json")
    assert paths.read_registry() is None


# ── one that can't be parsed stops og, never skipped ──

@pytest.mark.parametrize(("name", "text"), [("registry.json", "{not json"), ("registry.json", "[1, 2]"),
                                            ("marketplaces.json", "{not json"), ("baseline.env", "SBX_BASELINE_DOMAINS=unquoted\n")])
def test_a_file_that_cant_be_parsed_is_an_error_naming_it(cfg, name, text):
    (cfg / name).write_text(text)
    with pytest.raises(settings.Unreadable, match=name):
        paths.read_registry() if name == "registry.json" else choose.marketplaces("/x") if name == "marketplaces.json" \
            else baseline.baseline_lists()


@pytest.mark.parametrize("name", ["registry.json", "marketplaces.json", "baseline.env"])
@pytest.mark.parametrize("how", ["not text", "a folder"])
def test_a_file_og_cant_read_at_all_is_an_error_naming_it(cfg, name, how):
    if how == "a folder":
        (cfg / name).mkdir()
    else:
        (cfg / name).write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(settings.Unreadable, match=f"{name} can't be read"):
        paths.read_registry() if name == "registry.json" else choose.marketplaces("/x") if name == "marketplaces.json" \
            else baseline.baseline_lists()


def test_og_says_it_and_stops(og, cfg):
    (cfg / "registry.json").write_text("{not json")
    code, out, err = og("project", "ls")
    assert code == 1 and "registry.json" in err and "Traceback" not in out + err


# ── a command that needs a missing file says which, where, and what for ──

def test_project_ls_with_no_registry_names_the_file_where_and_what_its_for(og, cfg):
    code, _, err = og("project", "ls")
    assert code == 1 and "~/.config/ogun/registry.json" in err and "the repos og knows" in err


def test_an_openappa_install_with_no_pin_names_the_file_where_and_what_its_for(cfg, fakes, capfd):
    assert appa.install("box") is False
    err = capfd.readouterr().err
    assert "~/.config/ogun/appa.lock" in err and "the OpenAPPA release sandboxes install" in err
    assert fakes.sbx.calls == []


def test_a_pin_set_elsewhere_that_isnt_there_is_named_where_og_looked(cfg, fakes, capfd, monkeypatch, tmp_path):
    monkeypatch.setenv("SBX_APPA_LOCK", str(tmp_path / "elsewhere/appa.lock"))
    assert appa.install("box") is False
    err = capfd.readouterr().err
    assert str(tmp_path / "elsewhere/appa.lock") in err and "~/.config/ogun/appa.lock" not in err


def test_building_with_no_templates_names_the_folder_where_and_what_its_for(og, cfg, fakes):
    code, _, err = og("template")
    assert code == 1 and "~/.config/ogun/templates" in err and "the recipes og builds sandbox images from" in err
    assert fakes.sbx.calls == []


# ── the baseline: one file, never merged ──



def test_a_baseline_env_replaces_ogs_default_whole_never_merges(cfg):
    (cfg / "baseline.env").write_text(THREE)
    got = baseline.baseline_lists()
    assert got == {"SBX_BASELINE_DOMAINS": "only.example", "SBX_BASELINE_HTTP": "", "SBX_DEFAULT_RULES_OFF": ""}


def test_an_empty_whole_host_list_allows_no_host_and_the_other_lists_still_apply(cfg, fakes):
    (cfg / "baseline.env").write_text(THREE.replace('"only.example"', '""').replace('HTTP=""', 'HTTP="h.example=GET"'))
    assert baseline.baseline()
    allows = [c[3:] for c in fakes.sbx.calls if c[:3] == ["policy", "allow", "network"]]
    assert allows == [["h.example", "--method", "GET"]]


@pytest.mark.parametrize("left_out",["SBX_BASELINE_DOMAINS", "SBX_BASELINE_HTTP", "SBX_DEFAULT_RULES_OFF"])
def test_a_baseline_env_leaving_a_list_out_stops_og_naming_it(cfg, left_out):
    (cfg / "baseline.env").write_text("".join(x + "\n" for x in THREE.splitlines() if not x.startswith(left_out + "=")))
    with pytest.raises(settings.Unreadable, match=f"baseline.env has no {left_out}"):
        baseline.baseline_lists()


def test_an_attach_with_a_list_left_out_is_one_line_never_a_traceback(og, cfg, fakes):
    (cfg / "baseline.env").write_text('SBX_BASELINE_DOMAINS="only.example"\n')
    code, out, err = og("policy")
    assert code == 1 and "baseline.env has no" in err and "Traceback" not in out + err


# ── an edit goes to the real file, through the link ──

def test_a_registry_edit_writes_through_the_link_and_names_the_real_file(cfg, tmp_path, og, home, real_git, monkeypatch):
    real = tmp_path / "real/registry.json"
    real.parent.mkdir()
    real.write_text(json.dumps({"repos": {"here": {"owner": "personal"}}}))
    (cfg / "registry.json").symlink_to(real)
    for d in ("here", "there"):
        subprocess.run(["git", "init", "-q", str(home / "Projects/personal" / d)], check=True)
    monkeypatch.chdir(home / "Projects/personal/here")
    code, out, err = og("-v", "project", "add", "there")
    assert code == 0 and (cfg / "registry.json").is_symlink()
    assert json.loads(real.read_text())["repos"]["here"]["repos"]["read"] == ["personal/there"]
    assert "real/registry.json" in out + err
