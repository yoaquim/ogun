"""`og ports` and `og doctor`: a sandbox's published ports, and how this Mac's
sbx and og stand. Both read sbx's --json (its shapes held in
tests/test_health.py); og ports also publishes and unpublishes."""

import json
import re

from ogun.core import boxes, log, sbx
from ogun.core.log import shown
from ogun.net import baseline
from ogun.sandbox import sandboxes

PORTS_USAGE = "<name> [[<mac port>:]<port>... | --rm <port>...]"
PORTS_HELP = dict(
    about="Reach a service inside a sandbox from this Mac, at 127.0.0.1.",
    forms=[
        ("og ports <name>", "what's published: this Mac's address, the sandbox's port"),
        ("og ports <name> <port>…", "publish that sandbox port, on a free port of this Mac"),
        ("og ports <name> <mac port>:<port>", "publish it on that port of this Mac"),
        ("og ports <name> --rm <port>…", "unpublish that sandbox port"),
    ],
    notes=["Only this Mac reaches it (127.0.0.1). A service inside must listen on 0.0.0.0, not 127.0.0.1, "
           "to be reachable. Publishing starts a stopped sandbox."],
    examples=["og ports cub", "og ports cub 3000", "og ports cub 8080:3000", "og ports cub --rm 3000"],
)


def ports_usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("ports", PORTS_USAGE, problem=problem, err=err, **PORTS_HELP)


def _published(name: str) -> list[dict] | None:
    p = sbx.run("ports", name, "--json", wait=f"reading {name}'s ports")
    try:
        d = json.loads(p.stdout) if p.returncode == 0 else None
    except ValueError:
        return None
    return [x for x in d if isinstance(x, dict)] if isinstance(d, list) else None


def _addr(x: dict) -> str:
    ip = str(x.get("host_ip", ""))
    return f"[{ip}]:{x.get('host_port')}" if ":" in ip else f"{ip}:{x.get('host_port')}"


_SPEC = re.compile(r"(?:(\d{1,5}):)?(\d{1,5})(?:/(tcp|tcp4|tcp6|udp|udp4|udp6))?")


def ports(args: list[str]) -> int:
    """Loopback only: a spec naming another address of this Mac is refused,
    since it would reach the sandbox's service from the network."""
    if not args or args[0].startswith("-"):
        ports_usage("og ports needs a sandbox name")
        return 1
    name, rest = args[0], args[1:]
    rm = rest[:1] == ["--rm"]
    specs = rest[1:] if rm else rest
    if rm and not specs:
        ports_usage("og ports: --rm needs the sandbox ports to unpublish")
        return 1
    if spec_refused(specs, rm):
        return 1
    if sandboxes.find("ports", name) is None:
        return 1
    before = _published(name)
    if before is None:
        log.err(f"og ports: sbx couldn't list {name}'s ports")
        return 1
    if not specs:
        listing(name, before)
        return 0
    return unpublish(name, specs, before) if rm else publish(name, specs, before)


def spec_refused(specs: list[str], rm: bool) -> bool:
    """A spec that isn't a port (or, with --rm, the sandbox's port alone), or
    that names an address: refused, and said, before sbx is asked."""
    for sp in specs:
        if not _SPEC.fullmatch(sp) or (rm and ":" in sp):
            if re.fullmatch(r"[^:]+:\d+:\d+.*", sp) or "." in sp.split(":")[0]:
                log.err(f"og ports: '{shown(sp)}' names an address; og publishes on 127.0.0.1 only, "
                        "so only this Mac reaches the sandbox")
            else:
                ports_usage(f"og ports: '{shown(sp)}' isn't a port" + (" (with --rm, the sandbox's port alone)" if rm else ""))
            return True
    return False


def listing(name: str, before: list[dict]) -> None:
    rows = [[_addr(x), str(x.get("sandbox_port", "?")), str(x.get("protocol", ""))] for x in before]
    boxes.columns(["ON THIS MAC", "SANDBOX PORT", "PROTOCOL"], rows, title=f"ports {name}",
                  foot=f"to publish one: {log.cmd(f'og ports {name} <port>')}")


def unpublish(name: str, specs: list[str], before: list[dict]) -> int:
    """Each mapping of each sandbox port unpublished, as sbx names it; at the
    first sbx refuses, what went before it is said as gone."""
    gone = []
    for sp in specs:
        # a protocol named picks only its mappings: udp is udp, udp4 and udp6; tcp4 is tcp4
        port, _, proto = sp.partition("/")
        mine = [x for x in before if str(x.get("sandbox_port")) == port and str(x.get("protocol", "")).startswith(proto)]
        if not mine:
            log.info(f"{name}'s port {sp} isn't published: nothing to remove")
            continue
        for x in mine:
            spec = f"{_addr(x)}:{x.get('sandbox_port')}/{x.get('protocol')}"   # [::1]:… for IPv6, as sbx reads it
            p = sbx.run("ports", name, "--unpublish", spec, wait=f"unpublishing {name}'s {sp}")
            if p.returncode != 0:
                log.err(f"og ports: sbx couldn't unpublish {name}'s {sp}:")
                sbx.said(p)
                if gone:   # what went before it is gone all the same: said, and on the record
                    log.note(f"already unpublished: {', '.join(gone)}", err=True)
                    log.record(f"unpublished {', '.join(gone)}")
                return 1
            gone.append(f"{name}:{x.get('sandbox_port')}/{x.get('protocol')} (was {_addr(x)})")
    if gone:
        log.ok(f"unpublished {', '.join(gone)}")
        log.record(f"unpublished {', '.join(gone)}")
    return 0


