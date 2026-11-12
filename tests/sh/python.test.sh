#!/usr/bin/env bash
# og's Python: the lock pins every package to one version and its
# hashes, wheels only, with a two-week cutoff; setup installs og, which runs this checkout's code
# in isolation; and og's one style, -v and plain output when piped.
# The owner rules, og project and the usage lines are pytest (tests).

# shellcheck disable=SC2016  # the bash -c bodies expand in the child, on purpose
set -uo pipefail
# shellcheck source=/dev/null
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

echo "og's Python: lock, launcher, style"

PY="$("$OGUN/bin/venv")/bin/python"   # .venv on a Mac
OG="$("$OGUN/bin/venv")/bin/og"   # the command setup installs
# the venv is built from its pins alone, as og's install builds it
"$OGUN/bin/venv" --ready || bash "$OGUN/setup.sh" >/dev/null 2>&1
# not built, and couldn't be here (no network to its downloads): every case below needs it
"$OGUN/bin/venv" --ready && export OG_PY="$PY"
og_python_or_skip
expect_cmd 0 "the venv builds from its pins (setup.sh)" test -x "$PY"
# setup's last words say how to have og's tab completion: source this folder's completion.bash
says_completion() { local o; o=$(bash "$OGUN/setup.sh" 2>&1) || { echo "$o"; return 1; }
  grep -qF "source $OGUN/completion.bash" <<<"$o"; }
expect_cmd 0 "…and setup ends by saying how to load og's tab completion, by its path in this folder" says_completion
venv_python() { [[ "$("$PY" -I -c 'import platform; print(platform.python_version())')" == "$(tr -d '[:space:]' < "$OGUN/.python-version")" ]]; }
expect_cmd 0 "…and runs exactly the Python in .python-version" venv_python

# ── the lock ──
lock_rules() { "$PY" -I - "$OGUN" <<'PY'
import sys, tomllib
d = sys.argv[1]
proj = tomllib.load(open(f"{d}/pyproject.toml", "rb"))
lock = tomllib.load(open(f"{d}/uv.lock", "rb"))
uv = proj["tool"]["uv"]
assert uv.get("no-build") is True, "no-build is off"
assert uv.get("python-preference") == "only-managed", "a Python already on the Mac could be used"
pin = dict(l.split()[:2] for l in open(f"{d}/uv.pin") if l.strip() and not l.startswith("#"))
assert uv.get("required-version") == "==" + pin["version"], "required-version is not uv.pin's version"
for plat in ("aarch64-apple-darwin", "x86_64-apple-darwin", "aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu"):
    assert len(pin.get(plat, "")) == 64, f"uv.pin: no SHA-256 for {plat}"
import re
assert re.fullmatch(r"3\.\d+\.\d+", open(f"{d}/.python-version").read().strip()), ".python-version is not one exact Python"
assert uv.get("package") is False, "ogun would be built"
assert lock.get("options", {}).get("exclude-newer") == uv["exclude-newer"], "the lock was made without the cutoff"
pins = {}
dev = proj.get("dependency-groups", {}).get("dev", [])
for dep in proj["project"]["dependencies"] + dev:
    name, sep, ver = dep.partition("==")
    assert sep and ver, f"{dep} is not pinned to one version"
    pins[name.lower()] = ver
assert {"pytest", "ruff"} <= {d.partition("==")[0].lower() for d in dev}, "pytest and ruff are not in the dev group"
for p in lock["package"]:
    if p["name"] == "ogun":
        continue
    wheels = p.get("wheels") or []
    assert wheels, f"{p['name']} has no wheel: it would need building"
    for w in wheels:
        assert w.get("hash", "").startswith("sha256:"), f"{p['name']}: a wheel without a sha256"
    if p["name"] in pins:
        assert p["version"] == pins.pop(p["name"]), f"{p['name']}: lock and pyproject disagree"
assert not pins, f"pinned but not in the lock: {pins}"
PY
}
expect_cmd 0 "pinned: uv by version and SHA-256, one exact Python, every package one version (pytest and ruff too, in the dev group), wheels only, hashed, with the cutoff" lock_rules

