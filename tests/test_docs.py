"""docs: og's pages (docs/) resolve, stay inside og's folder, and say only what the code
does. Every relative link lands on a file in og's folder that exists, and every #anchor on a
heading there (GitHub's slug rules); every `ogun <command>` the pages show is in the
command table (help.py); every docs/…md path og's code, scripts and tests name exists
in og's docs. The checker is also run on planted mistakes, so a checker that passes
everything would fail here."""

import os
import re
from pathlib import Path

import pytest

from ogun import cli, help
from ogun.core import config, paths, settings

DOCS = paths.OGUN / "docs"

FENCE = re.compile(r"^(```|~~~)")
# a link's text may wrap onto the next line, never past a blank one
LINK = re.compile(r"(?<!!)\[(?:[^\]\n]|\n(?!\n))*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
CODE_SPAN = re.compile(r"(`+)(.+?)\1")
OGUN_CMD = re.compile(r"(?<![\w/.~-])ogun[ \t]+([a-z][a-z-]*)")
# a docs page named in og's code: relative to og's folder
PATHREF = re.compile(r"(?<![\w./~-])(docs/[\w./-]+\.md)\b")


def split(text: str) -> tuple[list[tuple[int, str]], str]:
    """(prose lines, code text): fenced blocks and inline code spans go to code."""
    prose, code, fenced = [], [], False
    for n, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line.lstrip()):
            fenced = not fenced
            prose.append((n, ""))
            continue
        if fenced:
            code.append(line)
            prose.append((n, ""))
            continue
        code.extend(m.group(2) for m in CODE_SPAN.finditer(line))
        prose.append((n, CODE_SPAN.sub("", line)))
    return prose, "\n".join(code)


def slug(heading: str) -> str:
    h = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading.strip())
    h = h.lower().replace("`", "")
    h = re.sub(r"[^\w\- ]", "", h)
    return h.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    seen: dict[str, int] = {}
    out, fenced = set(), False
    for line in path.read_text().splitlines():
        if FENCE.match(line.lstrip()):
            fenced = not fenced
            continue
        m = None if fenced else re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m:
            s = slug(m.group(1))
            k = seen.get(s, 0)
            out.add(s if k == 0 else f"{s}-{k}")
            seen[s] = k + 1
    return out


def check(root: Path, commands: set[str]) -> list[str]:
    """Every problem in <root>/docs/**.md: a link to a missing file or one outside <root>,
    a missing anchor, an `ogun <command>` not in the table."""
    root = root.resolve()
    problems = []
    for doc in sorted((root / "docs").rglob("*.md")):
        rel = doc.relative_to(root)
        prose, code = split(doc.read_text())
        text = "\n".join(line for _, line in prose)
        for m in LINK.finditer(text):
            n, target = text.count("\n", 0, m.start()) + 1, m.group(1)
            if re.match(r"^[a-z][a-z0-9+.-]*:", target):   # http:, https:, mailto:
                continue
            path, _, anchor = target.partition("#")
            dest = doc if not path else Path(os.path.normpath(doc.parent / path))
            if not dest.is_relative_to(root):
                problems.append(f"{rel}:{n}: link outside og's folder: {target}")
            elif not dest.exists():
                problems.append(f"{rel}:{n}: link to a missing file: {target}")
            elif anchor and dest.suffix == ".md" and anchor not in anchors(dest):
                problems.append(f"{rel}:{n}: no heading for #{anchor} in {dest.relative_to(root)}")
        problems += [f"{rel}: `ogun {c}` is not a command (og help lists them)"
                     for c in OGUN_CMD.findall(code) if c not in commands]
    return problems


COMMANDS = set(help.COMMANDS)


def test_every_link_anchor_and_command_in_ogs_docs_resolves_inside_og():
    assert DOCS.is_dir()
    assert check(paths.OGUN, COMMANDS) == []


def test_every_docs_page_og_names_exists_in_its_docs():
    named = [(f, ref) for f in sorted(paths.OGUN.rglob("*"))
             if f.is_file() and ".venv" not in f.parts and f.suffix in (".py", ".sh", ".bash", "", ".toml", ".env", ".lock")
             and f.name != Path(__file__).name
             for ref in set(PATHREF.findall(f.read_text(errors="replace")))]
    assert named, "og names no docs page at all: the pattern is broken"
    assert [f"{f.relative_to(paths.OGUN)}: {ref}" for f, ref in named if not (paths.OGUN / ref).is_file()] == []


