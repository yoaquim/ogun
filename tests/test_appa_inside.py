"""appa inside: the OpenAPPA scripts that run INSIDE a sandbox (docs/appa.md):
sandbox-scripts/appa/{policy.py,ensure.sh,activate.sh}, with og's stand-in
provision command. Each case gets
its own HOME; `appa` is a fake that does what the real one leaves behind
(hooks, policy, a runtime answering /health on a port of its own), so nothing
reaches the network or the machine's own ~/.claude."""

import json
import os
import random
import shutil
import subprocess
import tomllib
import urllib.request
from pathlib import Path

import pytest

from conftest import FIXTURES
from ogun.core import paths

# the runtime: answers /health on the --listen port until killed
SERVER = """import http.server, sys
host, port = sys.argv[1].rsplit(":", 1)
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404); self.end_headers()
    def log_message(self, *a): pass
http.server.HTTPServer((host, int(port)), H).serve_forever()
"""

# the appa the plugin install leaves in ~/.local/share/appa/bin
DATA_APPA = r"""#!/bin/sh
case "$1" in
  describe) [ -n "${FAKE_DESCRIBE_FAIL:-}" ] && exit 1   # as the real one: it parses, and no hint over 512 characters
            python3 -c 'import sys, tomllib; d = tomllib.load(open(sys.argv[1], "rb")); sys.exit(any(len(a.get("hint", "")) > 512 for a in d.get("policy", {}).get("annotator", [])))' "$3" ;;
  runtime) [ "${2:-}" = stop ] && { pkill -f "@FIX@/server.py" 2>/dev/null; exit 0; }
           [ -n "${FAKE_RUNTIME_FAIL:-}" ] && exit 1
           l=127.0.0.1:8787; while [ $# -gt 0 ]; do [ "$1" = --listen ] && l=$2; shift; done
           echo "${APPA_PROVIDER_GITHUB_TOKEN:-unset}" > "$HOME/runtime.token"
           exec python3 "@FIX@/server.py" "$l" ;;
esac
"""

# the appa on PATH: `plugin install claude-code` writes what the real one does
APPA = r"""#!/bin/sh
[ "$1 $2" = "plugin install" ] || exit 2
d=$HOME/.local/share/appa c=$HOME/.config/appa
mkdir -p "$d/bin" "$c/batteries/coding" "$HOME/.claude/skills/appa-guide"
cp "@FIX@/data-appa" "$d/bin/appa"; chmod +x "$d/bin/appa"
printf '[policy]\nversion = 2\n# put the mapping under [policy] here:\n#   [policy.audience]\n' > "$c/appa.toml"
printf '[policy]\nversion = 2\n[[policy.annotator]]\nname = "claude-code.bash-repository-requirements"\nbuiltin = "claude-code"\nhint = "BATTERY-HINT"\n' > "$c/batteries/coding/appa.toml"
printf '{"statusLine": {"type": "command", "command": "appa statusline"}}' > "$d/clappa.settings.json"
echo appa-guide > "$HOME/.claude/skills/appa-guide/SKILL.md"
[ -n "${FAKE_NO_HOOKS:-}" ] && exit 0
python3 - "$HOME/.claude/settings.json" "$d/bin/appa" <<'PY'
import json, sys
p, cmd = sys.argv[1], sys.argv[2]
s = json.load(open(p))
for ev in ("PreToolUse", "SessionStart", "Stop"):
    s.setdefault("hooks", {}).setdefault(ev, []).append({"matcher": "*", "hooks": [{"type": "command", "command": cmd, "args": ["hook"]}]})
json.dump(s, open(p, "w"))
PY
"""

# GitHub's answer about the origin, as `gh api repos/<slug> --jq .private` gives it
GH = r"""#!/bin/sh
echo "$*" >> "@FIX@/gh.log"
[ -n "${FAKE_GH_FAIL:-}" ] && exit 1
echo "${FAKE_GH_PRIVATE:-true}"
"""


