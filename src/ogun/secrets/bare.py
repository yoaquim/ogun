"""The bare og (docs/sandboxes.md): `og [<name>] [--org <owner> | --item
<vault item>] [--name <n>] [--sync] [--rm] [--appa] [--no-attach]` creates the sandbox for the current folder, or attaches to it.

It decides which GitHub token a sandbox gets: the folder's owner, --org, --item,
or the menu when the path names nobody; and an explicit --org or --item on an
existing sandbox replaces its token. So a change here deserves a secrets
review."""

import os
import re
import subprocess
import sys

from ogun.core import log, paths, sbx


def dir_name(d: str) -> str:
    """A directory's basename as a sandbox name: only the characters a name
    allows, and never a leading dot or dash. The name becomes the exchange's
    shared/<name>/ and boxes/<name>/, which og scan, tidy and the case-fold check
    walk with globs that skip dot-directories — a hidden one would never be
    scanned — and a hostname and a <name>.sbx ssh alias, which cannot start with
    a dot. So ~/.config-repo is `config-repo`."""
    n = re.sub(r"[^A-Za-z0-9._-]", "", os.path.basename(d))
    return re.sub(r"^[^A-Za-z0-9]*", "", n)


# ── the bare og ──

_VALUED = {"--org": "org", "--item": "item", "--name": "name"}
_SWITCHES = {"--rm": ("rm", True), "--sync": ("sync", True), "--no-attach": ("attach", False), "--appa": ("appa", True)}


def _help() -> None:
    from ogun import help
    help.page()


def up(argv: list[str]) -> int:
    from ogun.sandbox import init, session
    from ogun.secrets import github
    o = parse(argv)
    if isinstance(o, int):
        return o
    name = o["name"]
    d = os.path.realpath(os.getcwd())   # physical path: symlinks must not change the owner or the mounts
    explicit_name = bool(name)
    if not name:
        name = dir_name(d)
    if not name:
        log.err(f"og: '{log.shown(os.path.basename(d))}' has nothing a sandbox name can use; name one:", fix=log.cmd("og <name>"))
        return 1
    org, org_src = owner(d, o["org"], o["item"])
    token_item = o["item"]   # an item given (--item) or picked from the menu; carried into the create as-is
    listing = sbx.ls()
    exists = listing is not None and name in sbx.names(listing)
    # a new sandbox needs a repo to clone: settled before any token is asked for
    if not exists and not init.offer_init(d):
        return 1
    # a path that names nobody: at a terminal, offer the vault's tokens instead of
    # silently handing out the personal one (a new sandbox only; an existing one
    # keeps the owner it was created with)
    if not o["org"] and sys.stdin.isatty() and not paths.org_explicit(d) and not exists:
        token_item = github.pick_item()
        if not token_item:
            log.err("og: no token picked — nothing created; to skip the menu, run:", fix=log.cmd("og --org <owner>"))
            return 1
        org, org_src = github.item_owner(token_item) or "", f"picked: {token_item}"
    log.step(f"{name} · token owner: {org} ({org_src})")
    github.warnings()
    if exists:
        if not attach_existing(name, d, sbx.workspace(name, listing or ""), explicit_name, o, org):
            return 1
    elif not create_new(name, org, d, token_item, o["appa"]):
        return 1
    if not o["attach"]:
        log.ok(f"'{name}' is ready", f"attach with {log.cmd(f'og {name}')}")
        return 0
    # the upkeep every attach runs, the session, then --rm
    return session.session(name, exists, o["rm"])


