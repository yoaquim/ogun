"""`og tidy`: what removed sandboxes left behind, folders in the exchange (--rm: removed)
and stored secrets."""

import os
import re
from pathlib import Path

from ogun.core import boxes, log, naming, sbx
from ogun.exchange import folders, screen

TIDY_HELP = dict(
    about="Find what removed sandboxes left behind: folders in the exchange, and stored secrets.",
    forms=[
        ("og tidy", "list them, and what's in each folder"),
        ("og tidy --rm", "remove the folders (one with files in out/ stays); secrets are only listed"),
    ],
    notes=["shared/<name> and the quarantine always stay. A stored secret is yours to remove: "
           "each comes with the command that does it."],
    examples=["og tidy", "og tidy --rm"],
)


def tidy_usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("tidy", "[--rm]", problem=problem, err=err, **TIDY_HELP)


def _orphans(live: set[str]) -> list[Path]:
    """Folders in boxes/ whose sandbox no longer exists."""
    parent = folders.exchange() / "boxes"
    if not parent.is_dir():
        return []
    return [d for d in sorted(parent.iterdir())
            if d.is_dir() and not d.name.startswith(".") and not naming.reserved(d.name) and d.name not in live]


def _secrets(live: set[str]) -> list[tuple[str, str]] | None:
    """Each secret whose sandbox is gone, as a warning and the command that
    removes it: reported, never deleted, a stored credential is yours to remove.
    Both kinds: service secrets and the custom section og pass makes. None when
    sbx couldn't list them."""
    p = sbx.run("secret", "ls")
    if p.returncode != 0:
        return None
    found, custom = [], False
    for line in (p.stdout or "").splitlines():
        f = line.split()
        if line.startswith("CUSTOM SECRETS"):
            custom = True
            continue
        if not f:
            continue
        scope = f[0]
        if scope in ("SCOPE", "(global)") or scope in live:
            continue
        who = screen.shown(scope)
        if not custom and len(f) >= 3 and f[1] == "service":
            found.append((f"{who}'s {screen.shown(f[2])} secret is still stored; {who} is gone — to remove it:",
                          log.cmd(f"sbx secret rm {screen.shown(f[2])} --sandbox {who}")))
        elif custom:
            # a custom row's other columns can hold spaces; its placeholder is found by shape
            m = re.search(r"(sbx-cs-[A-Za-z0-9]+)", line)
            found.append((f"{who}'s custom secret is still stored; {who} is gone — to remove it:",
                          log.cmd(f"sbx secret rm --sandbox {who} --placeholder {m.group(1)}")) if m
                         else (f"{who}'s custom secret is still stored; {who} is gone — its placeholder is in:",
                               log.cmd("sbx secret ls")))
    return found


def tidy(args: list[str]) -> int:
    """Folders whose sandbox is gone: listed with a look at what's in each, or
    removed with --rm (one with files in out/ stays); the secrets left for one,
    listed. shared/<name>/ is knowledge and outlives its sandbox, .quarantine/ is
    evidence: neither is touched."""
    if args not in ([], ["--rm"]):
        tidy_usage("og tidy takes only --rm")
        return 1
    # the live list is all that stands between --rm and every folder: a list sbx
    # didn't give must stop it, or every live sandbox's folder would look left behind
    listing = sbx.ls()
    if listing is None:
        log.err("og tidy: sbx ls failed — og can't tell which folders still have a sandbox, so nothing was touched")
        return 1
    live = {line.split()[0] for line in listing.splitlines()[1:] if line.split()}
    found, rc = False, 0
    for d in _orphans(live):
        found = True
        name = screen.shown(d.name)
        if args:
            if not naming.name_chars(d.name):   # box_rm builds no path from such a name
                log.warn(f"  {log.WARNING} '{name}' can't be a sandbox name, so og leaves its folder alone: {screen.shown(log.path(d))}")
                continue
            # og rm's own removal: files waiting in out/ are never deleted unseen,
            # and og take still reaches a gone sandbox's folder
            done = folders.box_rm(d.name, d, say=False)
            if done == "removed":
                log.ok(f"removed {name}'s folder", f"shared/{name} kept")
                log.record(f"removed {name}'s folder")
            rc |= done == "failed"
        else:
            log.section(f"{name}: the sandbox is gone, its folder isn't")
            files = []
            for top, _, names in os.walk(d):
                files += [str(Path(top, x).relative_to(d)) for x in names if x != ".DS_Store"]
            files.sort()
            for x in files[:5]:
                log.note(screen.shown(x), clock="")
            if len(files) > 5:
                log.note(f"and {len(files) - 5} more", clock="")
            if not files:
                log.note("empty", clock="")
            elif folders.has_files(d / "out"):
                log.note(f"files wait in its out/: {log.cmd(f'og take {name} --all')}", clock="")
    if found and not args:
        log.info("", clock="")
        log.info(f"{log.cmd('og tidy --rm')} removes these folders; one with files waiting in out/ is kept until they're taken.", clock="")
    secrets = _secrets(live)
    if secrets is None:
        log.warn(f"  {log.WARNING} couldn't list secrets (sbx secret ls failed) — leftover secrets not checked")
        if not found:
            log.info("no folder is left by a removed sandbox")
        return 1
    for msg, fix in secrets:
        found = True
        log.warn(f"  {log.WARNING} {msg}", fix=fix)
    if not found:
        log.info("nothing to tidy: every folder in the exchange belongs to a sandbox that's still here, and no secret is left for one that's gone")
    return int(rc)