class Fix:
    """The fakes, og's OpenAPPA scripts as og unpacks them in a sandbox, the
    provision command activation runs again (og's stand-in), and a runtime port
    that is never 8787."""

    def __init__(self, root):
        self.root = root
        (root / "bin").mkdir(parents=True)
        self.provision = str(FIXTURES / "provision.sh")
        self.appa = root / "appa"
        shutil.copytree(paths.SCRIPTS / "appa", self.appa, ignore=shutil.ignore_patterns("__pycache__"))
        self.url = f"http://127.0.0.1:{random.randint(20000, 39999)}"
        (root / "server.py").write_text(SERVER)
        for f, body in ((root / "data-appa", DATA_APPA), (root / "bin/appa", APPA), (root / "bin/gh", GH)):
            f.write_text(body.replace("@FIX@", str(root)))
            f.chmod(0o755)

    def stop_servers(self) -> None:
        subprocess.run(["pkill", "-f", str(self.root / "server.py")], capture_output=True)

    def servers(self) -> int:
        p = subprocess.run(["pgrep", "-f", str(self.root / "server.py")], capture_output=True, text=True)
        return len(p.stdout.split())

    def healthy(self) -> bool:
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f"{self.url}/health", timeout=2) as r:
                return r.status == 200
        except OSError:
            return False


@pytest.fixture(scope="module")
def fix(tmp_path_factory):
    f = Fix(tmp_path_factory.mktemp("appa-sbx"))
    yield f
    f.stop_servers()


class Box:
    """A sandbox's HOME with a workspace repo whose origin is given."""

    def __init__(self, fix, h, origin):
        self.fix, self.h, self.ws = fix, h, h / "ws"
        h.mkdir()
        subprocess.run(["git", "init", "-q", str(self.ws)], check=True)
        if origin:
            subprocess.run(["git", "-C", str(self.ws), "remote", "add", "origin", origin], check=True)
        self.pol = h / "pol/appa.toml"

    def env(self, **kw) -> dict:
        e = {k: v for k, v in os.environ.items() if not k.startswith("XDG_")}
        return {**e, "HOME": str(self.h), "PATH": f"{self.fix.root / 'bin'}{os.pathsep}{e['PATH']}",
                "APPA_RUNTIME_URL": self.fix.url, **kw}

    def run(self, *cmd, stdin=None, **kw) -> subprocess.CompletedProcess:
        return subprocess.run([str(c) for c in cmd], input=stdin, capture_output=True, text=True, env=self.env(**kw))

    # policy.py on a root policy of this content, the battery's hint beside it
    def policy(self, content: str, *args, **kw) -> subprocess.CompletedProcess:
        self.pol.parent.mkdir(exist_ok=True)
        self.pol.write_text(content)
        (self.pol.parent / "batteries/coding").mkdir(parents=True, exist_ok=True)
        (self.pol.parent / "batteries/coding/appa.toml").write_text(
            '[[policy.annotator]]\nname = "claude-code.bash-repository-requirements"\nhint = "BATTERY-HINT"\n')
        return self.policy_again(*(args or (self.ws, "/ro/notes")), **kw)

    def policy_again(self, *args, **kw) -> subprocess.CompletedProcess:
        return self.run("python3", self.fix.appa / "policy.py", self.pol, *args, **kw)

    def text(self) -> str:
        return self.pol.read_text()

    def ensure(self, *args, **kw) -> subprocess.CompletedProcess:
        return self.run("bash", self.fix.appa / "ensure.sh", *args, **kw)

    def activate(self, *args, **kw) -> subprocess.CompletedProcess:
        kw.setdefault("OG_PROVISION_CMD", self.fix.provision)   # og's provision command
        return self.run("bash", self.fix.appa / "activate.sh", "v0.37.0", self.ws, *(args or ("/ro/notes",)), **kw)

    def install(self) -> None:
        """OpenAPPA installed and turned on as activate.sh leaves it, before ensure.sh."""
        (self.h / ".claude").mkdir()
        (self.h / ".claude/settings.json").write_text("{}")
        assert self.run("appa", "plugin", "install", "claude-code").returncode == 0
        hooks = json.loads((self.h / ".claude/settings.json").read_text()).get("hooks") or {}
        mine = {ev: [e for e in v if any((x.get("command") or "").endswith("/appa") for x in e.get("hooks") or [])]
                for ev, v in hooks.items()}
        (self.h / ".local/share/appa/ogun-hooks.json").write_text(json.dumps(mine))
        (self.h / ".config/ogun").mkdir(parents=True)
        (self.h / ".config/ogun/appa").write_text("v0.37.0\n")

    def clappa(self) -> dict:
        return json.loads((self.h / ".local/share/appa/clappa.settings.json").read_text())


