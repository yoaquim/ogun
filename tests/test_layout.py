"""layout: og's package organised by concern, no module over about 400 lines, and
the scripts og sends into a sandbox kept together outside the package."""

import shutil
import subprocess

import pytest

from conftest import FIXTURES
from ogun.core import paths

SRC = paths.OGUN / "src/ogun"
LIMIT = 400


def test_no_module_is_over_the_limit():
    over = {str(f.relative_to(SRC)): n for f in SRC.rglob("*.py") if (n := len(f.read_text().splitlines())) > LIMIT}
    assert over == {}


def test_each_concern_is_a_subpackage():
    for d in ("core", "net", "exchange", "sandbox", "secrets"):
        assert (SRC / d / "__init__.py").is_file(), d


def test_no_module_sits_loose_beside_them_but_the_entry_and_its_commands():
    assert {f.name for f in SRC.glob("*.py")} == {"__init__.py", "cli.py", "help.py", "ship.py", "mcp.py"}


def test_the_in_sandbox_scripts_live_together_outside_the_package():
    assert not list(SRC.rglob("*.sh"))
    assert (paths.SCRIPTS / "unsafe-probe.sh").is_file()


OWN = ("sandbox-ssh.sh", "sandbox-docker.sh", "unsafe-probe.sh", "env/drop.sh", "env/export.sh", "env/expose.sh",
       "env/unexport.sh", "appa/install.sh", "appa/activate.sh", "appa/ensure.sh", "appa/policy.py")


def test_ogs_own_files_live_in_ogs_tree():
    assert SRC.parents[1] == paths.OGUN and paths.OGUN / "sandbox-scripts" == paths.SCRIPTS
    assert [rel for rel in OWN if not (paths.SCRIPTS / rel).is_file()] == []
    assert (SRC / "net/baseline.env").is_file()


def in_sandbox_scripts() -> list:
    """Every shell script og sends into a sandbox, its own (env, OpenAPPA, ssh,
    Docker, the unsafe-files probe, the ship request), and the recipes it builds
    from as its tests have them."""
    return sorted([*(FIXTURES / "templates").rglob("*.sh"), *paths.SCRIPTS.rglob("*.sh")])


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck isn't installed (brew install shellcheck)")
def test_every_in_sandbox_script_is_shellcheck_clean_at_its_default_level():
    scripts = in_sandbox_scripts()
    assert len(scripts) >= 13
    p = subprocess.run(["shellcheck", "-f", "gcc", *map(str, scripts)], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout


def hidden_modules(src=SRC) -> list[str]:
    """Each place a local name (an argument, an assignment, a loop or with target)
    is an og module the same file imports: inside that function, the module is gone."""
    import ast
    found = []
    for f in sorted(src.rglob("*.py")):
        tree = ast.parse(f.read_text())
        mods = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                and n.module and n.module.split(".")[0] == "ogun" for a in n.names}
        for n in ast.walk(tree):
            name = (n.id if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
                    else n.arg if isinstance(n, ast.arg) else None)
            if name in mods:
                found.append(f"{f.relative_to(src)}:{n.lineno} {name}")
    return found


def test_no_local_name_hides_a_module_the_file_imports():
    assert hidden_modules() == []


def test_the_check_finds_one(tmp_path):
    (tmp_path / "a.py").write_text("from ogun.net import egress\n\ndef f(egress):\n    out = [x for x in egress]\n")
    assert hidden_modules(tmp_path) == ["a.py:3 egress"]


FUNCTION_LIMIT = 60


def long_functions(src=SRC) -> dict[str, int]:
    """Each function longer than the limit, def line to last line, by file:name."""
    import ast
    return {f"{f.relative_to(src)}:{n.name}": size for f in sorted(src.rglob("*.py"))
            for n in ast.walk(ast.parse(f.read_text()))
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
            and (size := n.end_lineno - n.lineno + 1) > FUNCTION_LIMIT}


def test_no_function_is_over_the_limit():
    assert long_functions() == {}


def test_the_function_check_finds_one(tmp_path):
    (tmp_path / "a.py").write_text("def f():\n" + "    x = 1\n" * FUNCTION_LIMIT + "\n\ndef g():\n    pass\n")
    assert long_functions(tmp_path) == {"a.py:f": FUNCTION_LIMIT + 1}
