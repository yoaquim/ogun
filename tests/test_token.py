"""token: og token [<owner>] [<days>], a sandbox's GitHub token minted or rotated.
GitHub's form opens pre-filled (the owner, the lifetime, the permissions); a
person generates the token and saves it over the 1Password item's credential;
og checks the item holds a NEW token, asking again in place rather than sending
anyone to mint a second, and only then records when it expires, for the
expiry warning. The token is never printed. `open` records the URL it got; op
answers each `op read` in turn."""

import datetime

import pytest

from conftest import MAC_PROFILES, use_profile

FORM = "https://github.com/settings/personal-access-tokens/new"
READ = "read -n op://Sandbox/github-pat-{}-desk/credential"


@pytest.fixture
def mint(og, fakes, home, stand_in, monkeypatch):
    """og token, with the credential the item holds before the form (before=) and
    at each read after it (after=, one per Enter); keys is what's typed."""
    monkeypatch.setenv("OG_VAULT", "Sandbox")
    use_profile(home, "home")
    url = home / "opened"
    stand_in("open", f'printf "%s\\n" "$1" > "{url}"')

    def run(*args, before="", after=("github_pat_new",), keys="\n"):
        url.unlink(missing_ok=True)
        fakes.op.clear()
        for cred in (before, *after):
            fakes.op.answer(["read"], stdout=cred, code=0 if cred else 1, once=True)
        fakes.op.answer(["read"], code=1)   # every read after those: nothing there
        code, out, err = og("token", *args, stdin=keys)
        reads = [" ".join(c) for c in fakes.op.calls if c[:1] == ["read"]]
        return code, out + err, url.read_text().strip() if url.exists() else None, reads

    return run


def expiry(home, owner):
    f = home / f".local/state/ogun/tokens/github-{owner}.expires"
    return f.read_text().strip() if f.exists() else None


def in_days(n: int) -> str:
    return (datetime.date.today() + datetime.timedelta(days=n)).isoformat()


# ── the lifetime: the same days pre-fill the form and are recorded ──

def test_no_lifetime_is_60_days_in_the_form_and_recorded_as_today_plus_60(mint, home):
    code, _, url, _ = mint("personal")
    assert code == 0 and "expires_in=60&" in url and expiry(home, "personal") == in_days(60)


def test_an_owner_and_90_days_name_the_owner_as_its_github_owner_and_record_90(mint, home):
    code, _, url, _ = mint("acme", "90")
    assert code == 0 and "expires_in=90&" in url and "&target_name=acme&" in url
    assert expiry(home, "acme") == in_days(90)


def test_no_owner_is_personal_and_the_form_names_no_github_owner_so_its_your_own(mint, home):
    code, _, url, reads = mint()
    assert code == 0 and "target_name=" not in url and reads[0] == READ.format("personal")


# ── github_owners: a folder whose GitHub owner has another name ──

def test_a_folder_named_in_sbx_github_owners_opens_the_form_for_that_github_owner(mint, monkeypatch):
    monkeypatch.setenv("OG_GITHUB_OWNERS", "acme=acme-corp personal=jdoe")
    assert "&target_name=acme-corp&" in mint("acme")[2]
    assert "&target_name=jdoe&" in mint()[2]
    assert "&target_name=other&" in mint("other")[2]


@pytest.mark.parametrize("bad", ["acme", "acme=", "=acme-corp", "acme=acme corp=", "Acme=acme-corp", "acme=acme/corp"])
def test_a_malformed_sbx_github_owners_stops_og_naming_it(mint, monkeypatch, bad):
    monkeypatch.setenv("OG_GITHUB_OWNERS", bad)
    code, out, url, _ = mint("acme")
    assert code == 1 and url is None and "github_owners" in out


def test_the_form_names_the_item_and_asks_for_exactly_these_permissions(mint):
    _, _, url, _ = mint("acme", "30")
    assert url.startswith(FORM + "?") and f"name=github-pat-acme-desk-{datetime.date.today().isoformat()}&" in url
    assert url.endswith("&target_name=acme&expires_in=30&contents=write&pull_requests=write&actions=read&statuses=read")
    assert "description=sbx%20proxy%20token%20(docs/secrets.md)" in url


def test_366_githubs_maximum_is_accepted_and_a_leading_zero_is_decimal(mint):
    assert "expires_in=366&" in mint("personal", "366")[2]
    assert "expires_in=90&" in mint("personal", "090")[2]


@pytest.mark.parametrize("days", ["367", "0", "-5", "abc", "1.5", "none"])
def test_days_out_of_range_are_refused_with_the_usage_and_the_form_never_opens(mint, days):
    code, out, url, reads = mint("personal", days)
    assert code == 1 and url is None and reads == []
    assert "from 1 to 366" in out and "og token [<owner>] [<days>]" in out


def test_a_lone_number_is_a_lifetime_not_an_owner_refused_with_the_fix(mint):
    code, out, url, _ = mint("90")
    assert code == 1 and url is None and "og token personal 90" in out


@pytest.mark.parametrize("owner", ["Umbrella", "hooli tools", "a_b", "-x"])
def test_an_owner_thats_no_folder_key_is_refused_before_the_form(mint, owner):
    code, out, url, _ = mint(owner)
    assert code == 1 and url is None and "not an owner key" in out


def test_a_capitalised_owner_is_told_its_lowercase_folder(mint):
    assert "e.g. og token umbrella" in mint("Umbrella")[1]


