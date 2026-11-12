"""og stands on its own: a copy of its folder alone installs (setup.sh) and runs. Its
code and tests read nothing outside the folder, it carries its own test runner, shell
tests and tab completion, its help points at its own docs, and its core commands run
with an empty config folder. What a team supplies goes in og's config folder
(docs/config.md)."""

import os
import re

import pytest

from ogun.core import paths

# ── og runs with an empty config folder ──

@pytest.fixture
def bare_mac(home, og, fakes):
    """A Mac with nothing set up for og: its config folder empty, no settings file;
    sbx faked."""
    from ogun.core import config
    for n in config.NAMED:
        (home / ".config/ogun" / n).unlink(missing_ok=True)
    (home / ".config/ogun/config.toml").unlink(missing_ok=True)
    return og


@pytest.mark.parametrize(("args", "code", "says"), [
    (("help",), 0, "usage: og"),
    (("ls", "--all"), 0, ""),
    (("template", "ls"), 0, ""),
    (("tidy",), 0, "nothing to tidy"),
    (("log",), 0, "nothing recorded yet"),
    (("project", "ls"), 1, "no registry.json at ~/.config/ogun/registry.json"),
    (("skills",), 1, "no skills folder is set (SBX_SKILLS_DIR"),
    (("policy",), None, "baseline egress"),
    (("doctor",), None, ""),
])
def test_og_runs_its_core_commands_on_an_empty_config_folder(bare_mac, home, args, code, says):
    got, out, err = bare_mac(*args)
    assert got in (0, 1) and (code is None or got == code), out + err
    assert says in out + err and "Traceback" not in out + err


def test_the_help_page_points_at_ogs_own_docs(og):
    _, out, _ = og("help")
    assert "Full reference: docs/README.md, in og's folder" in out


# ── og reads nothing outside its folder: its tests carry their own fixtures ──

# a path built from a folder around og's own
OUTSIDE_RE = re.compile(r"paths\.CODE\b|\bCODE\s*=|OGUN\.parent|parents\[4\]")


def test_no_line_of_ogs_source_or_tests_reads_outside_its_folder():
    me = __file__.rsplit("/", 1)[-1]
    found = [f"{f.relative_to(paths.OGUN)}: {line.strip()}"
             for d in (paths.OGUN / "src", paths.SCRIPTS, paths.OGUN / "tests") for f in sorted(d.rglob("*"))
             if f.is_file() and f.suffix in (".py", ".sh", "") and f.name != me
             for line in f.read_text(errors="replace").splitlines()
             if OUTSIDE_RE.search(line)]
    assert found == []


# ── og's own runner, shell tests and tab completion, beside it ──

SHELL_TESTS = paths.OGUN / "tests/sh"


def test_og_has_a_test_runner_of_its_own_and_its_shell_tests_beside_it():
    runner = paths.OGUN / "test.sh"
    assert runner.is_file() and runner.stat().st_mode & 0o111
    names = {f.name for f in SHELL_TESTS.glob("*.test.sh")}
    assert {"bin.test.sh", "pytest.test.sh", "python.test.sh", "workflow-push-request.test.sh", "copy.test.sh"} <= names
    assert (SHELL_TESTS / "lib.sh").is_file()


def test_og_has_its_tab_completion_and_its_tests_beside_it():
    assert (paths.OGUN / "completion.bash").is_file()
    assert {"completion.test.sh", "shared-values.test.sh"} <= {f.name for f in SHELL_TESTS.glob("*.test.sh")}


# ── no test reaches the home of whoever runs them ──

def test_a_test_without_a_scratch_home_still_has_one(tmp_path):
    from conftest import RUNNERS_HOME
    from ogun.core import settings
    assert os.environ["HOME"] != RUNNERS_HOME and str(paths.state_dir()).startswith(str(tmp_path))
    assert not [n for n in (*settings.NAMES, "XDG_CONFIG_HOME") if n in os.environ and n != "SBX_OGUN_DIR"]


def test_nor_the_runners_terminal_settings():
    assert os.environ.get("TERM") == "xterm-256color" and "NO_COLOR" not in os.environ


def test_a_shell_test_leaves_no_scratch_folder_behind_even_a_read_only_one(tmp_path):
    import subprocess
    script = (f'. "{paths.OGUN}/tests/sh/lib.sh"; echo "$TEST_TMP"; mkdir -p "$TEST_TMP/ro/in"; '
              'chmod a-w "$TEST_TMP/ro"; SUMMARIZED=1')
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env={**os.environ, "TMPDIR": str(tmp_path)})
    left = p.stdout.strip().splitlines()[0]
    assert left.startswith(str(tmp_path)) and not os.path.exists(left), p.stderr