@pytest.fixture
def box(fix, tmp_path):
    """A fresh sandbox HOME, its origin a private GitHub repo; no runtime up."""
    fix.stop_servers()
    made = []

    def make(origin="https://github.com/octocat/secret.git"):
        b = Box(fix, tmp_path / f"home{len(made)}", origin)
        made.append(b)
        return b

    yield make
    fix.stop_servers()


ROOT = "[policy]\nversion = 2\n"


def policy_of(b) -> dict:
    return tomllib.loads(b.text())["policy"]


def hints_fit(b) -> bool:
    return all(len(a["hint"]) <= 512 for a in policy_of(b)["annotator"])


# ── policy.py: Ogun's block in OpenAPPA's root policy ──

def test_the_block_self_is_the_tokens_account_mounts_narrow_to_self_both_hints_the_batterys_kept(box):
    b = box()
    assert b.policy(ROOT).returncode == 0
    p = policy_of(b)
    tools, ann = {t["name"]: t for t in p["tool"]}, {a["name"]: a for a in p["annotator"]}
    assert p["audience"]["self"] == ["github:viewer"]
    for root in (str(b.ws), "/ro/notes"):
        assert tools[f"tool/coding/read_file(file_path:{root}/*)"]["delta"] == {"audience": ["self"]}
        assert tools[f"tool/coding/search_files(path:{root}*)"]["delta"] == {"audience": ["self"]}
    assert str(b.ws) in ann["claude-code.bash-requirements"]["hint"] and "/ro/notes" in ann["claude-code.bash-requirements"]["hint"]
    repo = ann["claude-code.bash-repository-requirements"]["hint"]
    assert repo.startswith("BATTERY-HINT ") and "github.com/octocat/secret" in repo and "audience self" in repo


def test_a_rerun_replaces_the_block_never_adds_a_second(box):
    b = box()
    assert b.policy(ROOT).returncode == 0 and b.policy_again(b.ws).returncode == 0
    assert b.text().count(">>> ogun") == 1 and b.text().count("<<< ogun") == 1 and "/ro/notes" not in b.text()


def test_an_audience_table_only_in_a_comment_doesnt_count_as_one(box):
    b = box()
    assert b.policy(ROOT + "# put it here:\n#   [policy.audience]\n").returncode == 0
    assert any(line == "[policy.audience]" for line in b.text().splitlines())


def test_a_real_audience_table_is_left_alone_toml_allows_one(box):
    b = box()
    assert b.policy(ROOT + '[policy.audience]\nself = ["github:someone"]\n').returncode == 0
    assert b.text().splitlines().count("[policy.audience]") == 1 and "github:someone" in b.text()


def test_an_origin_off_github_is_named_as_it_is(box):
    b = box("https://gitlab.example.com/acme/orders.git")
    assert b.policy(ROOT).returncode == 0 and "origin, https://gitlab.example.com/acme/orders.git" in b.text()


def test_a_github_origins_visibility_is_asked_of_github_by_owner_and_repo(box, fix):
    b = box()
    (fix.root / "gh.log").unlink(missing_ok=True)
    assert b.policy(ROOT).returncode == 0
    assert "api repos/octocat/secret --jq .private" in (fix.root / "gh.log").read_text().splitlines()


