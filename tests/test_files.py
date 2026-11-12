"""Writing a file whole: a temp file beside it, then a rename, so a crash or a
full disk never leaves a half-written file where a whole one was."""

import json
import os
import stat

import pytest

from ogun.core import files


def _mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def test_text_replaces_the_file_whole(tmp_path):
    f = tmp_path / "names"
    f.write_text("old\n")
    files.write_text(f, "a\nb\n")
    assert f.read_text() == "a\nb\n"
    assert [p.name for p in tmp_path.iterdir()] == ["names"]


def test_a_private_file_is_readable_by_its_owner_only(tmp_path):
    f = tmp_path / "rec.json"
    files.write_json(f, {"a": 1}, private=True)
    assert _mode(f) == 0o600


def test_a_shared_file_follows_the_umask(tmp_path):
    old = os.umask(0o022)
    try:
        files.write_text(tmp_path / "x", "x")
    finally:
        os.umask(old)
    assert _mode(tmp_path / "x") == 0o644


def test_json_is_indented_two_ascii_and_no_trailing_newline_by_default(tmp_path):
    f = tmp_path / "rec.json"
    files.write_json(f, {"name": "café", "n": [1]})
    assert f.read_text() == json.dumps({"name": "café", "n": [1]}, indent=2)


def test_json_can_keep_unicode_and_end_with_a_newline(tmp_path):
    f = tmp_path / "registry.json"
    files.write_json(f, {"name": "café"}, ascii=False, newline=True)
    assert f.read_text() == '{\n  "name": "café"\n}\n'


def test_a_write_that_cant_complete_leaves_the_old_file_and_no_temp(tmp_path):
    f = tmp_path / "rec.json"
    f.write_text('{"old": true}')
    with pytest.raises(TypeError):
        files.write_json(f, {"bad": object()})
    assert f.read_text() == '{"old": true}'
    assert [p.name for p in tmp_path.iterdir()] == ["rec.json"]


def test_a_folder_that_cant_be_written_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        files.write_text(tmp_path / "missing" / "f", "x")
