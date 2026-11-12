"""config: the user's own files, named files in og's config folder (beside
config.toml): registry.json, marketplaces.json, templates/ and appa.lock. Each may be a link, read through. Missing means none: no registry, no
plugins, no templates, og's own baseline; a command that needs one says which
file, where og looked, and what it's for. One that can't be parsed is an error,
never skipped. A [baseline] table in config.toml replaces og's default whole."""

import json
import re
import subprocess

import pytest

from ogun.core import config, paths, settings
from ogun.net import baseline
from ogun.sandbox import appa, choose, template

THREE = '[baseline]\ndomains = ["only.example"]\nhttp = []\ndefault_rules_off = []\n'


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
    assert baseline.baseline_lists() == baseline.own() and baseline.own()["domains"]
    assert appa.lock("version") == ""


# ── read through a link ──

def test_each_file_is_read_through_a_link(cfg, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "registry.json").write_text(json.dumps({"repos": {"x": {"owner": "me"}}}))
    (real / "templates").mkdir()
    (real / "templates/work.sh").write_text("#!/bin/sh\n")
    (real / "appa.lock").write_text("version v1.2.3\n")
    for name in ("registry.json", "templates", "appa.lock"):
        (cfg / name).symlink_to(real / name)
    assert paths.registry_entry("x") == {"owner": "me"} and template.recipes() == ["work"]
    assert appa.lock("version") == "v1.2.3"


def test_a_link_to_nothing_is_missing(cfg, tmp_path):
    (cfg / "registry.json").symlink_to(tmp_path / "gone.json")
    assert paths.read_registry() is None


# ── one that can't be parsed stops og, never skipped ──

@pytest.mark.parametrize(("name", "text"), [("registry.json", "{not json"), ("registry.json", "[1, 2]"),
                                            ("marketplaces.json", "{not json")])
def test_a_file_that_cant_be_parsed_is_an_error_naming_it(cfg, name, text):
    (cfg / name).write_text(text)
    with pytest.raises(settings.Unreadable, match=name):
        paths.read_registry() if name == "registry.json" else choose.marketplaces("/x")


@pytest.mark.parametrize("name", ["registry.json", "marketplaces.json"])
@pytest.mark.parametrize("how", ["not text", "a folder"])
def test_a_file_og_cant_read_at_all_is_an_error_naming_it(cfg, name, how):
    if how == "a folder":
        (cfg / name).mkdir()
    else:
        (cfg / name).write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(settings.Unreadable, match=f"{name} can't be read"):
        paths.read_registry() if name == "registry.json" else choose.marketplaces("/x")


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
    monkeypatch.setattr("ogun.sandbox.appa.lock_file", lambda: tmp_path / "elsewhere/appa.lock")
    assert appa.install("box") is False
    err = capfd.readouterr().err
    assert str(tmp_path / "elsewhere/appa.lock") in err and "~/.config/ogun/appa.lock" not in err


def test_building_with_no_templates_names_the_folder_where_and_what_its_for(og, cfg, fakes):
    code, _, err = og("template")
    assert code == 1 and "~/.config/ogun/templates" in err and "the recipes og builds sandbox images from" in err
    assert fakes.sbx.calls == []


# ── the baseline: one file, never merged ──



def test_a_baseline_table_replaces_ogs_default_whole_never_merges(cfg):
    (cfg / "config.toml").write_text(THREE)
    assert baseline.baseline_lists() == {"domains": ["only.example"], "http": [], "default_rules_off": []}


def test_an_empty_whole_host_list_allows_no_host_and_the_other_lists_still_apply(cfg, fakes):
    (cfg / "config.toml").write_text(THREE.replace('["only.example"]', '[]').replace('http = []', 'http = ["h.example=GET"]'))
    assert baseline.baseline()
    allows = [c[3:] for c in fakes.sbx.calls if c[:3] == ["policy", "allow", "network"]]
    assert allows == [["h.example", "--method", "GET"]]


@pytest.mark.parametrize("left_out", ["domains", "http", "default_rules_off"])
def test_a_baseline_table_leaving_a_list_out_stops_og_naming_it(cfg, left_out):
    (cfg / "config.toml").write_text("".join(x + "\n" for x in THREE.splitlines() if not x.startswith(left_out + " =")))
    with pytest.raises(settings.Unreadable, match=rf"\[baseline\] has no {left_out}"):
        baseline.baseline_lists()


@pytest.mark.parametrize(("text", "says"), [
    ('[baseline]\ndomains = "a.example"\nhttp = []\ndefault_rules_off = []\n', "baseline.domains must be a list of text"),
    ('[baseline]\ndomains = []\nhttp = []\ndefault_rules_off = []\nhosts = []\n', "baseline.hosts isn't a key"),
    ('baseline = "x"\n', "baseline must be a [baseline] table"),
])
def test_a_baseline_table_og_cant_take_stops_og_naming_why(cfg, text, says):
    (cfg / "config.toml").write_text(text)
    with pytest.raises(settings.Unreadable, match=re.escape(says)):
        baseline.baseline_lists()


def test_an_attach_with_a_list_left_out_is_one_line_never_a_traceback(og, cfg, fakes):
    (cfg / "config.toml").write_text('[baseline]\ndomains = ["only.example"]\n')
    code, out, err = og("policy")
    assert code == 1 and "[baseline] has no" in err and "Traceback" not in out + err


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