def test_any_owner_key_is_taken_as_typed_with_no_special_names(mint):
    code, _, url, _ = mint("acme-labs")
    assert code == 0 and "&target_name=acme-labs&" in url


def test_more_than_an_owner_and_days_is_usage(mint):
    code, out, url, _ = mint("umbrella", "30", "extra")
    assert code == 1 and url is None and "usage: og token" in out


# ── the credential: read before and after, never printed ──

def test_the_credential_is_read_from_the_forms_item_before_and_after_and_never_printed(mint):
    code, out, _, reads = mint("umbrella")
    assert code == 0 and reads == [READ.format("umbrella")] * 2 and "github_pat_new" not in out


def test_nothing_saved_asks_again_in_place_then_records_nothing_and_never_sends_you_to_mint_another(mint, home):
    code, out, _, reads = mint("umbrella", "30", after=("", "", "", ""), keys="\n\n\n\n")   # an Enter to spare: three asks, no more
    assert code == 1 and expiry(home, "umbrella") is None and len(reads) == 4
    assert "don't mint another" in out and "mkdir -p ~/.local/state/ogun/tokens && date -v+30d +%Y-%m-%d > ~/.local/state/ogun/tokens/github-umbrella.expires" in out
    assert "then run: og token" not in out


def test_typing_skip_stops_asking_at_once(mint, home):
    code, out, _, reads = mint("umbrella", after=("",), keys="\nskip\n")
    assert code == 1 and len(reads) == 2 and "nothing recorded" in out and expiry(home, "umbrella") is None


def test_no_answer_at_an_ask_is_a_skip(mint, home):
    code, _, _, reads = mint("umbrella", after=("",), keys="\n")
    assert code == 1 and len(reads) == 2 and expiry(home, "umbrella") is None


def test_saved_at_the_second_ask_is_recorded_with_no_second_token_asked_for(mint, home):
    code, _, _, reads = mint("umbrella", "30", after=("", "github_pat_new"), keys="\n\n")
    assert code == 0 and expiry(home, "umbrella") == in_days(30) and len(reads) == 3


def test_a_rotation_with_the_old_token_still_there_records_nothing(mint, home):
    code, out, _, _ = mint("personal", before="github_pat_old", after=("github_pat_old",), keys="\n")
    assert code == 1 and expiry(home, "personal") is None and "nothing recorded" in out


def test_a_rotation_whose_item_cant_be_read_after_is_no_new_token(mint, home):
    code, out, _, _ = mint("personal", before="github_pat_old", after=("",), keys="\n")   # 1Password locked since
    assert code == 1 and expiry(home, "personal") is None and "nothing recorded" in out


def test_a_rotation_that_saved_a_new_token_is_recorded(mint, home):
    code, _, _, _ = mint("personal", "45", before="github_pat_old", after=("github_pat_new",))
    assert code == 0 and expiry(home, "personal") == in_days(45)


# ── which item, which vault, and what next ──

def test_a_suffixed_profile_mints_into_an_item_with_its_suffix(mint, home):
    use_profile(home, "work")
    assert mint("initech")[3][0] == "read -n op://Sandbox/github-pat-initech-work/credential"


def test_the_vault_is_ogs_setting(mint, monkeypatch):
    monkeypatch.setenv("OG_VAULT", "Other")
    assert mint("umbrella")[3][0] == "read -n op://Other/github-pat-umbrella-desk/credential"


def test_the_vault_set_in_ogs_settings_file_is_the_one_minted_into(mint, home, monkeypatch):
    monkeypatch.delenv("OG_VAULT")
    (home / ".config/ogun").mkdir(parents=True, exist_ok=True)
    (home / ".config/ogun/config.toml").write_text('vault = "CustomVault"\n' + MAC_PROFILES)
    assert mint("umbrella")[3][0] == "read -n op://CustomVault/github-pat-umbrella-desk/credential"


def test_a_settings_file_og_cant_read_stops_it_before_the_form_never_a_guessed_vault(mint, home, monkeypatch):
    monkeypatch.delenv("OG_VAULT")
    (home / ".config/ogun").mkdir(parents=True, exist_ok=True)
    (home / ".config/ogun/config.toml").write_text('valt = "CustomVault"\n')
    code, out, url, reads = mint("umbrella")
    assert code == 1 and url is None and reads == [] and "valt" in out


def test_a_saved_token_says_how_new_and_existing_sandboxes_get_it(mint):
    code, out, _, _ = mint("umbrella")
    assert code == 0 and "og --org umbrella" in out and "og <name> --sync" in out and "Delete the previous token on GitHub" in out


def test_without_open_the_form_is_printed_to_open_by_hand(mint, stand_in, home):
    stand_in("open", "exit 1")
    code, out, _, _ = mint("umbrella")
    assert code == 0 and FORM + "?" in out


def test_help_is_its_usage_and_mints_nothing(og, fakes, home):
    code, out, _ = og("token", "--help")
    assert code == 0 and out.startswith("usage: og token") and fakes.op.calls == []


def test_the_record_command_quotes_a_state_folder_the_shell_would_split(home):
    from ogun.secrets import token
    assert token._sh(home / ".local/state/ogun/tokens") == "~/.local/state/ogun/tokens"
    assert token._sh(home / "my state/tokens") == f"'{home}/my state/tokens'"
