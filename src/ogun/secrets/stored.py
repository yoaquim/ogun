"""A sandbox's secrets as sbx holds them: listed, their placeholders read, one removed
(og pass --rm). Names and placeholders only: no value is ever read back."""

import json
import re
import shlex

from ogun.core import log, records, sbx
from ogun.core.log import shown
from ogun.sandbox import sandboxes
from ogun.secrets import secret


def sandbox_there(sb: str) -> bool:
    """The sandbox is there: said when it isn't, and when sbx couldn't list."""
    return sandboxes.find("pass", sb) is not None


def listing(sb: str) -> int:
    """og pass <name>: the secrets sbx holds for that sandbox, a line each: the
    variable, the hosts the proxy swaps it in on, where it came from (a
    1Password reference, or pasted: never any part of the value), its
    placeholder. Its GitHub token, og's own, and what --expose put in its
    environment (sbx never holds those) are said beneath."""
    if not sandbox_there(sb):
        return 1
    p = sbx.run("secret", "ls", "--sandbox", sb, "--json", wait=f"reading {sb}'s secrets")
    try:
        d = json.loads(p.stdout) if p.returncode == 0 else None
    except ValueError:
        d = None
    if not isinstance(d, dict) or not isinstance(d.get("custom_secrets", []), list):
        log.err(f"og pass: sbx couldn't list {sb}'s secrets")
        return 1
    rows = []
    for c in d.get("custom_secrets") or []:
        if not isinstance(c, dict) or c.get("scope") != sb:
            continue
        hosts = c.get("targets") if isinstance(c.get("targets"), list) else []
        src = str(c.get("source") or "")
        frm = f"1Password: {src.removeprefix('op://')}" if c.get("kind") == "ref" and src.startswith("op://") else "pasted"
        rows.append((shown(str(c.get("env", "?"))), shown(", ".join(map(str, hosts))) or "no host", shown(frm),
                     shown(str(c.get("placeholder", "")))))
    github = any(isinstance(x, dict) and x.get("type") == "service" and x.get("name") == "github" and x.get("scope") == sb
                 for x in d.get("secrets") or [])
    # a line each, not a table: a table's columns cut a variable's name and its 1Password path
    log.section(f"{sb}'s secrets")
    for env, hosts, frm, ph in sorted(rows):
        log.note(f"{env}: swapped in on {hosts} · from {frm}" + (f" · {ph}" if ph else ""), clock="")
    if not rows:
        log.note("none from og pass", clock="")
    log.note(f"GitHub: {'its own token, set by og' if github else 'no token yet: attaching sets one'}", clock="")
    log.info("not listed: values given with --expose, which sbx doesn't hold", clock="")
    if rows:
        log.info(f"to remove one: {log.cmd(f'og pass {sb} <ENV_VAR> --rm')}", clock="")
    return 0


_PH = re.compile(r"sbx-cs-[A-Za-z0-9]+")


def placeholders(listing: str, sb: str, env: str) -> list[str] | None:
    """The placeholders `sbx secret ls --sandbox <sb>` lists for env, from the
    sandbox's own rows under the custom secrets' header (SCOPE, TARGETS
    comma-continued, ENV, PLACEHOLDER, SECRET), read as sandboxenv.full and grants.revoke read
    them. A service section alone means nothing registered: []. None when what
    sbx lists can't be known: a row of this sandbox that doesn't read that way,
    a non-service row with no header og knows above it (sbx's layout moved),
    or neither header at all (an empty answer says nothing)."""
    out, under, services = [], False, False
    for line in listing.splitlines():
        f = line.split()
        if f == ["SCOPE", "TARGETS", "ENV", "PLACEHOLDER", "SECRET"]:
            under = True
            continue
        if f == ["SCOPE", "TYPE", "NAME", "SECRET"]:
            services = True
            continue
        if not f or f[0] != sb:
            continue
        if not under:
            if len(f) < 2 or f[1] != "service":
                return None
            continue
        k = 1
        while k < len(f) - 1 and f[k].endswith(","):
            k += 1
        if k + 2 >= len(f) or not _PH.fullmatch(f[k + 2]):
            return None
        if f[k + 1] == env:
            out.append(f[k + 2])
    return out if under or services else None


def remove(sb: str, env: str) -> int:
    """og pass <name> <ENV_VAR> --rm: what pass gave, removed. Each of the
    sandbox's sbx registrations for that variable removed, then every export of
    it from its persistent env (a placeholder's, or an exposed real value)."""
    if not sandbox_there(sb):
        return 1
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", env):
        log.err(f"og pass: '{env}' isn't an environment variable name: letters, digits and _, like OPENAI_API_KEY")
        return 1
    p = sbx.run("secret", "ls", "--sandbox", sb)
    phs = placeholders(p.stdout or "", sb, env) if p.returncode == 0 else None
    if phs is None:
        log.err(f"og pass: couldn't read {sb}'s secrets from sbx, so nothing was removed; to see them, run:",
                fix=log.cmd(f"sbx secret ls --sandbox {sb}"))
        return 1
    for ph in phs:
        # sbx asks y/N without -f, and og runs it with no terminal to answer from
        if sbx.run("secret", "rm", "--sandbox", sb, "--placeholder", ph, "-f").returncode != 0:
            log.err(f"og pass: sbx couldn't remove {env} from {sb}; remove it by hand:",
                    fix=log.cmd(f"sbx secret rm --sandbox {sb} --placeholder {ph}"))
            return 1
    d = sbx.run("exec", sb, "bash", "-lc", secret.env_script("drop.sh"), "_", env, wait=f"clearing {env} in {sb}")
    if d.returncode not in (0, 3):
        # drop.sh's own edit, by hand: every `export ENV=` line, as export.sh and expose.sh write them
        by_hand = shlex.join(["og", "sh", sb, "sudo", "sed", "-i", f"/^export {env}=/d", "/etc/sandbox-persistent.sh"])
        log.err((f"og pass: sbx dropped {env}, but og couldn't clear it from {sb}'s environment; to clear it, run:" if phs
                 else f"og pass: couldn't clear {env} from {sb}'s environment; to clear it, run:"), fix=log.cmd(by_hand))
        return 1
    if not phs and d.returncode == 3:
        log.info(f"{sb} has no {env}: nothing to remove")
        return 0
    if _granted(sb, env):
        log.note(f"{env} came from registry.json: attaching won't give it back to {sb}, but a new sandbox for that "
                 "repo gets it; its hosts stay allowed until it's removed from registry.json")
    said = ["sbx dropped it; the proxy may swap it in until sbx restarts"] if phs else []
    said += ["gone from its environment"] if d.returncode == 0 else []
    log.ok(f"removed {env} from {sb}", "; ".join(said))
    log.record(f"removed {env} from {sb}")
    return 0


def _granted(sb: str, env: str) -> bool:
    """Whether the sandbox's create record lists env among its secret grants."""
    try:
        rec = records.read_record(sb) or {}
        return any(isinstance(g, dict) and g.get("env") == env for g in rec.get("secrets") or [])
    except AttributeError:
        return False