# ── the command: setup installs og from this folder into og's own environment ──
FIX="$TEST_TMP/ogpy"
mkdir -p "$FIX/bin" "$FIX/plant"
# sbx stub: nothing here talks to a sandbox
printf '#!/bin/sh\nexit 0\n' > "$FIX/bin/sbx"; chmod +x "$FIX/bin/sbx"
export PATH="$FIX/bin:$PATH"
declared() { "$PY" -I - "$OGUN/pyproject.toml" <<'PY'
import sys, tomllib
d = tomllib.load(open(sys.argv[1], "rb"))
assert d["project"]["scripts"] == {"og": "ogun.cli:main"}, d["project"].get("scripts")
assert "build-system" not in d, "a build system would be downloaded and run to install og"
PY
}
expect_cmd 0 "the project file declares og (ogun.cli:main), with no build system to download or run" declared
installed() { [[ -x "$OG" && "$(head -n 1 "$OG")" == "#!$PY -I" ]]; }
expect_cmd 0 "setup installs og into og's own environment, run by its Python, isolated" installed
editable() { [[ "$("$PY" -I -c 'import ogun; print(ogun.__file__)')" == "$OGUN/src/ogun/__init__.py" ]]; }
expect_cmd 0 "…from this folder, as it is: the code og runs is this checkout's src" editable
bare_env() { local o; o=$(cd "$FIX" && env -i HOME="$FIX" PATH=/usr/bin:/bin "$OG" help 2>&1) && grep -q "^og — one sandboxed" <<<"$o"; }
expect_cmd 0 "og runs from a shell with no profile and a bare PATH" bare_env
ln -sf "$OG" "$FIX/bin/og-link"
via_link() { local o; o=$("$FIX/bin/og-link" help 2>&1) && grep -q project <<<"$o"; }
expect_cmd 0 "a link to it (~/.local/bin/og, say) runs it" via_link
# a module planted where og is run, or named by PYTHONPATH, is never imported
printf 'raise SystemExit("planted module ran")\n' > "$FIX/plant/json.py"
printf 'raise SystemExit("planted module ran")\n' > "$FIX/plant/typer.py"
isolated() { local o; o=$(cd "$FIX/plant" && PYTHONPATH="$FIX/plant" "$OG" --help 2>&1) && ! grep -q planted <<<"$o"; }
expect_cmd 0 "og ignores modules in the current folder and PYTHONPATH" isolated
no_launcher() { [[ ! -e "$OGUN/bin/og" ]]; }
expect_cmd 0 "no other way in: the venv's og is the only og (no launcher in bin/)" no_launcher

# ── og's Python, run from here ──
pyrun() { "$PY" -I -c "import sys; sys.path.insert(0, '$OGUN/src'); $1" "${@:2}"; }

# ── one style: every color and layout in log.py, and og style draws them ──
one_style() { local hits; hits=$(grep -rnE 'from rich|import rich|\\033|\\x1b|\\e\[' "$OGUN/src/ogun" --include='*.py' | grep -vE '/core/(log|boxes)\.py:')
  [[ -z "$hits" ]] || { echo "$hits" >&2; return 1; }; }