# ── the checker itself, on planted mistakes ──

@pytest.fixture
def tree(tmp_path):
    """A tiny og folder: a README page and one more, linked both ways, with a command."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/README.md").write_text(
        "# Top\n\n## Two words\n\nSee [the page](a.md#part-one) and [here](#two-words).\n\n```bash\nogun ls\n```\n")
    (tmp_path / "docs/a.md").write_text("# A\n\n## Part one\n\nBack to [the top](README.md#top). Run `ogun help`.\n")
    return tmp_path


def test_a_clean_tree_passes(tree):
    assert check(tree, COMMANDS) == []


@pytest.mark.parametrize(("planted", "says"), [
    ("[gone](nope.md)", "link to a missing file"),
    ("[gone](a.md#part-two)", "no heading for #part-two"),
    ("[out](../../README.md)", "link outside og's folder"),
    ("[a link whose text\nwraps](nope.md)", "link to a missing file"),
    ("Run `ogun frobnicate` now.", "`ogun frobnicate` is not a command"),
])
def test_the_checker_fails_on_a_planted_mistake(tree, planted, says):
    with (tree / "docs/README.md").open("a") as f:
        f.write(f"\n{planted}\n")
    found = check(tree, COMMANDS)
    assert len(found) == 1 and says in found[0]


def test_links_inside_a_code_fence_are_not_checked(tree):
    with (tree / "docs/README.md").open("a") as f:
        f.write("\n```md\n[not a link](nowhere.md)\n```\n")
    assert check(tree, COMMANDS) == []


# ── what the pages say matches the code ──

def test_the_config_folder_page_names_every_file_and_setting():
    page = (DOCS / "config.md").read_text()
    missing = [n for n in (*config.NAMED, "config.toml", *settings.NAMES, "OG_PROFILE") if f"`{n}" not in page]
    assert missing == []


def test_the_style_guide_lists_each_commands_format_as_cli_does():
    guide = (DOCS / "appendix/ogun-style.md").read_text()
    section = guide.split("## Two formats", 1)[1].split("\n## ", 1)[0]
    listed = dict(re.findall(r"^\| `og ([a-z <>-]*)` \| ([a-z]*)", section, re.M))
    assert listed and listed == cli.FORMAT


def test_ogs_own_readme_reaches_every_page_of_its_docs():
    link = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s#]+)(?:#[^)\s]*)?(?:\s+\"[^\"]*\")?\)")
    seen, todo = set(), [DOCS / "README.md"]
    while todo:
        page = todo.pop().resolve()
        if page in seen or page.suffix != ".md" or not page.is_file():
            continue
        seen.add(page)
        todo += [page.parent / t for t in link.findall(page.read_text()) if not re.match(r"^[a-z]+:", t)]
    assert sorted(str(p.relative_to(DOCS)) for p in DOCS.rglob("*.md") if p.resolve() not in seen) == []


# ── the docs' command table says what og's own table says ──

def _rows(heading: str) -> dict[str, str]:
    """The rows of README.md's table under heading, by the command or flag their
    first cell names (ogun <cmd>, or --flag)."""
    text = (DOCS / "README.md").read_text().split(heading, 1)[1]
    out = {}
    for line in text.splitlines():
        if line.startswith("|") and not line.startswith(("| Command", "| Flag", "|---")):
            m = re.match(r"\| `(?:ogun (\w+)|(--[\w-]+))", line)
            if m:
                out.setdefault(m[1] or m[2], line)
        elif out and not line.startswith("|"):
            break
    return out


def _words(usage: str) -> set[str]:
    """The flags and fixed subcommands a usage line names."""
    return set(re.findall(r"--[\w-]+", usage)) | set(re.findall(r"(?<![<\w-])([a-z]+)(?![\w>])", usage))


@pytest.mark.parametrize("cmd", sorted(help.COMMANDS))
def test_the_docs_command_table_has_each_command_with_every_flag_and_subcommand(cmd):
    rows = _rows("## Commands")
    assert cmd in rows, f"no row for ogun {cmd}"
    missing = sorted(w for w in _words(help.COMMANDS[cmd][0]) if w not in rows[cmd])
    assert missing == [], f"ogun {cmd}'s row lacks {missing}"


def test_and_its_flags_table_has_each_create_flag():
    flags = set(re.findall(r"^  (--[\w-]+)", help.FLAGS, re.M))
    assert flags and sorted(flags - set(_rows("Flags for a bare"))) == []
