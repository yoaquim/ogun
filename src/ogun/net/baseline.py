"""This Mac's network baseline (og's baseline.env, beside this module): its allowed hosts, sbx's broad
default rules taken out, and the ssh-agent guard, which keeps sbx from forwarding
the Mac's agent."""

import re
from pathlib import Path

from ogun.core import config, log, sbx
from ogun.net import ruletable

BASELINE_FILE = Path(__file__).with_name("baseline.env")   # og's own default
LISTS = ("SBX_BASELINE_DOMAINS", "SBX_BASELINE_HTTP", "SBX_DEFAULT_RULES_OFF")
_ENV_LINE = re.compile(r'^([A-Z_]+)="(.*)"$')


def baseline_lists() -> dict[str, str]:
    """The baseline's lists: baseline.env in og's config folder when there is
    one, replacing og's own whole (no merge: what's allowed is one file's
    content), else og's own."""
    text = config.read_text("baseline.env")
    if text is None:
        got = lists_in(BASELINE_FILE.read_text())
    else:
        got = lists_in(text, "baseline.env")
        for k in LISTS:   # each one og applies: a list left out is no list, never og's own
            if k not in got:
                raise config.unreadable("baseline.env", f'has no {k} (an empty list is {k}="")')
    return got



def lists_in(text: str, name: str = "") -> dict[str, str]:
    """NAME="value" lines, as any other reader parses them; comments and blank lines
    aside, any other line stops og (the config folder's file, name)."""
    out = {}
    for n, line in enumerate(text.splitlines(), 1):
        m = _ENV_LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
        elif line.strip() and not line.lstrip().startswith("#"):
            if name:
                raise config.unreadable(name, f"line {n} isn't NAME=\"value\"")
            raise ValueError(f"og's own baseline.env, line {n}, isn't NAME=\"value\"")
    return out


def _http_rules(spec: str) -> list[tuple[str, str, str]]:
    """"<host>=<methods>[=<path glob>]", space-separated → (host, methods, path)."""
    rules = []
    for hm in spec.split():
        host, _, rest = hm.partition("=")
        methods, _, path = rest.partition("=")
        rules.append((host, methods, path))
    return rules


def baseline() -> bool:
    """The egress every sandbox gets: whole-host allows only where nobody
    hostile can write, read-only HTTP rules for registries and GitHub, and
    sbx's default rules removed."""
    b = baseline_lists()
    # an empty list is no whole-host allow (sbx refuses an empty one), not a failure
    domains = b["SBX_BASELINE_DOMAINS"].strip()
    if domains and not ruletable.allow_twice("policy", "allow", "network", domains):
        return False
    good = True
    for host, methods, path in _http_rules(b["SBX_BASELINE_HTTP"]):
        good = ruletable.allow_twice("policy", "allow", "network", host, "--method", methods, *(["--path", path] if path else [])) and good
    return default_rules_off() and good


def default_rules_off(why: str = "") -> bool:
    """Remove each sbx default rule Ogun keeps off that sbx lists; quiet when
    none is back. An sbx upgrade may restore one, so this runs with every
    baseline and on every attach."""
    good = True
    for r in baseline_lists()["SBX_DEFAULT_RULES_OFF"].split():
        if sbx.run("policy", "inspect", r).returncode:
            continue   # already gone
        # --force: its y/N prompt would sit unseen, or fail with no terminal
        if sbx.run("policy", "rm", "network", "--id", r, "--force").returncode == 0:
            log.note(f"removed sbx's default rule {r}{f' ({why})' if why else ''}", err=True)
            log.record(f"removed sbx's default rule {r}")
        else:
            log.warn(f"  {log.WARNING} could not remove sbx's default rule {r} — by hand:", err=True,
                     fix=log.cmd(f"sbx policy rm network --id {r} --force"))
            good = False
    return good


# ── the ssh-agent guard ──

_AGENT_KEY = "ssh.agentForwardingEnabled"


def agent_forwarding_off() -> bool | None:
    """Only reads: whether sbx's setting plainly says the agent isn't forwarded
    (og doctor asks; ssh_agent_off sets it when it isn't); None when sbx couldn't
    say. Fail closed: anything but a plain `false` reads as on."""
    p = sbx.run("settings", "get", _AGENT_KEY)
    if p.returncode != 0:
        return None
    # split on newline, then space and tab only, never the other characters Python
    # counts as breaks, so `false\r` is not off
    lines = [x for x in p.stdout.split("\n") if x.strip(" \t")]
    line = lines[-1] if lines else ""
    if _AGENT_KEY in line:
        line = line.split(_AGENT_KEY, 1)[1]
    words = [w for w in re.split(r"[ \t]+", line.replace(":", " ").replace("=", " ")) if w]
    return bool(words) and words[0] == "false"


def default_rules_back() -> list[str]:
    """Only reads: the sbx default rules og keeps off that sbx shows again (an
    upgrade can restore one). One sbx couldn't inspect reads as gone, as
    default_rules_off reads it."""
    back = []
    for r in baseline_lists()["SBX_DEFAULT_RULES_OFF"].split():
        p = sbx.run("policy", "inspect", r)
        if p.returncode == 0:
            back.append(r)
    return back


def baseline_missing() -> list[str] | None:
    """Only reads: the baseline's hosts with no every-sandbox allow sbx lists,
    as og policy would add them; None when sbx couldn't list its rules."""
    rules = ruletable.read_rules()
    if rules is None:
        return None
    def key(t, host, methods="", path=""):
        # an http rule is its host, methods (in any order) and path: github.com's
        # GET,HEAD and its POST to git-upload-pack are two rules, each needed
        m = frozenset(x for x in methods.upper().split(",") if x and x != "-")
        return (t, host.removesuffix("/**").removesuffix(":443"), m, (path or "/**") if t == "http" else "")
    have = {key(r["type"], res, r["method"], r["path"]) for r in rules
            if r["scope"] == "all" and r["decision"] == "allow" for res in r["res"]}
    hosts = {k[1] for k in have if k[0] == "network"}   # a whole-host allow covers any request to it
    b = baseline_lists()
    out = [h for h in b["SBX_BASELINE_DOMAINS"].split(",") if h and h not in hosts]
    out += [f"{h} {m}{f' {pth}' if pth else ''}" for h, m, pth in _http_rules(b["SBX_BASELINE_HTTP"])
            if h not in hosts and key("http", h, m, pth) not in have]
    return sorted(set(out))


def ssh_agent_off(cmd: str = "policy") -> bool:
    """Sandboxes must not see the Mac's ssh-agent: it holds the host's keys,
    perhaps a commit-signing one, so a sandbox could sign
    with it and push over SSH past its token. sbx forwards it by default and
    `sbx setup` turns it back on, so every create checks. The setting reaches
    the daemon only on a restart, which stops running sandboxes: that stays
    your call. cmd: the og command running it, for its error lines."""
    if agent_forwarding_off():
        return True
    s = sbx.run("settings", "set", _AGENT_KEY, "false")
    if s.returncode:
        log.err(f"og {cmd}: sbx shares this Mac's ssh-agent with sandboxes and couldn't turn it off — needs sbx ≥ 0.42.1, then:",
                fix=log.cmd("sbx settings set ssh.agentForwardingEnabled false"))
        ruletable.sbx_said(s)
        return False
    log.record("ssh-agent forwarding set off (applies after sbx daemon restart)")
    log.err(f"og {cmd}: ssh-agent forwarding is now off, but only after sbx restarts (running sandboxes stop) — run this, then run your og command again:",
            fix=log.cmd("sbx daemon restart"))
    return False