@pytest.mark.parametrize("kw", [{"FAKE_GH_PRIVATE": "false"}, {"FAKE_GH_FAIL": "1"}], ids=["public", "github doesn't answer"])
def test_a_public_origin_or_one_github_doesnt_answer_for_gets_no_push_exception(box, kw):
    b = box()
    assert b.policy(ROOT, **kw).returncode == 0
    assert "bash-repository-requirements" not in b.text() and "bash-requirements" in b.text()


def test_no_origin_no_push_hint(box):
    b = box(origin="")
    assert b.policy(ROOT).returncode == 0 and "bash-repository-requirements" not in b.text()


def test_private_places_are_named_in_the_push_hint_even_with_a_public_origin_never_taken_for_mounts(box):
    b = box()
    assert b.policy(ROOT, FAKE_GH_PRIVATE="false").returncode == 0
    assert b.policy_again(b.ws, "--private", "gitlab.example.com/acme/assets", "--private", "gitlab.example.com/acme/docs", "/ro/notes",
                          FAKE_GH_PRIVATE="false").returncode == 0
    p = policy_of(b)
    repo = {a["name"]: a["hint"] for a in p["annotator"]}["claude-code.bash-repository-requirements"]
    assert "gitlab.example.com/acme/assets, gitlab.example.com/acme/docs" in repo and "own origin" not in repo
    assert any(t["name"] == "tool/coding/read_file(file_path:/ro/notes/*)" for t in p["tool"])
    assert not any("--private" in t["name"] or "acme/assets" in t["name"] for t in p["tool"])


def test_private_places_beside_a_private_origin_are_one_sentence(box):
    b = box()
    assert b.policy(ROOT).returncode == 0
    assert b.policy_again(b.ws, "--private", "gitlab.example.com/acme/assets").returncode == 0
    assert "own origin, github.com/octocat/secret or into gitlab.example.com/acme/assets" in b.text()


def test_too_many_private_places_for_the_hint_are_refused_the_file_untouched(box):
    b = box()
    b.pol.parent.mkdir()
    b.pol.write_text(ROOT)
    many = [a for i in range(1, 13) for a in ("--private", f"git.example.com/a-rather-long-owner-name/repository-number-{i}")]
    p = b.policy_again(b.ws, *many)
    assert p.returncode != 0 and "too long" in p.stderr and ">>> ogun" not in b.text()


def test_a_battery_hint_too_long_to_add_to_keeps_its_rules_in_fewer_words_under_512(box):
    b = box()
    assert b.policy(ROOT).returncode == 0
    (b.pol.parent / "batteries/coding/appa.toml").write_text(
        f'[[policy.annotator]]\nname = "claude-code.bash-repository-requirements"\nhint = "{"B" * 480}"\n')
    assert b.policy_again(b.ws).returncode == 0
    assert hints_fit(b) and "doesn't establish" in b.text() and "BBBB" not in b.text()


def test_a_battery_hint_that_fits_is_kept_word_for_word_ogun_s_exception_after_it(box):
    b = box()
    assert b.policy(ROOT).returncode == 0 and hints_fit(b) and "BATTERY-HINT Except" in b.text()


def test_many_read_only_mounts_each_get_their_read_rules_and_the_shell_hint_stays_under_512(box):
    b = box()
    b.pol.parent.mkdir()
    b.pol.write_text(ROOT)
    mounts = [f"/Volumes/octocat/Projects/personal/a-rather-long-related-repository-name-{i}" for i in range(1, 13)]
    assert b.policy_again(b.ws, *mounts).returncode == 0
    assert hints_fit(b) and f"{mounts[11]}/*" in b.text()


def test_a_policy_that_doesnt_parse_is_never_written_over(box):
    b = box()
    b.pol.parent.mkdir()
    b.pol.write_text("[policy\n")
    assert b.policy_again(b.ws).returncode != 0 and b.text() == "[policy\n"


# ── ensure.sh: hooks in place, runtime up, or no session ──

def test_ensure_installed_but_never_turned_on_exits_3_for_ogun_to_activate(box, fix):
    b = box()
    b.install()
    (b.h / ".config/ogun/appa").unlink()
    p = b.ensure()
    assert p.returncode == 3 and "never turned on" in p.stdout + p.stderr and not fix.healthy()


