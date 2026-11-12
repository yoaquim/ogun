"""Each sandbox's own GitHub token (docs/secrets.md): which owner it's for, which
1Password item fills it, and when attach sets it again. A security gate:
a change here deserves a secrets review."""

import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from ogun.core import log, paths, sbx, settings


def vault() -> str:
    return settings.vault()


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


def _plain(v: str, src: str = "") -> str:
    if v and not _TOKEN_RE.fullmatch(v):
        raise settings.Unreadable(f"{src or 'token_name'} '{v}' isn't a plain word (a-z, 0-9, -): it ends 1Password "
                                  "item names" + (" (set token_name in that profile)" if src else ""))
    return v


def token_name() -> str:
    """The ending of this Mac's own items (github-pat-<owner>-<it>): token_name,
    else the profile's name; "" with neither."""
    return _plain(settings.get("token_name") or settings.profile())


def endings() -> list[str]:
    """Every ending an item of this vault may have: this Mac's, then each
    profile's as that profile reads it (its own token_name, else the shared
    one, else its name), once each. Two where one ends the other (home-work,
    work) stop og: github-pat-foo-home-work would name two owners."""
    common = settings.shared().get("token_name", "")
    # its own setting, even an empty one, wins over the shared one, as the merge in settings does
    out = [token_name()] + [_plain(p.get("token_name", common) or name, f"profile '{name}' (its token name)")
                            for name, p in settings.profiles().items()]
    out = list(dict.fromkeys(e for e in out if e))
    for a in out:
        for b in out:
            if a.endswith("-" + b):
                raise settings.Unreadable(f"token item endings {a} and {b} overlap: github-pat-<owner>-{a} could be "
                                          f"<owner>-{a[:-len(b) - 1]}'s {b} token; give one profile another token_name")
    return out


def token_suffix() -> str:
    """The ending every item this Mac uses must have; "" for any."""
    return settings.get("token_suffix")


def item(owner: str) -> str:
    """The item name for this Mac: og token mints into it, og reads it."""
    t = token_name()
    if not t:
        raise settings.Unreadable("og can't name this Mac's token items: choose a profile (OG_PROFILE, or "
                                  "~/.config/ogun/profile) or set token_name")
    return f"github-pat-{owner}-{t}"


def items(owner: str) -> list[str]:
    """Every item that may hold this owner's token on this Mac, best first: its
    own, then the other profiles' endings (an owner may have a token for one Mac only),
    each ending in token_suffix when that's set (unset: any)."""
    if not owner:
        return []
    own = item(owner)
    cands = [own] + [f"github-pat-{owner}-{e}" for e in endings() if e != token_name()]
    return [c for c in cands if c.endswith(token_suffix())]


def item_valid_for(owner: str, it: str) -> bool:
    """One this Mac may hand the owner's sandboxes (its own name, or a fallback
    it allows): what attach accepts as provenance, so a fallback is not "stale"
    forever."""
    return it in items(owner)


_GH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,60}")


def org_resolve(d: str) -> str:
    """The owner slug for a folder: the path's, unless
    the placed repo's registry entry, under that same owner, names another
    GitHub account (`github`: acme/shop → acme-labs). The override
    keys on the basename, and every subfolder of every checkout has one: only
    the placed repo gets it."""
    org = paths.org_from_path(d)
    entry = paths.registry_entry(os.path.basename(d.rstrip("/")))
    gh = entry.get("github") if isinstance(entry, dict) else None
    if gh and isinstance(gh, str) and _GH_RE.fullmatch(gh) and not paths.refusal(d, entry):
        return gh
    return org


def org_source(d: str, org: str) -> str:
    """Where a resolved owner came from, for the line you check at create:
    the override first, since a placed repo may declare one too, then the placing,
    then the fallback guess."""
    if org != paths.org_from_path(d):
        return "registry github override"
    if paths.path_owner(d):
        return "registry path"
    # the same question that gave the owner: did a project folder name it
    if paths.org_explicit(d):
        return "from path"
    folders = [f for f, _ in paths.roots()]
    r = paths.real(d)
    inside = any(r.startswith(paths.real(f) + os.sep) for f in folders)
    return f"default: {'no owner from' if inside else 'outside'} {', '.join(folders)}"


