"""A grant inside the sandbox: the placeholders sbx holds for it, exported into the
sandbox's environment or cleared from it, and og pass run quietly to set one."""

import contextlib
import os
import re
import sys

from ogun.core import log, sbx
from ogun.secrets import secret

PH = re.compile(r"sbx-cs-[A-Za-z0-9]+")


def targets_end(f: list[str]) -> int:
    """The index of a row's last target: sbx lists them comma-space separated."""
    k = 1
    while k < len(f) - 1 and f[k].endswith(","):
        k += 1
    return k


def placeholders(sb: str, env: str, hosts: str, src: str, listing: str) -> list[str]:
    """From `sbx secret ls`, the placeholder of each of this sandbox's rows for
    that variable, from exactly that op:// source, to exactly those hosts
    (comma-joined). sbx prints `SCOPE TARGETS ENV PLACEHOLDER SECRET`: targets
    comma-space separated, the secret as `ref:op://… (on-demand)` (an item may
    hold spaces). Read by position and compared whole, so a longer item or
    variable, or another host set, is another row."""
    want = hosts.split(",") if hosts else []
    need, out = set(want), []
    for line in listing.splitlines():
        f = line.split()
        if not f or f[0] != sb:
            continue
        k = targets_end(f)
        if k + 4 > len(f) or f[k + 1] != env or not PH.fullmatch(f[k + 2]):
            continue
        got = {t[:-1] if t.endswith(",") else t for t in f[1:k + 1]}
        if len(got) != len(want) or not got <= need:
            continue
        s = " ".join(f[k + 3:]).removesuffix(" (on-demand)").removeprefix("ref:")
        if s == src:
            out.append(f[k + 2])
    return out


def global_placeholders(env: str, listing: str) -> list[str]:
    """From `sbx secret ls`, the placeholder of each global (every-sandbox) custom
    row naming that variable, whatever its hosts or source: sbx treats any two
    as the same variable twice."""
    out = []
    for line in listing.splitlines():
        f = line.split()
        if not f or f[0] != "(global)":
            continue
        k = targets_end(f)
        if k + 3 <= len(f) and f[k + 1] == env and PH.fullmatch(f[k + 2]):
            out.append(f[k + 2])
    return out


def export(sb: str, env: str, ph: str) -> bool:
    return sbx.run("exec", sb, "bash", "-lc", secret.env_script("export.sh"), "_", env, ph).returncode == 0


def unexport(sb: str, env: str, ph: str) -> None:
    if sbx.run("exec", sb, "bash", "-lc", secret.env_script("unexport.sh"), "_", env, ph).returncode != 0:
        log.warn(f"  {log.WARNING} could not clear {env} from {sb}'s env — inside it, delete the line: export {env}={ph} "
                 "(in /etc/sandbox-persistent.sh)", err=True)


def quiet_pass(argv: list[str]) -> int:
    """og pass, its talk on stderr (stdout is the grants applied) and nothing to read from."""
    with open(os.devnull) as null, contextlib.redirect_stdout(sys.stderr):
        stdin, sys.stdin = sys.stdin, null
        try:
            return secret.pass_(argv)
        finally:
            sys.stdin = stdin


def full(listing: str, sb: str) -> bool:
    """Whether `sbx secret ls --sandbox` says what is gone: the custom secrets'
    header in the layout read here, with every row of this sandbox under it in
    that layout; or only the service section (`<sandbox> service github …`, its
    own header): no custom secret at all. Anything else (no header, another
    layout, a row it can't read) only says what it shows. og pass --rm reads it
    the same way (stored.placeholders)."""
    under = services = bad = False
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
        if not under and (len(f) < 2 or f[1] != "service"):
            bad = True
        if under:
            k = targets_end(f)
            if k + 4 > len(f) or not PH.fullmatch(f[k + 2]):
                bad = True
    return (under or services) and not bad