expect_cmd 0 "only log.py and boxes.py draw: no Rich import, no escape code, anywhere else in src" one_style
named_colors() { ! grep -nE '\[(green|red|yellow|cyan)\]' "$OGUN"/src/ogun/*.py; }
expect_cmd 0 "…and a summary's states use the theme's names, never a color by name" named_colors
style_plain() { local o; o=$("$OG" style 2>&1)
  [[ "$o" == *"→ a step"* && "$o" == *"  · a fact"* && "$o" == *"✓ done"* && "$o" == *"  ⚠ needs a look"* && "$o" == *"⚠ A CALLOUT"* && "$o" == *"usage: og style"* && "$o" != *$'\033'* ]]; }
expect_cmd 0 "og style draws every kind of line, plain when piped" style_plain
style_pretty() { "$PY" -I - "$OGUN/src" 2>&1 <<'EOF' | grep -q $'\x1b\[1;38;2;125;196;228m→'
import sys; sys.path.insert(0, sys.argv[1])
import os; os.environ["COLORTERM"] = "truecolor"
from ogun.core import log
log.pretty = lambda err=False: True
log._consoles.clear()
log._consoles[False] = log.Console(highlight=False, soft_wrap=True, force_terminal=True, color_system="truecolor")
log.step("x")
EOF
}
expect_cmd 0 "…and on a terminal a step's arrow is og's own color, bold" style_pretty
ls_pretty() { local o; o=$("$PY" -I - "$OGUN/src" 2>&1 <<'EOF'
import sys, subprocess; sys.path.insert(0, sys.argv[1])
from ogun.core import log; from ogun.sandbox import sandboxes
log.pretty = lambda err=False: True
log._consoles[False] = log.Console(highlight=False, soft_wrap=True, force_terminal=True, width=100)
sandboxes.protected = lambda: set()
table = "SANDBOX  AGENT   STATUS\ncub      claude  running\nfern             stopped\n"
sandboxes.sbx.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, table, "")
sys.exit(sandboxes.ls([]))
EOF
) || return 1
  o=$(sed 's/\x1b\[[0-9;]*m//g' <<<"$o")
  grep -q '^╭─ og ls ─' <<<"$o" && grep -qE '│ +cub +claude +● running +│' <<<"$o" && grep -qE '│ +fern +- +○ stopped +│' <<<"$o" \
    && grep -qE '│ +● 1 running · ○ 1 stopped +│' <<<"$o"; }
expect_cmd 0 "og ls on a terminal: og's box, each state marked (● running, ○ stopped), and the count of each" ls_pretty
ls_colors() { local o; o=$("$PY" -I - "$OGUN/src" 2>&1 <<'EOF'
import sys, subprocess; sys.path.insert(0, sys.argv[1])
from ogun.core import log; from ogun.sandbox import sandboxes
log.pretty = lambda err=False: True
log.wrapping = lambda err: log.Console(highlight=False, force_terminal=True, color_system="truecolor", width=100)
sandboxes.protected = lambda: {"cub"}
# a newer sbx marks its own status
table = "SANDBOX  AGENT   STATUS\ncub      claude  ● running\nfern     claude  ○ stopped\n"
sandboxes.sbx.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, table, "")
sys.exit(sandboxes.ls([]))
EOF
) || return 1
  [[ "$o" == *$'\e[1;38;2;166;218;149m● running'* && "$o" == *$'\e[38;2;198;160;246mOpenAPPA'* && "$o" == *$'\e[2mclaude'* \
     && "$(sed 's/\x1b\[[0-9;]*m//g' <<<"$o")" == *"● 1 running · ○ 1 stopped"* && "$o" != *"● ● running"* ]]; }
expect_cmd 0 "…running bold green, the agent dim, OpenAPPA lavender, even when sbx marks its own status" ls_colors
summary_box() { "$PY" -I - "$OGUN/src" 2>&1 <<'EOF' | sed 's/\x1b\[[0-9;]*m//g' | grep -q '^╭─ og policy ─'
import sys; sys.path.insert(0, sys.argv[1])
from ogun.core import boxes, log
log.pretty = lambda err=False: True
log.wrapping = lambda err: log.Console(highlight=False, force_terminal=True, width=100)
log._consoles[False] = log.Console(highlight=False, soft_wrap=True, force_terminal=True, width=100)
boxes.table("og policy", [("baseline", f"[ok]{log.DONE} applied[/]")])
EOF
}
expect_cmd 0 "…and a summary sits in the same box, titled with its command" summary_box

formats() { [ "$(pyrun 'import os
from ogun.core import log
print(log.size(7), log.size(12345), log.size(1234567), log.path(os.path.expanduser("~/Downloads/cub")), log.path("/tmp/x"), log.when(0)[:2])')" \
  = "7 B 12 KB 1.2 MB ~/Downloads/cub /tmp/x 19" ]; }
expect_cmd 0 "one format per kind of value: sizes (7 B, 12 KB, 1.2 MB), paths under home as ~, times as a date" formats
no_spinner() { [ -z "$(pyrun 'from ogun.core import log
with log.waiting("x"): pass' 2>&1)" ]; }
expect_cmd 0 "…and a spinner only on a terminal: piped, waiting prints nothing" no_spinner
rotate() { local d; d=$(mktemp -d); [ "$(XDG_STATE_HOME="$d" pyrun 'from ogun.core import changes, log
log.RECORD_MAX = 50
for i in range(4): log.record(f"change {i}")
print(*[e["what"] for e in changes.entries()], sep=",")')" = "change 2,change 3" ]; }
expect_cmd 0 "the record moves to og.log.1 past its size (one older file kept), and og log reads both, oldest first" rotate
race() { local d; d=$(mktemp -d); mkdir -p "$d/ogun"
  # the test holds og.log.lock, as another og command mid-write would: a record must
  # wait for it (so no two rotate at once), and land once it's let go
  XDG_STATE_HOME="$d" pyrun 'import fcntl, subprocess, sys, time, os
from ogun.core import log
lock = open(log.record_file().with_name("og.log.lock"), "a"); fcntl.flock(lock, fcntl.LOCK_EX)
w = subprocess.Popen([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); from ogun.core import log; log.record(\"waited\")", sys.argv[1]])
time.sleep(1)
waited = w.poll() is None and not log.record_file().exists()
fcntl.flock(lock, fcntl.LOCK_UN); w.wait(10)
sys.exit(0 if waited and "waited" in log.record_file().read_text() else 1)' "$OGUN/src"; }
expect_cmd 0 "…and a record waits for another og command writing one, so two never rotate at once" race
red_exit() { "$PY" -I - "$OGUN/src" 2>&1 <<'PY' | grep -q $'\x1b\[38;2;237;135;150m    ↳ exit 1'
import sys, os; sys.path.insert(0, sys.argv[1])
os.environ["OG_VERBOSE"] = "1"
from ogun.core import log
log.pretty = lambda err=False: True
log._consoles[True] = log.Console(highlight=False, soft_wrap=True, force_terminal=True, color_system="truecolor")
log.detail("    ↳ exit 1 · 3 ms", failed=True)
PY
}
expect_cmd 0 "-v: an sbx call that failed shows its exit in red" red_exit
cmd_pretty() { "$PY" -I - "$OGUN/src" 2>&1 <<'PY' | grep -q $'\x1b\[38;2;238;212;159m  ⚠ fix it: \x1b\[0m\x1b\[1;38;2;125;196;228mog rm cub --force'
import sys, os; sys.path.insert(0, sys.argv[1])
from ogun.core import log
log.pretty = lambda err=False: True
log._consoles[False] = log.Console(highlight=False, soft_wrap=True, force_terminal=True, color_system="truecolor")
log.time.strftime = lambda *a: "12:00:00"
log.warn(f"  {log.WARNING} fix it: {log.cmd('og rm cub --force')}")
PY
}
expect_cmd 0 "a command inside a message is bold, og's color, on a terminal, the sentence around it its own color" cmd_pretty
cmd_plain() { local o d; d=$(mktemp -d); o=$(XDG_STATE_HOME="$d" pyrun 'from ogun.core import changes, log
log.warn("fix it: " + log.cmd("og rm cub --force"))
log.record("ran " + log.cmd("og policy"))
print(changes.entries()[-1]["what"])' 2>&1)
  [ "$o" = $'fix it: og rm cub --force\nran og policy' ]; }
expect_cmd 0 "…piped, the bare words, and the record stores them bare too" cmd_plain
no_marks_leak() { ! "$OG" style 2>&1 | LC_ALL=C grep -q $'\xee\x80[\x80\x81]'; }
expect_cmd 0 "…and no command mark ever reaches piped output" no_marks_leak
views() { local d o; d=$(mktemp -d); mkdir -p "$d/ogun"
  printf '%s\n' '{"t":"2026-10-27T09:12:44","cmd":"og allow fern x.example.com --read-only","what":"fern may reach x.example.com (reading only)"}' \
    '{"t":"2026-10-28T14:07:51","cmd":"og rm fern --force","what":"fern removed"}' > "$d/ogun/og.log"
  o=$(XDG_STATE_HOME="$d" "$PY" -I - "$OGUN/src" 2>&1 <<'PY'
import sys; sys.path.insert(0, sys.argv[1])
import os; os.environ["OG_VERBOSE"] = "1"
from ogun.core import changes, log
log.pretty = lambda err=False: True
log._consoles[False] = log.Console(highlight=False, soft_wrap=True, force_terminal=True, width=100)
changes.show([])
os.environ["OG_VERBOSE"] = "0"   # -v changes nothing it shows
print("---"); changes.show([])
PY
) || return 1
  o=$(sed 's/\x1b\[[0-9;]*m//g' <<<"$o")
  grep -qx 'Tue 27 Oct 2026' <<<"$o" && grep -qx 'Wed 28 Oct 2026' <<<"$o" && grep -qx '\[14:07:51\] fern removed' <<<"$o" \
    && ! grep -q '✓' <<<"$o" && [ "$(grep -cx '           og rm fern --force' <<<"$o")" = 2 ] \
    && [ "$(sed -n '1,/^---$/p' <<<"$o" | sed '$d' | grep -v '^$')" = "$(sed -n '/^---$/,$p' <<<"$o" | sed '1d' | grep -v '^$')" ] && ! grep -q '│' <<<"$o"; }
expect_cmd 0 "og log on a terminal is classic: a section a day, each change a plain line with the time it happened (a replay, no ✓), its command beneath, with or without -v" views
every_format() { [ -z "$(pyrun 'from ogun import cli
user = {c for c in cli.PORTED if c != "internal"}
print(" ".join(sorted(user ^ {k.split()[0] for k in cli.FORMAT})), " ".join(v for v in cli.FORMAT.values() if v not in ("classic", "table")))' | tr -d ' ')" ]; }
expect_cmd 0 "…every ported command has one, and only those two exist" every_format
table_only() { local o; o=$("$PY" -I - "$OGUN/src" 2>&1 <<'PY'
import sys, subprocess; sys.path.insert(0, sys.argv[1])
from ogun.core import log; from ogun.sandbox import sandboxes
log.pretty = lambda err=False: True
log._consoles[False] = log.Console(highlight=False, soft_wrap=True, force_terminal=True, width=100)
log.wrapping = lambda err: log.Console(highlight=False, force_terminal=True, width=100)
sandboxes.protected = lambda: set()
def fake(*a, **k):
    return subprocess.CompletedProcess(a, 0, "SANDBOX  AGENT   STATUS\ncub      claude  running\n", "")
sandboxes.sbx.run = fake
sandboxes.ls([])
PY
) || return 1
  # every line of a table command's output is part of its box: nothing classic around it
  [ -n "$o" ] && ! sed 's/\x1b\[[0-9;]*m//g' <<<"$o" | grep -v '^[╭│╰]' | grep -q .; }
expect_cmd 0 "og ls, the table format, prints nothing outside its box" table_only
no_undefined() {   # a name used but never defined fails only when its line runs: caught here instead
  local o; o=$("$PY" -I - "$OGUN/src/ogun" <<'PY'
import ast, builtins, pathlib, sys
for f in sorted(pathlib.Path(sys.argv[1]).glob("*.py")):
    t, known = ast.parse(f.read_text()), set(dir(builtins)) | {"__file__"}
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)): known.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)): known.update((a.asname or a.name).split(".")[0] for a in n.names)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store): known.add(n.id)
        elif isinstance(n, ast.arg): known.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name: known.add(n.name)
        elif isinstance(n, ast.Global): known.update(n.names)
    bad = {n.id for n in ast.walk(t) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)} - known
    if bad: print(f.name, sorted(bad))
PY
); [ -z "$o" ] || { echo "$o"; return 1; }; }
expect_cmd 0 "no Python file uses a name it never defines or imports" no_undefined
done_rule() {   # ✓ and green only through log.ok, which adds the mark itself; → only through log.step
  ! grep -nE 'log\.ok\(f?"(→|✓|\{log\.DONE\})' "$OGUN"/src/ogun/*.py \
    && ! grep -nE 'log\.(info|note|warn)\(f?"(→ |✓)' "$OGUN"/src/ogun/*.py; }
expect_cmd 0 "a done line is log.ok's alone (it adds ✓), and no other line fakes a ✓ or a step's →" done_rule
done_look() { local o; o=$("$PY" -I - "$OGUN/src" 2>&1 <<'PY'
import sys; sys.path.insert(0, sys.argv[1])
from ogun.core import log
log.pretty = lambda err=False: True
log._consoles[False] = log.Console(highlight=False, soft_wrap=True, force_terminal=True, color_system="truecolor")
log.time.strftime = lambda *a: "12:00:00"
log.ok("gave note.txt to workshop", "~/x/in/note.txt")
PY
); [[ "$o" == *$'\e[38;2;166;218;149m✓ gave note.txt to workshop'* && "$o" == *$'\e[2m~/x/in/note.txt'* ]]; }
expect_cmd 0 "…green covers the ✓ and the summary only; the detail after it is dim" done_look
fix_rule() {   # a command to run is a warning's or error's fix line, never inside its sentence
  local o; o=$("$PY" -I - "$OGUN/src/ogun" <<'PY'
import ast, pathlib, sys
bad = []
for f in sorted(pathlib.Path(sys.argv[1]).glob("*.py")):
    for n in ast.walk(ast.parse(f.read_text())):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("warn", "err")
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "log" and n.args):
            continue
        msg = n.args[0]
        for x in ast.walk(msg):
            # a command in the sentence (log.cmd, _rm_cmd, or rm built by one) …
            if isinstance(x, ast.Call) and getattr(x.func, "attr", getattr(x.func, "id", "")) in ("cmd", "_rm_cmd"):
                bad.append(f"{f.name}:{n.lineno} a command in the sentence")
            if isinstance(x, ast.Name) and x.id == "rm":
                bad.append(f"{f.name}:{n.lineno} a command in the sentence")
            # … or a placeholder printed as text: a string that forgot its f
            if isinstance(x, ast.Constant) and isinstance(x.value, str) and "{log." in x.value:
                bad.append(f"{f.name}:{n.lineno} {{log.…}} as text: not an f-string")
print("\n".join(sorted(set(bad))))
PY
); [ -z "$o" ] || { echo "$o"; return 1; }; }
expect_cmd 0 "a warning's or error's command is its fix line, never in its sentence, and no message prints {log.…} as text" fix_rule
fix_look() { local o; o=$("$PY" -I - "$OGUN/src" 2>&1 <<'PY'
import sys; sys.path.insert(0, sys.argv[1])
from ogun.core import log
log.pretty = lambda err=False: True
log._consoles[False] = log.Console(highlight=False, soft_wrap=True, force_terminal=True, color_system="truecolor")
log.time.strftime = lambda *a: "12:00:00"
log.warn(f"  {log.WARNING} kept cub's folder: files wait in its out/", fix=f"{log.cmd('og take cub --all')}, then {log.cmd('og tidy --rm')}")
PY
)
  local plain; plain=$(sed 's/\x1b\[[0-9;]*m//g' <<<"$o")
  [ "$(sed -n 2p <<<"$plain")" = "               og take cub --all, then og tidy --rm" ] && [[ "$o" == *$'\e[1;38;2;125;196;228mog take cub --all'* ]]; }
expect_cmd 0 "…on a terminal it sits under the warning's text, the commands bold in og's color" fix_look
short_script() { [ "$(pyrun 'from ogun.core import sbx; print(sbx._short("a\nb\nc"), sbx._short("ls"))')" = "<script, 3 lines> ls" ]; }
expect_cmd 0 "-v shows a script sent into a sandbox as its line count, not its text" short_script

# ── more detail on request: -v each sbx command and how it ended, -vv what it printed ──
cat > "$FIX/bin/sbx" <<'STUB'
#!/bin/sh
[ "$1" = ls ] && { printf 'SANDBOX  AGENT  STATUS\ncub  claude  running\n'; exit 0; }
[ "$1 $2" = "policy allow" ] && { echo "allowed it"; exit 0; }
exit 0
STUB
chmod +x "$FIX/bin/sbx"
quiet_default() { local e; e=$("$OG" allow cub example.com 2>&1 >/dev/null); [[ "$e" != *'$ sbx'* ]]; }
expect_cmd 0 "by default no sbx command is shown" quiet_default
v1() { local e; e=$("$OG" -v allow cub example.com 2>&1 >/dev/null)
  [[ "$e" == *'$ sbx policy allow network --sandbox cub example.com'* && "$e" == *"↳ exit 0"* && "$e" != *"out│"* ]]; }
expect_cmd 0 "-v: each sbx command and how it ended, on stderr" v1
v_after() { local e; e=$("$OG" allow cub example.com -v 2>&1 >/dev/null); [[ "$e" == *'$ sbx ls'* ]]; }
expect_cmd 0 "…anywhere in a ported command" v_after
v2() { local e; e=$("$OG" -vv allow cub example.com 2>&1 >/dev/null); [[ "$e" == *"out│ cub  claude  running"* ]]; }
expect_cmd 0 "-vv: what each printed too" v2
plain_piped() { local o; o=$("$OG" allow cub example.com 2>&1); [[ "$o" != *$'\033'* ]]; }
expect_cmd 0 "piped, nothing is colored: the plain words the tests grep" plain_piped


# ── the sandbox names tab completion reads, kept by og's sbx gateway (sbx.py) ──
names_kept() { local d="$FIX/names-state" b="$FIX/names-bin"; rm -rf "$d"; mkdir -p "$b"
  printf '#!/bin/sh\n[ "$1" = ls ] && printf "SANDBOX  AGENT  STATUS\\nalpha  claude  running\\nbeta  claude  stopped\\n"\nexit 0\n' > "$b/sbx"; chmod +x "$b/sbx"
  PATH="$b:$PATH" XDG_STATE_HOME="$d" pyrun 'from ogun.core import sbx; sbx.ls()' || return 1
  [[ "$(cat "$d/ogun/sandbox-names")" == $'alpha\nbeta' ]] || return 1
  PATH="$b:$PATH" XDG_STATE_HOME="$d" pyrun 'from ogun.core import sbx; sbx.run("rm", "alpha", "--force")' || return 1
  [[ "$(cat "$d/ogun/sandbox-names")" == beta ]] || return 1
  # a listing that failed changes nothing
  printf '#!/bin/sh\nexit 1\n' > "$b/sbx"
  PATH="$b:$PATH" XDG_STATE_HOME="$d" pyrun 'from ogun.core import sbx; sbx.ls()'; [[ "$(cat "$d/ogun/sandbox-names")" == beta ]]; }
expect_cmd 0 "og keeps the names completion offers: each sbx ls writes them, an sbx rm drops one, a failed ls changes nothing" names_kept

# ── og itself, as a person or a script runs it ──
entry_sbx() { local b="$FIX/entry-bin"; mkdir -p "$b"
  printf '#!/bin/sh\n[ "$1" = ls ] && { printf "SANDBOX  AGENT  STATUS\\ncub  claude  running\\n"; exit 0; }\n[ "$1 $2" = "policy ls" ] && exit 0   # a read, not logged\necho "$*" >> "%s/entry.log"\n' "$FIX" > "$b/sbx"
  chmod +x "$b/sbx"; : > "$FIX/entry.log"; printf '%s' "$b"; }
entry_v() { local b e; b=$(entry_sbx); e=$(PATH="$b:$PATH" OG_VERBOSE='' "$OG" -v allow cub example.com 2>&1 >/dev/null) || return 1
  [[ "$e" == *'$ sbx policy allow network --sandbox cub example.com'* ]] && [ "$(cat "$FIX/entry.log")" = "policy allow network --sandbox cub example.com" ]; }
expect_cmd 0 "og -v: each sbx command on stderr" entry_v
entry_help() { local b o; b=$(entry_sbx); o=$(PATH="$b:$PATH" "$OG" allow cub example.com --help 2>&1) || return 1
  [[ "$o" == *"usage: og allow"* && "$o" == *"Examples:"* && "$o" == *"--read-only"* ]] && [ ! -s "$FIX/entry.log" ]; }
expect_cmd 0 "…og allow --help is its help, each form and examples, and allows nothing" entry_help
# a bare og is the commonest call of all: it reaches og's create path with no
# command, and nothing around it may say anything of its own
entry_bare() { local b e; b=$(entry_sbx); for args in "" "--no-attach"; do
    # shellcheck disable=SC2086  # no arguments, or one flag: split on purpose
    e=$(cd "$FIX" && PATH="$b:$PATH" "$OG" $args </dev/null 2>&1 >/dev/null)
    ! grep -qE "Traceback|^(bash|environment): " <<<"$e" || { echo "[$args] $e"; return 1; }; done; }
expect_cmd 0 "a bare og, and one with only flags: no error from anything but og" entry_bare

summarize