def _ends() -> str:
    return "|".join(map(re.escape, endings()))


def item_owner(it: str) -> str | None:
    """The owner an item is for: exactly ONE trailing ending (a profile's token
    name) comes off, so github-pat-foo-desk-home is owner foo-desk. Every item
    names its owner, personal too, except a bare github-pat-home, which names none."""
    m = re.fullmatch(rf"github-pat-(.+)-(?:{_ends()})", it) if endings() else None
    return m.group(1) if m else None


def vault_items() -> list[str]:
    """The vault's github-pat-* items this Mac may use, sorted: every one, or
    only those ending in token_suffix when that's set. 1Password locked, not signed
    in, or no such vault: none (op printed nothing). One unlock."""
    try:
        p = subprocess.run(["op", "item", "list", "--vault", vault(), "--format", "json"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        got = json.loads(p.stdout)
    except (OSError, ValueError):
        got = []
    # owner = a ~/Projects folder (or personal), then one of the vault's endings
    valid = re.compile(rf"github-pat-[a-z0-9][a-z0-9-]*-(?:{_ends()})") if endings() else None
    names = sorted(str(i.get("title", "")) for i in got if isinstance(i, dict) and valid and valid.fullmatch(str(i.get("title", ""))))
    return [n for n in names if n.endswith(token_suffix())]


def pick_item() -> str:
    """A numbered menu of the vault's tokens this Mac may use, for a folder whose
    path names no owner; the chosen ITEM (the exact one shown, so picking another
    profile's token installs that token). Enter: this Mac's personal item. A typo or an
    out-of-range number asks again (three tries); end of input, or three misses,
    is "" — the caller must then stop rather than fall back to personal by
    accident. Reads the terminal ($OG_MENU_IN for tests), one open stream, so a
    retry reads the NEXT line."""
    its = vault_items()
    if not its:
        # say why there is nothing to pick, or the caller's "no token picked" is all there is
        if not endings():
            log.err("og: no profile and no token_name, so og can't tell which items are this Mac's token items; "
                    "choose a profile (OG_PROFILE, or ~/.config/ogun/profile) or set token_name")
        else:
            log.err(f"og: the vault '{vault()}' holds no github-pat-* item this Mac may use, or 1Password is locked "
                    "or not signed in; mint one with og token <owner>")
        return ""
    log.step(f"no owner in the path — which GitHub token? (vault '{vault()}')", err=True)
    for i, it in enumerate(its, 1):
        print(f"    {i}) {it}  (owner: {item_owner(it)})", file=sys.stderr)
    try:
        f = open(os.environ.get("OG_MENU_IN") or "/dev/tty")  # noqa: SIM115 closed by the with below; only the open may fail
    except OSError:
        return ""
    with f:
        for _ in range(3):
            print("    number, or Enter for personal: ", end="", file=sys.stderr, flush=True)
            line = f.readline()
            if not line:
                break
            ans = line.strip(" \t\n")
            if not ans:
                return item("personal")
            if re.fullmatch(r"[0-9]+", ans) and 1 <= int(ans) <= len(its):
                return its[int(ans) - 1]
            print(f"    not a number from 1 to {len(its)}: '{log.shown(ans)}'", file=sys.stderr)
    return ""


def attach_owner(ws: str, have: str) -> str:
    """The owner an existing sandbox keeps: its workspace's, unless that path
    names nobody ("personal" only as a guess), when the one on record stands."""
    org = org_resolve(ws)
    if have and not paths.org_explicit(ws):
        org = have
    return org


def records_dir() -> Path:
    """Where og keeps each sandbox's token record and each owner's token expiry."""
    return paths.state_dir() / "tokens"


def _record(name: str, kind: str) -> Path:
    return records_dir() / f"{name}.{kind}"


def _recorded(name: str, kind: str) -> str:
    try:
        return _record(name, kind).read_text().strip()
    except OSError:
        return ""


def token_owner(name: str) -> str:
    return _recorded(name, "owner")


def token_item(name: str) -> str:
    return _recorded(name, "item")


def has_token(name: str) -> bool:
    """sbx lists a github service secret for the sandbox. A listing that failed
    reads as none, so attach sets it again: one more 1Password read, never a
    sandbox left with a token nobody checked."""
    p = sbx.run("secret", "ls", "--sandbox", name, wait=f"reading {name}'s secrets")
    if p.returncode:
        return False
    return any(len(f) > 2 and f[1] == "service" and f[2] == "github" for f in (line.split() for line in p.stdout.splitlines()))


def set_token(name: str, org: str, it: str = "") -> bool:
    """The owner's token from 1Password (unlocked from this terminal) into the
    sandbox's own github secret, and a record of which owner and item filled it:
    sbx can't say, and the item depends on this Mac's profile. An explicit item (from the
    menu) is the only candidate."""
    cands = [it] if it else items(org)
    if not cands:
        log.err("og: no org given")
        return False
    # an empty read (cancelled prompt, no terminal, no such item) must fail HERE
    # with its cause: passed on, sbx prompts "Enter secret:" and reads nothing
    log.step(f"{org} GitHub token, scoped to '{name}' (1Password vault '{vault()}')")
    tok, used = "", ""
    for c in cands:
        try:
            p = subprocess.run(["op", "read", "-n", f"op://{vault()}/{c}/credential"], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, check=False)
        except FileNotFoundError:
            break
        tok = p.stdout.decode("utf-8", "replace").rstrip("\n") if p.returncode == 0 else ""
        if tok:
            used = c
            break
    if not tok:
        log.err(f"og: 1Password returned no token for '{cands[0]}' (the unlock cancelled, no terminal for the prompt, "
                f"or no such item in vault '{vault()}'); to create it, run:", fix=log.cmd(f"og token {org}"))
        return False
    # -f: replace an old token after rotation
    p = sbx.run("secret", "set", "-f", "github", "--sandbox", name, "-t", tok, hide=tok, wait=f"giving {name} its token")
    if p.returncode:
        log.err(f"og: sbx couldn't set {name}'s GitHub token")
        sbx.said(p, hide=tok)
        return False
    # which owner this sandbox holds AND which item filled it: if the profile is
    # corrected later, the same owner resolves to a different item and the
    # token must be replaced (attach compares this record)
    _record(name, "owner").parent.mkdir(parents=True, exist_ok=True)
    _record(name, "owner").write_text(org + "\n")
    _record(name, "item").write_text(used + "\n")
    record_expiry(org, tok)
    return True


# ── when a token dies ──

def expiry_file(owner: str) -> Path:
    """Where the owner's token's expiry date is kept, for warnings(): og token
    writes it when it saves a new token, and record_expiry() whenever og reads one."""
    return records_dir() / f"github-{owner}.expires"


def record_expiry(owner: str, tok: str) -> None:
    """GitHub's own word on when the token dies (the
    GitHub-Authentication-Token-Expiration header every API call answers with),
    kept for warnings(). So a token saved without og token recording its date (a
    Ctrl-C after saving it, one made by hand on GitHub) still has the right one
    after its next create or --sync. The token goes to curl on stdin, never in
    its arguments. Best effort: no answer leaves the date as it was."""
    try:
        p = subprocess.run(["curl", "-sS", "--max-time", "10", "-o", "/dev/null", "-D", "-", "-H", "@-",
                            "https://api.github.com/"], input=f"Authorization: Bearer {tok}\n".encode(),
                           capture_output=True, check=False)
    except FileNotFoundError:
        return
    if p.returncode:
        return
    for line in p.stdout.decode("utf-8", "replace").splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "github-authentication-token-expiration":
            m = re.match(r"\s*(\d{4}-\d{2}-\d{2})\b", value)
            if m:
                try:
                    expiry_file(owner).parent.mkdir(parents=True, exist_ok=True)
                    expiry_file(owner).write_text(m.group(1) + "\n")
                except OSError:
                    pass
            return


def warnings() -> None:
    """Before a create or an attach: each token that expired, or dies within a
    week, with the command that makes a new one; and a global github secret,
    which sbx hands every sandbox ahead of its own token, so each sandbox's
    token is the only one."""
    today = datetime.date.today()
    found = {f.name: f for f in records_dir().glob("github-*.expires")}
    for _, f in sorted(found.items()):
        which = f.name[len("github-"):-len(".expires")]
        try:
            exp = f.read_text().strip()
            when = datetime.date.fromisoformat(exp)
        except (OSError, ValueError):
            continue
        if when < today:
            log.warn(f"  {log.WARNING} GitHub token '{which}' expired {exp}; to make a new one, run:", fix=log.cmd(f"og token {which}"))
        elif when < today + datetime.timedelta(days=7):
            log.warn(f"  {log.WARNING} GitHub token '{which}' expires {exp}; to make a new one, run:", fix=log.cmd(f"og token {which}"))
    p = sbx.run("secret", "ls", wait="reading sbx's secrets")
    if p.returncode == 0 and any(f[:3] == ["(global)", "service", "github"] for f in (line.split() for line in p.stdout.splitlines())):
        log.warn(f"  {log.WARNING} a global github secret exists: sbx hands it to every sandbox ahead of its own token. "
                 "Remove it:", fix=log.cmd("sbx secret rm github"))


def token_refresh(name: str, sync: bool, ws: str) -> bool:
    """On attach: the token set again when the sandbox has none, when the owner
    on record is unknown or differs, or when its item isn't one this Mac may use
    for the owner; with --sync, read fresh regardless. The owner comes from the
    SANDBOX's workspace, never from wherever og was run."""
    if not ws:
        log.err(f"og: '{name}': workspace unknown, so its token owner can't be confirmed; run it again with --org <owner>")
        return False
    have = token_owner(name)
    org = attach_owner(ws, have)
    done = False
    if not has_token(name):
        log.step(f"no token yet · owner from its workspace {ws}: {org}")
        if not set_token(name, org):
            return False
        done = True
    elif have != org:
        # a token with NO owner record could be ANY owner's. When the workspace
        # path doesn't name one either, "personal" is only a guess: replacing a
        # work token with the personal one would expose personal repos inside
        # a work sandbox, so a person must say
        if not have and not paths.org_explicit(ws):
            log.err(f"og: '{name}' has a GitHub token og holds no owner record for, and its workspace ({ws}) names no owner, "
                    "so the token could be any owner's. Attach once with --org <owner> to stamp it.")
            return False
        log.step(f"token owner on record: {have or 'unknown'}; from its workspace: {org}; replacing")
        if not set_token(name, org):
            return False
        done = True
    else:
        # same owner, but it resolves to a DIFFERENT item when the profile changed
        # since. With no item record its source is unknown, so it's set again
        # from this Mac's item rather than trusted
        want, held = item(org), token_item(name)
        if not held:
            log.step(f"token with no item on record; setting it again from this Mac's item '{want}' to record its source")
            if not set_token(name, org):
                return False
            done = True
        elif not item_valid_for(org, held):
            log.step(f"token came from item '{held}'; this Mac reads '{want}'; replacing")
            if not set_token(name, org):
                return False
            done = True
    if sync and not done:
        # the item it holds, while still one this Mac may use for the owner (one picked
        # from the menu stays that one): the token rotated in THAT item
        keep = token_item(name)
        if not item_valid_for(org, keep):
            keep = ""
        log.step(f"--sync: the {org} GitHub token, read fresh from 1Password" + (f" ({keep})" if keep else ""))
        if not set_token(name, org, keep):
            return False
    return True