def publish(name: str, specs: list[str], before: list[dict]) -> int:
    """The specs published, then where each new mapping landed on this Mac."""
    p = sbx.run("ports", name, *[a for sp in specs for a in ("--publish", sp)], wait=f"publishing {name}'s {', '.join(specs)}")
    if p.returncode != 0:
        log.err(f"og ports: sbx couldn't publish {name}'s {', '.join(specs)}:")
        sbx.said(p)
        return 1
    after = _published(name) or []
    new = [x for x in after if x not in before]
    where = ", ".join(f"{name}:{x.get('sandbox_port')} is at {_addr(x)}" for x in new) or f"{name}: published {', '.join(specs)}"
    log.ok(where, "only this Mac reaches it")
    log.record(where)
    return 0


# ── og doctor ──

DOCTOR_HELP = dict(
    about="Check this Mac's sbx and og setup. Only reads: each fix is printed, never run.",
    forms=[("og doctor", "sbx's own checks, then og's: ssh-agent forwarding off, the baseline in place, "
                         "sbx's default rules off")],
    notes=["Exit 1 when something needs a look; sbx's own advice (an update) never fails it."],
    examples=["og doctor", "og -v doctor"],
)


def doctor_usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("doctor", "", problem=problem, err=err, **DOCTOR_HELP)


def doctor(args: list[str]) -> int:
    """Exit 1 when something stands in the way of a safe sandbox: an sbx check
    that failed (something is broken), or one of og's settings out of place or
    unreadable (nothing broken yet, but a sandbox reaches more than it should).
    sbx's own warnings (an update) are advice, never a failure."""
    if args:
        doctor_usage("og doctor takes no arguments")
        return 1
    log.section("sbx")
    bad = sbx_failed()
    log.section("og")
    bad = og_failed() or bad
    log.info("everything checks out" if not bad else "some of this needs a look (above)")
    return int(bad)


def sbx_failed() -> bool:
    """sbx's own checks (sbx diagnose), each said: True when one failed or its
    answer can't be read; a warning (an update) is advice, never a failure."""
    p = sbx.run("diagnose", "--json", wait="asking sbx to check itself")
    try:
        d = json.loads(p.stdout) if p.returncode in (0, 1) else None
    except ValueError:
        d = None
    if not isinstance(d, dict) or not isinstance(d.get("checks"), list):
        log.err("og doctor: sbx diagnose gave no answer og can read")
        return True
    bad = False
    for c in d["checks"]:
        if not isinstance(c, dict):
            continue
        what, st, msg = shown(str(c.get("name", "?"))), c.get("status"), shown(str(c.get("message", "")))
        if st == "pass":
            log.note(f"{what}: {msg}")
        elif st == "warn":
            fix = "brew upgrade --cask sbx" if what == "Binary version" and "Caskroom" in sbx_path(d) else ""
            hint = shown(str(c.get("hint", "")))
            log.warn(f"  {log.WARNING} {what}: {msg}" + ("; to update, run:" if fix else f"; {hint}" if hint else ""),
                     fix=log.cmd(fix) if fix else "")
        elif st == "fail":
            bad = True
            hint = shown(str(c.get("hint", "")))
            log.err(f"og doctor: {what} failed: {msg}" + (f"; {hint}" if hint else ""))
    return bad


def og_failed() -> bool:
    """og's settings, each said: True when one is out of place or unreadable —
    ssh-agent forwarding on, the baseline missing a rule, a broad default rule back."""
    bad = False
    agent = baseline.agent_forwarding_off()
    if agent:
        log.note("ssh-agent forwarding: off")
    elif agent is None:
        bad = True
        log.warn(f"  {log.WARNING} couldn't read sbx's ssh-agent setting; to set it off, run:", fix=log.cmd("og policy"))
    else:
        bad = True
        log.warn(f"  {log.WARNING} ssh-agent forwarding is on: a sandbox can use this Mac's keys; to turn it off, run:", fix=log.cmd("og policy"))
    missing = baseline.baseline_missing()
    if missing is None:
        bad = True
        log.warn(f"  {log.WARNING} couldn't read sbx's rules, so the baseline is unknown")
    elif missing:
        bad = True
        log.warn(f"  {log.WARNING} the baseline is missing {', '.join(missing)}; to put it back, run:", fix=log.cmd("og policy"))
    else:
        log.note("baseline: in place")
    back = baseline.default_rules_back()
    if back:
        bad = True
        log.warn(f"  {log.WARNING} sbx's broad default rules are back: {', '.join(back)}; to turn them off, run:", fix=log.cmd("og policy"))
    else:
        log.note("sbx's broad default rules: off")
    return bad


def sbx_path(d: dict) -> str:
    """Where sbx diagnose found its binary (its CLI binary check's detail)."""
    return next((str(c.get("detail", "")) for c in d.get("checks", []) if isinstance(c, dict) and c.get("name") == "CLI binary"), "")