def test_ensure_with_no_saved_hooks_is_no_session(box):
    b = box()
    b.install()
    (b.h / ".local/share/appa/ogun-hooks.json").unlink()
    p = b.ensure()
    assert p.returncode != 0 and "no saved OpenAPPA hooks" in p.stdout + p.stderr


def test_ensure_puts_back_the_hooks_a_provision_dropped_keeping_what_it_wrote(box, fix):
    b = box()
    b.install()
    saved = json.loads((b.h / ".local/share/appa/ogun-hooks.json").read_text())
    mine = {"type": "command", "command": "/x/mine"}
    # a provision command that rewrote settings.json its own way: no OpenAPPA hook, one of its own
    (b.h / ".claude/settings.json").write_text(json.dumps({"model": "m", "hooks": {"Stop": [{"hooks": [mine]}]}}))
    assert b.ensure().returncode == 0 and fix.healthy()
    s = json.loads((b.h / ".claude/settings.json").read_text())
    assert s["model"] == "m" and s["hooks"]["Stop"][0] == {"hooks": [mine]}
    assert all(e in s["hooks"][ev] for ev, es in saved.items() for e in es)
    assert b.ensure().returncode == 0
    assert json.loads((b.h / ".claude/settings.json").read_text()) == s   # once: never added twice


def test_ensure_with_settings_it_cant_read_is_no_session(box):
    b = box()
    b.install()
    (b.h / ".claude/settings.json").write_text("{not json")
    p = b.ensure()
    assert p.returncode != 0 and "could not read ~/.claude/settings.json" in p.stdout + p.stderr


def test_ensure_starts_a_runtime_that_isnt_running_with_the_sandboxs_github_token_placeholder(box, fix):
    b = box()
    b.install()
    assert not fix.healthy()
    assert b.ensure(GH_TOKEN="placeholder").returncode == 0 and fix.healthy()
    assert (b.h / "runtime.token").read_text().strip() == "placeholder"


def test_ensure_leaves_a_runtime_thats_up_alone(box, fix):
    b = box()
    b.install()
    assert b.ensure().returncode == 0 and fix.healthy()
    n = fix.servers()
    assert b.ensure().returncode == 0 and fix.servers() == n


def test_a_runtime_that_wont_start_is_no_session_and_says_where_its_log_is(box):
    b = box()
    b.install()
    p = b.ensure("3", FAKE_RUNTIME_FAIL="1")   # three asks, not ogun's fifty: the same no
    assert p.returncode != 0 and "runtime didn't answer" in p.stdout + p.stderr


def hook(b) -> Path:
    """og's status line hook in the sandbox, as a provision command might leave it."""
    h = b.h / ".config/ogun/appa-statusline"
    h.parent.mkdir(parents=True, exist_ok=True)
    h.write_text("#!/bin/sh\necho mine\n")
    h.chmod(0o755)
    return h


def test_a_status_line_whose_script_is_gone_is_pointed_at_the_hook_the_rest_kept(box):
    b = box()
    b.install()
    hook(b)
    cs = b.h / ".local/share/appa/clappa.settings.json"
    cs.write_text(json.dumps({"statusLine": {"type": "command", "command": f'"{b.h}/old/line.sh"'}, "keep": 1}))
    assert b.ensure().returncode == 0
    assert b.clappa()["statusLine"]["command"] == f'"{b.h}/.config/ogun/appa-statusline"' and b.clappa()["keep"] == 1


def test_one_whose_script_is_there_or_with_no_hook_is_left_alone(box):
    b = box()
    b.install()
    cs = b.h / ".local/share/appa/clappa.settings.json"
    gone = {"statusLine": {"type": "command", "command": f'"{b.h}/old/line.sh"'}}
    cs.write_text(json.dumps(gone))
    assert b.ensure().returncode == 0 and b.clappa() == gone
    hook(b)
    cs.write_text(json.dumps({"statusLine": {"type": "command", "command": "appa statusline"}}))
    assert b.ensure().returncode == 0 and b.clappa()["statusLine"]["command"] == "appa statusline"


