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
    monkeypatch.setattr("ogun.sandbox.create.skills_store", lambda: s)
    monkeypatch.setenv("OG_SKILLS_DIR", "~/agent-config/skills")   # a team's
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
    monkeypatch.setattr("ogun.sandbox.create.skills_store", lambda: home / "blocker/store")
    code, out, err = og("skills")
    assert code == 1 and "couldn't make the skills store" in out + err


@pytest.mark.parametrize("args", [["x"], ["--all"]])
def test_og_skills_takes_no_arguments(og, store, args):
    code, out, err = og("skills", *args)
    assert code == 1 and "usage: og skills" in out + err and not store.exists()


def test_help_is_its_usage_and_mirrors_nothing(og, store):
    code, out, _ = og("skills", "--help")
    assert code == 0 and out.startswith("usage: og skills") and not store.exists()


def test_a_skill_linked_in_from_elsewhere_reaches_the_store_as_its_files(og, store, home):
    (home / "elsewhere/review").mkdir(parents=True)
    (home / "elsewhere/review/SKILL.md").write_text("review\n")
    (home / "agent-config/skills/review").symlink_to(home / "elsewhere/review")
    assert og("skills")[0] == 0
    assert not (store / "review").is_symlink() and (store / "review/SKILL.md").read_text() == "review\n"


def test_a_link_to_nothing_is_said_and_left_out_and_the_rest_still_arrives(og, store, home):
    (home / "elsewhere/review").mkdir(parents=True)
    (home / "elsewhere/review/SKILL.md").write_text("review\n")
    (home / "elsewhere/review/notes[1].md").symlink_to(home / "nowhere")   # inside a linked skill, a name rsync reads as a pattern
    (home / "agent-config/skills/review").symlink_to(home / "elsewhere/review")
    (home / "agent-config/skills/gone").symlink_to(home / "nowhere")
    code, out, err = og("skills")
    assert code == 0 and (store / "review/SKILL.md").read_text() == "review\n" and (store / "outline/SKILL.md").is_file()
    assert not os.path.lexists(store / "gone") and not os.path.lexists(store / "review/notes[1].md")
    assert "~/agent-config/skills/gone links to nothing; left out of the skills store" in out + err
    assert "~/agent-config/skills/review/notes[1].md links to nothing" in out + err


def test_a_linked_skill_whose_target_goes_leaves_the_store_too(og, store, home):
    import shutil
    (home / "elsewhere/review").mkdir(parents=True)
    (home / "elsewhere/review/SKILL.md").write_text("review\n")
    (home / "agent-config/skills/review").symlink_to(home / "elsewhere/review")
    assert og("skills")[0] == 0 and (store / "review/SKILL.md").is_file()
    shutil.rmtree(home / "elsewhere/review")
    assert og("skills")[0] == 0 and not os.path.lexists(store / "review") and (store / "outline/SKILL.md").is_file()


def test_a_folder_two_skills_link_to_is_checked_under_each_name(og, store, home):
    (home / "elsewhere/shared").mkdir(parents=True)
    (home / "elsewhere/shared/SKILL.md").write_text("shared\n")
    (home / "elsewhere/shared/bad").symlink_to(home / "missing")
    for n in ("a", "b"):
        (home / f"agent-config/skills/{n}").symlink_to(home / "elsewhere/shared")
    code, out, err = og("skills")
    assert code == 0 and (store / "a/SKILL.md").is_file() and (store / "b/SKILL.md").is_file()
    assert "skills/a/bad links to nothing" in out + err and "skills/b/bad links to nothing" in out + err


def test_a_linked_folder_that_holds_itself_is_walked_once(store, home):
    from ogun.sandbox import create
    (home / "agent-config/skills/outline/loop").symlink_to(home / "agent-config/skills")
    (home / "agent-config/skills/outline/bad").symlink_to(home / "missing")
    assert create.dangling(str(home / "agent-config/skills")) == ["outline/bad"]
