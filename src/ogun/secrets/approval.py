"""Which secret grants a sandbox gets (registry.json), and their approval: once per Mac,
at a real terminal, for that exact grant read from that vault (docs/secrets.md#secret-grants)."""

import os
import re
import sys
from pathlib import Path

from ogun.core import boxes, config, log, paths, settings
from ogun.secrets import rules


def grants_vault() -> str:
    return settings.vault()


def approved_file() -> Path:
    return paths.state_dir() / "approved-secrets"


def grants(d: str, quiet: bool = False) -> list[str]:
    """The grants a sandbox of this directory gets, a line each. The rules'
    refusals and skips go to stderr, or nowhere when quiet."""
    return rules.resolve(paths.registry_file(), os.path.basename(d.rstrip("/")), paths.org_from_path(d),
                         paths.placed(d), config.label(), (lambda _: None) if quiet else rules.stderr,
                         paths.shown_repo(os.path.basename(d.rstrip("/"))))


def fields(g: str, n: int) -> list[str]:
    """A grant line's n fields, the last taking the rest of the line."""
    f = g.split("\t", n - 1)
    return f + [""] * (n - len(f))


def _answer(f: Path, g: str, vault: str, how: str) -> bool:
    """One answer, kept (0600)."""
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(os.open(f, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as out:
            out.write(f"{g}\t{vault}" + (f"\t{how}" if how else "") + "\n")
        os.chmod(f, 0o600)
    except OSError:
        return False
    return True


def _confirm() -> int:
    """0 yes, 1 no, 2 no terminal to ask at."""
    if not sys.stdin.isatty():
        return 2
    print("    grant it to this sandbox and every later one it applies to? [y/N] ", end="", file=sys.stderr, flush=True)
    a = sys.stdin.readline().strip(" \t\n")
    return 0 if re.fullmatch(r"[Yy]([Ee][Ss])?", a) else 1


def _approvals(f: Path) -> set[str]:
    try:
        return set(f.read_text().splitlines()) if f.is_file() else set()
    except OSError:
        return set()


def approved(d: str) -> list[str]:
    """The grants for this directory that this Mac has approved. A grant seen for
    the first time (or changed: another item, field or host is another grant) is
    shown in full and asked about once; the answer, yes or no, is remembered in
    approved_file() (0600, outside every repo, so an edit to the registry alone
    never hands a sandbox a value). With no terminal, an unapproved grant is
    skipped and named."""
    f, vault, out = approved_file(), grants_vault(), []
    for g in grants(d):
        # the approval is for this grant read from this vault: the same item name elsewhere is another value
        if f"{g}\t{vault}" in _approvals(f):
            out.append(g)
            continue
        scope, env, hosts, item, field = fields(g, 5)
        # a "no" stands too: asking at every attach would train a reflexive yes
        if f"{g}\t{vault}\tdeclined" in _approvals(f):
            log.note(f"{env} ({scope}): declined earlier — not given (undo: delete its line in {log.path(f)})", err=True)
            continue
        who = (f"EVERY SANDBOX on this Mac (top-level grant, profile {scope.removeprefix('*@')})" if scope.startswith("*@")
               else f"sandboxes of repo '{scope}'")
        boxes.callout("SECRET GRANT, NOT YET APPROVED ON THIS MAC",
                    [f"{who} get {env}, swapped in on {hosts.replace(',', ', ')}", f"source: op://{vault}/{item}/{field}"], err=True)
        rc = _confirm()
        if rc == 0:
            if not _answer(f, g, vault, ""):
                log.warn(f"  {log.WARNING} could not record the approval — it will be asked again", err=True)
            out.append(g)
        elif rc == 1:
            if not _answer(f, g, vault, "declined"):
                log.warn(f"  {log.WARNING} could not record the decline — it will be asked again", err=True)
            log.warn(f"  {log.WARNING} {env}: declined — not given, and not asked again "
                     f"(undo: delete its line in {log.path(f)})", err=True)
        else:
            log.warn(f"  {log.WARNING} {env}: not approved on this Mac, and there is no terminal to ask at — skipped "
                     "(create once at a terminal to approve it)", err=True)
    return out