# ── activate.sh: everything, or nothing claimed ──

def activated(b, fix) -> subprocess.CompletedProcess:
    """activate.sh run as ogun runs it, then each thing it leaves checked."""
    (b.h / ".claude").mkdir()
    p = b.activate()
    assert p.returncode == 0, p.stdout + p.stderr
    skills = b.h / ".claude/skills"
    assert (b.h / ".config/ogun/appa").read_text().strip() == "v0.37.0"
    assert skills.is_dir() and not skills.is_symlink() and (skills / "appa-guide/SKILL.md").is_file()
    assert sorted(json.loads((b.h / ".local/share/appa/ogun-hooks.json").read_text())) == ["PreToolUse", "SessionStart", "Stop"]
    toml = (b.h / ".config/appa/appa.toml").read_text()
    assert ">>> ogun" in toml and f"{b.ws}/*" in toml
    assert b.clappa()["statusLine"]["command"] == f'"{b.h}/.config/ogun/appa-statusline"'
    assert fix.healthy() and "OpenAPPA v0.37.0 on" in p.stdout + p.stderr
    return p


def test_activate_marker_writable_skills_hooks_saved_the_block_the_status_line_a_runtime_up(box, fix):
    activated(box(), fix)


def test_activate_with_no_provision_command_makes_the_skills_folder_itself_and_turns_openappa_on(box, fix):
    b = box()
    (b.h / ".claude").mkdir()
    p = b.activate(OG_PROVISION_CMD="")
    assert p.returncode == 0, p.stdout + p.stderr
    skills = b.h / ".claude/skills"
    assert skills.is_dir() and not skills.is_symlink() and (skills / "appa-guide/SKILL.md").is_file() and fix.healthy()
    # no provision command, so no hook: the plugin's own line stays, never one that doesn't exist
    assert b.clappa()["statusLine"]["command"] == "appa statusline"


def test_a_provision_command_that_sets_up_no_claude_config_still_gets_openappa_its_folder(box, fix):
    # provision is anyone's setup: one that leaves no ~/.claude must not cost the sandbox
    b = box()
    p = b.activate(OG_PROVISION_CMD="true")
    assert p.returncode == 0, p.stdout + p.stderr
    skills = b.h / ".claude/skills"
    assert skills.is_dir() and not skills.is_symlink() and (skills / "appa-guide/SKILL.md").is_file() and fix.healthy()


def test_activate_refuses_a_skills_link_it_can_t_turn_into_a_folder(box):
    b = box()
    (b.h / ".claude").mkdir()
    (b.h / ".claude/skills").symlink_to(b.h)
    p = b.activate(OG_PROVISION_CMD="")
    assert p.returncode != 0 and "is still a link" in p.stdout + p.stderr


def test_activate_passes_private_places_to_the_block_beside_the_mounts(box):
    b = box()
    (b.h / ".claude").mkdir()
    assert b.activate("--private", "gitlab.example.com/acme/assets", "/ro/notes").returncode == 0
    toml = (b.h / ".config/appa/appa.toml").read_text()
    assert "gitlab.example.com/acme/assets" in toml and "/ro/notes/*" in toml


def test_an_install_that_adds_no_hooks_fails_activation(box):
    b = box()
    (b.h / ".claude").mkdir()
    p = b.activate(FAKE_NO_HOOKS="1")
    assert p.returncode != 0 and "added no hooks" in p.stdout + p.stderr


def test_a_policy_openappa_rejects_fails_activation_before_any_runtime_starts(box, fix):
    b = box()
    (b.h / ".claude").mkdir()
    p = b.activate(FAKE_DESCRIBE_FAIL="1")
    assert p.returncode != 0 and "OpenAPPA rejects the policy" in p.stdout + p.stderr and not fix.healthy()


def test_activation_runs_the_provision_command_again_once_the_marker_is_written(box, fix):
    b = box()
    activated(b, fix)
    assert (b.h / "provision.log").read_text().splitlines() == ["provisioned, marker v0.37.0"]
