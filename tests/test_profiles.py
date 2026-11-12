"""Profiles: one config.toml with a section per profile ([profiles.<name>]), and
each Mac told which to use: OG_PROFILE, else the one-line ~/.config/ogun/profile.
Never guessed (no machine name, no file of the Mac's own). The profile's name is the label the
registry's `profiles` lists, MCP servers, marketplaces and the default template
match; its token settings name the 1Password items og uses."""

import pytest

from ogun.core import config, settings
from ogun.sandbox import template
from ogun.secrets import github

BOTH = '[profiles.home]\nSBX_TOKEN_NAME = "desk"\n\n[profiles.work]\nSBX_TOKEN_SUFFIX = "-work"\n'


@pytest.fixture
def cfg(home, monkeypatch):
    monkeypatch.delenv("OG_PROFILE", raising=False)
    d = home / ".config/ogun"

    def write(text=BOTH, profile=None):
        (d / "config.toml").write_text(text)
        if profile is not None:
            (d / "profile").write_text(profile)
        return d
    return write


# ── which profile: told, never guessed ──

def test_no_profile_chosen_is_none_and_only_the_shared_settings_apply(cfg):
    cfg('SBX_VAULT = "Shared"\n[profiles.work]\nSBX_VAULT = "Office"\n')
    assert settings.profile() == "" and settings.get("SBX_VAULT") == "Shared"


def test_the_profile_file_chooses_and_its_section_wins_over_the_shared_settings(cfg):
    cfg('SBX_VAULT = "Shared"\nSBX_TOKEN_NAME = "x"\n[profiles.work]\nSBX_VAULT = "Office"\n', profile="work\n")
    assert settings.profile() == "work"
    assert (settings.get("SBX_VAULT"), settings.get("SBX_TOKEN_NAME")) == ("Office", "x")


def test_og_profile_wins_over_the_file_and_the_environment_over_both(cfg, monkeypatch):
    cfg(BOTH + '[profiles.other]\nSBX_VAULT = "Other"\n', profile="work")
    monkeypatch.setenv("OG_PROFILE", "other")
    assert settings.profile() == "other" and settings.get("SBX_VAULT") == "Other"
    monkeypatch.setenv("SBX_VAULT", "Env")
    assert settings.get("SBX_VAULT") == "Env"


def test_every_profile_is_listed_with_its_own_settings(cfg):
    cfg()
    assert settings.profiles() == {"home": {"SBX_TOKEN_NAME": "desk"}, "work": {"SBX_TOKEN_SUFFIX": "-work"}}


@pytest.mark.parametrize(("text", "profile", "said"), [
    (BOTH, "hmoe", "no [profiles.hmoe]"),                       # a typo never reads as no profile
    ("", "work", "no [profiles.work]"),
    (BOTH, "has space", "isn't a profile name"),
    (BOTH, "../up", "isn't a profile name"),
    ('profiles = "work"\n', "", "profiles must be"),
    ('[profiles]\nwork = "x"\n', "", "profiles.work must be"),
    ('[profiles.work]\nSBX_VALT = "x"\n', "", "SBX_VALT isn't a setting og has"),
    ('[profiles.work]\nSBX_VAULT = ["x"]\n', "", "SBX_VAULT must be text or a number"),
])
def test_a_profile_og_cant_use_stops_og(cfg, text, profile, said):
    cfg(text, profile=profile)
    with pytest.raises(settings.Unreadable, match=said.replace("[", r"\[").replace(".", r"\.")):
        settings.get("SBX_VAULT")


def test_a_profile_file_og_cant_read_stops_og(cfg, home):
    cfg()
    (home / ".config/ogun/profile").mkdir()
    with pytest.raises(settings.Unreadable, match="profile"):
        settings.profile()


def test_the_profile_file_is_one_of_the_config_folders_named_files(home):
    assert config.file("profile") == home / ".config/ogun/profile"


# ── the profile's name is the label ──

def test_the_default_template_is_the_profiles(cfg):
    cfg(profile="work")
    assert template.machine() == "work"


def test_no_profile_no_default_template_said_once(cfg, capfd, monkeypatch):
    monkeypatch.setattr(config, "_said", set())
    cfg()
    assert template.machine() == "" and template.machine() == ""
    assert capfd.readouterr().err.count("no og profile chosen") == 1


# ── token items: og's own, and the ones this Mac may use ──

def test_a_profile_with_a_token_name_mints_into_it_and_falls_back_to_the_other_profiles_items(cfg):
    cfg(profile="home")
    assert github.item("umbrella") == "github-pat-umbrella-desk"
    assert github.items("umbrella") == ["github-pat-umbrella-desk", "github-pat-umbrella-work"]