def parse(argv: list[str]) -> dict | int:
    """The bare og's flags: what was asked for, or the exit code when they don't
    parse (said) or ask for help (printed)."""
    from ogun.secrets import github
    want = {"org": "", "item": "", "name": ""}
    o = {"rm": False, "sync": False, "attach": True, "appa": False}
    expect = ""
    for a in argv:
        if expect:
            if expect == "item":
                if github.item_owner(a) is None:
                    log.err(f"og: --item needs a vault item like github-pat-acme-home (github-pat-<owner>-<this Mac's token name>), "
                            f"got '{log.shown(a)}'")
                    return 1
            elif not a or a.startswith("-"):
                what = {"org": "a GitHub owner slug", "name": "a name"}[expect]
                log.err(f"og: --{expect} needs {what}, got '{log.shown(a)}'")
                return 1
            want[expect], expect = a, ""
            continue
        if a in _VALUED:
            expect = _VALUED[a]
        elif a in _SWITCHES:
            o[_SWITCHES[a][0]] = _SWITCHES[a][1]
        elif a in ("--help", "-h"):
            _help()
            return 0
        elif a.startswith("-"):
            log.err(f"og: unknown option {log.shown(a)}; every command and flag:", fix=log.cmd("og help"))
            return 1
        elif want["name"]:
            log.err(f"og: got two names ('{log.shown(want['name'])}', '{log.shown(a)}') — the token owner is taken "
                    "from the path, or --org <slug>")
            return 1
        else:
            want["name"] = a
    if expect:
        log.err({"org": "og: --org needs a GitHub owner slug (its token: og token <slug>)",
                 "item": f"og: --item needs an item name from vault '{github.vault()}'",
                 "name": "og: --name needs a name"}[expect])
        return 1
    if want["item"] and want["org"]:
        log.err("og: --item and --org together — the item already names its owner")
        return 1
    if want["item"]:
        want["org"] = github.item_owner(want["item"]) or ""
    return {**want, **o}


def owner(d: str, org_opt: str, item_opt: str) -> tuple[str, str]:
    """The token owner and where it came from: the item, --org, or the path."""
    from ogun.secrets import github
    if item_opt:
        return org_opt, f"--item {item_opt}"
    if org_opt:
        return org_opt, "--org"
    org = github.org_resolve(d)
    return org, github.org_source(d, org)


def attach_existing(name: str, d: str, ws: str, explicit_name: bool, o: dict, org: str) -> bool:
    """The checks and upkeep before attaching to a sandbox that exists, each refusal said."""
    from ogun.net import baseline
    from ogun.sandbox import base, create, facts, session
    from ogun.secrets import github, grants
    # attach works from any directory, but a DEFAULT name (the folder's) must belong
    # to THIS folder: ~/Projects/acme/foo and ~/Projects/personal/foo both default to
    # "foo", and attaching to the wrong one puts this repo's work under the other owner's token
    if not explicit_name:
        wr = os.path.realpath(ws) if ws and os.path.isdir(ws) else ws
        if wr and wr != d:
            log.err(f"og: sandbox '{name}' belongs to {wr}, not {d}; give this one its own name:",
                    fix=log.cmd(f"og --name {org}-{name}"))
            return False
    # OpenAPPA is chosen at create; asking for it on a sandbox made without it
    # is refused rather than ignored (it would read as protection it doesn't have)
    if o["appa"] and not facts.has_appa(name):
        log.err(f"og: '{name}' was created without OpenAPPA, which is chosen at create; remove it, then make it again:",
                fix=f"{log.cmd(f'og rm {name}')}, then {log.cmd('og --appa')}")
        return False
    log.step(f"'{name}' exists — attaching")
    if o["org"]:
        # an explicit --org / --item on an existing sandbox REPLACES its token (that is what
        # the flag says it does); silently keeping the old one would leave the old owner's access
        if not github.set_token(name, org, o["item"]):
            return False
    elif not github.token_refresh(name, o["sync"], ws):
        return False
    # attach may run from anywhere: its own workspace, not this folder
    if o["sync"] and not (create.skills() and base.setup(name) and session.https_remotes(name, ws)):
        return False
    # grants its create never applied (it stopped early), or declared since
    grants.catch_up(name, ws)
    # an sbx upgrade since the last create may have put a default rule back; one that
    # can't be removed stops the attach, like the ssh-agent guard (fail closed)
    if not baseline.default_rules_off("an sbx upgrade restored it"):
        log.err("og: not attaching while one of sbx's broad default rules is on — remove it by hand "
                "(the line above), then attach again")
        return False
    return True


def create_new(name: str, org: str, d: str, token_item: str, appa_on: bool) -> bool:
    from ogun.sandbox import create
    if subprocess.run(["git", "-C", d, "rev-parse", "--is-inside-work-tree"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        log.err(f"og: no sandbox named '{name}' and {d} is not a git repo to create one from; the sandboxes there are:",
                fix=log.cmd("og ls"))
        return False
    return create.create(name, org, d, "session", token_item, appa_on)
