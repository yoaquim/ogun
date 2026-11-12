"""Where a sandbox's create record lives, and reading one back: the records the
secret grants are applied and revoked from."""

import json

import pytest

from ogun.core import records
from ogun.sandbox import sandboxes


@pytest.fixture
def folder(home):
    d = home / ".local/state/ogun/sandboxes"
    d.mkdir()
    return d


def test_a_record_is_named_for_its_sandbox(folder):
    assert records.record_file("web") == folder / "web.json"


def test_a_record_reads_back(folder):
    (folder / "web.json").write_text(json.dumps({"sandbox": "web", "secrets": []}))
    assert records.read_record("web") == {"sandbox": "web", "secrets": []}


@pytest.mark.parametrize("text", [None, "{broken", "[1]"])
def test_a_missing_or_unreadable_record_is_none(folder, text):
    if text is not None:
        (folder / "web.json").write_text(text)
    assert records.read_record("web") is None


def test_records_live_in_ogs_state_folder(home):
    assert records.records_dir() == home / ".local/state/ogun/sandboxes"


def test_protected_names_the_sandboxes_whose_record_has_openappa(folder):
    (folder / "web.json").write_text('{"appa": {"version": "1.2"}}')
    (folder / "api.json").write_text('{"appa": {"version": null}}')
    (folder / "odd.json").write_text("[1]")
    (folder / "bad.json").write_text("{broken")
    assert sandboxes.protected() == {"web"}
