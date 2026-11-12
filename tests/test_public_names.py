"""No og module reaches into another's private names: a name another module uses
is public, so renaming a private one can never break a caller it didn't know of."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "ogun"


def _ogun_modules(tree: ast.Module) -> set[str]:
    """The local names this module binds to og modules: `from ogun import x` and
    `from ogun.pkg import x`, `import ogun.x as y`, at the top or inside a function."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and (node.module == "ogun" or node.module.startswith("ogun.")):
            names |= {a.asname or a.name for a in node.names}
        elif isinstance(node, ast.Import):
            names |= {a.asname for a in node.names if a.name.startswith("ogun.") and a.asname}
    return names


def reach_ins(src: Path = SRC) -> list[str]:
    found = []
    for f in sorted(src.rglob("*.py")):
        tree = ast.parse(f.read_text())
        mods = _ogun_modules(tree) - {f.stem}
        rel = f.relative_to(src)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in mods
                    and node.attr.startswith("_") and not node.attr.startswith("__")):
                found.append(f"{rel}:{node.lineno} {node.value.id}.{node.attr}")
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("ogun."):
                found += [f"{rel}:{node.lineno} from {node.module} import {a.name}"
                          for a in node.names if a.name.startswith("_")]
    return found


def test_no_module_uses_another_modules_private_names():
    assert reach_ins() == []


def test_the_check_finds_a_reach_in(tmp_path):
    (tmp_path / "a.py").write_text("from ogun import b\nb._hidden()\nb.shown()\n")
    (tmp_path / "c.py").write_text("from ogun.b import _hidden\n")
    (tmp_path / "d.py").write_text("def _own(): pass\n_own()\n")
    assert reach_ins(tmp_path) == ["a.py:2 b._hidden", "c.py:1 from ogun.b import _hidden"]


def test_and_one_in_a_package_through_an_import_from_another(tmp_path):
    (tmp_path / "net").mkdir()
    (tmp_path / "net/e.py").write_text("from ogun.core import b\nb._hidden()\n")
    assert reach_ins(tmp_path) == ["net/e.py:2 b._hidden"]