def test_a_profile_with_a_suffix_uses_only_items_ending_in_it(cfg):
    cfg(profile="work")
    assert github.item("initech") == "github-pat-initech-work"
    assert github.items("initech") == ["github-pat-initech-work"]
    assert github.item_valid_for("initech", "github-pat-initech-work")
    assert not github.item_valid_for("initech", "github-pat-initech-desk")


def test_an_items_owner_is_read_against_every_profiles_token_name(cfg):
    cfg('[profiles.home]\nSBX_TOKEN_NAME = "den"\n[profiles.office]\n', profile="home")
    assert github.item_owner("github-pat-foo-office") == "foo"
    assert github.item_owner("github-pat-foo-office-den") == "foo-office"
    assert github.item_owner("github-pat-foo-desk") is None


def test_with_no_profile_and_no_token_name_og_cant_name_its_item_and_says_so(cfg):
    cfg()
    with pytest.raises(settings.Unreadable, match="SBX_TOKEN_NAME"):
        github.item("umbrella")


def test_a_token_name_set_with_no_profile_still_names_its_item(cfg):
    cfg('SBX_TOKEN_NAME = "home"\n')
    assert github.items("umbrella") == ["github-pat-umbrella-home"]


@pytest.mark.parametrize("name", ["Has-Caps", "a b", "-lead"])
def test_a_token_name_that_isnt_a_plain_word_stops_og(cfg, name):
    cfg(f'SBX_TOKEN_NAME = "{name}"\n')
    with pytest.raises(settings.Unreadable, match="SBX_TOKEN_NAME"):
        github.item("umbrella")


def test_another_profiles_name_that_cant_end_an_item_is_named_as_that_profile(cfg):
    cfg(BOTH + "[profiles.Team_A]\n", profile="home")
    with pytest.raises(settings.Unreadable, match=r"profile 'Team_A'.*set SBX_TOKEN_NAME in that profile"):
        github.items("hooli")


def test_another_profile_without_a_token_name_of_its_own_takes_the_shared_one_not_its_name(cfg):
    cfg('SBX_TOKEN_NAME = "common"\n[profiles.home]\nSBX_TOKEN_NAME = "desk"\n[profiles.work]\n', profile="home")
    assert github.items("foo") == ["github-pat-foo-desk", "github-pat-foo-common"]
    assert github.item_owner("github-pat-foo-common") == "foo"


@pytest.mark.parametrize("text", [
    '[profiles.home]\nSBX_TOKEN_NAME = "home-work"\n[profiles.work]\n',
    '[profiles.work]\n[profiles.home]\nSBX_TOKEN_NAME = "home-work"\n',
])
def test_endings_one_of_which_ends_the_other_stop_og_rather_than_misread_an_owner(cfg, text):
    cfg(text, profile="work")
    with pytest.raises(settings.Unreadable, match=r"endings home-work and work overlap"):
        github.item_owner("github-pat-foo-home-work")


def test_two_profiles_may_share_an_ending(cfg):
    cfg('[profiles.a]\nSBX_TOKEN_NAME = "x"\n[profiles.b]\nSBX_TOKEN_NAME = "x"\n', profile="a")
    assert github.items("foo") == ["github-pat-foo-x"]


def test_an_ending_that_ends_another_without_a_dash_is_no_overlap(cfg):
    # the dash marks where an ending starts: github-pat-foo-awork can only be foo's awork token
    cfg('[profiles.a]\nSBX_TOKEN_NAME = "awork"\n[profiles.work]\n', profile="a")
    assert (github.item_owner("github-pat-foo-awork"), github.item_owner("github-pat-foo-work")) == ("foo", "foo")


def test_a_profiles_empty_token_name_masks_the_shared_one_for_the_others_too(cfg):
    # as that profile reads it: its own setting, empty, wins over the shared one, so its name ends its items
    cfg('SBX_TOKEN_NAME = "common"\n[profiles.home]\nSBX_TOKEN_NAME = "desk"\n[profiles.work]\nSBX_TOKEN_NAME = ""\n',
        profile="home")
    assert github.items("foo") == ["github-pat-foo-desk", "github-pat-foo-work"]
    assert github.item_owner("github-pat-foo-work") == "foo"


def test_a_profile_chosen_with_no_settings_file_at_all_says_the_file_is_missing(home, monkeypatch):
    monkeypatch.setenv("OG_PROFILE", "home")
    (home / ".config/ogun/config.toml").unlink(missing_ok=True)
    with pytest.raises(settings.Unreadable, match=r"there's no ~/\.config/ogun/config\.toml, where \[profiles\.home\] goes"):
        settings.profile()


