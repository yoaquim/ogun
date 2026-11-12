"""skills: og skills, a folder of skills mirrored into sbx's shared skills store, which
every sandbox mounts. The store is always left read-only: sandboxes mount it
read-write, and read-only modes are what stop one sandbox planting a skill for the
rest. The mirror is its only writer: it unlocks, syncs, and locks again."""

import os
import subprocess

import pytest


@pytest.fixture
def store(home, monkeypatch):
    """A skills folder with two skills, and the store beside them."""
    s = home / "store"
    monkeypatch.setenv("SBX_SKILLS_STORE", str(s))
    monkeypatch.setenv("SBX_SKILLS_DIR", "~/agent-config/skills")   # a team's
    for name in ("outline", "glossary"):
        (home / f"agent-config/skills/{name}").mkdir(parents=True)
        (home / f"agent-config/skills/{name}/SKILL.md").write_text(f"{name}\n")
    yield s
    subprocess.run(["chmod", "-R", "u+w", str(s)], capture_output=True)   # so the test's folder can go


def writable(p) -> list[str]:
    return [str(x) for x in [p, *p.rglob("*")] if os.access(x, os.W_OK)]


def test_og_skills_mirrors_claude_skills_into_the_store_and_says_how_many(og, store):
    code, out, err = og("skills")
    assert code == 0 and sorted(x.name for x in store.iterdir()) == ["glossary", "outline"]
    assert (store / "outline/SKILL.md").read_text() == "outline\n" and "skills store: 2 skills" in out + err


def test_the_store_is_left_read_only_every_file_and_folder(og, store):
    assert og("skills")[0] == 0 and (store / "outline/SKILL.md").is_file() and writable(store) == []


def test_a_skill_gone_from_the_folder_goes_from_the_store_a_changed_one_follows(og, store, home):
    og("skills")
    subprocess.run(["rm", "-rf", str(home / "agent-config/skills/glossary")], check=True)
    (home / "agent-config/skills/outline/SKILL.md").write_text("outline, changed\n")
    assert og("skills")[0] == 0
    assert sorted(x.name for x in store.iterdir()) == ["outline"] and (store / "outline/SKILL.md").read_text() == "outline, changed\n"
    assert writable(store) == []


def test_a_skill_a_sandbox_planted_in_the_store_is_removed(og, store):
    og("skills")
    subprocess.run(["chmod", "-R", "u+w", str(store)], check=True)
    (store / "planted").mkdir()
    (store / "planted/SKILL.md").write_text("x\n")
    assert og("skills")[0] == 0 and not (store / "planted").exists()


def test_a_store_that_cant_be_made_fails_it(og, store, home, monkeypatch):
    (home / "blocker").write_text("a file, not a folder\n")
    monkeypatch.setenv("SBX_SKILLS_STORE", str(home / "blocker/store"))
    code, out, err = og("skills")
    assert code == 1 and "couldn't make the skills store" in out + err


@pytest.mark.parametrize("args", [["x"], ["--all"]])
def test_og_skills_takes_no_arguments(og, store, args):
    code, out, err = og("skills", *args)
    assert code == 1 and "usage: og skills" in out + err and not store.exists()


def test_help_is_its_usage_and_mirrors_nothing(og, store):
    code, out, _ = og("skills", "--help")
    assert code == 0 and out.startswith("usage: og skills") and not store.exists()
