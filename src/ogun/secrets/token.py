"""`og token`: a sandbox's GitHub token minted or rotated. GitHub's form opens
pre-filled; a person generates the token and saves it over the 1Password item's
credential, and og records when it expires once the item holds a NEW one. The
token itself is never read into og's output."""

import datetime
import re
import shlex
import shutil
import subprocess
import sys

from ogun.core import boxes, log, paths, settings
from ogun.secrets import github

USAGE = "[<owner>] [<days>]"
HELP = dict(
    about="Mint or rotate the GitHub token for an owner's sandboxes: GitHub's form opens pre-filled, "
          "you save the token in 1Password, og records when it expires.",
    forms=[
        ("og token", "the personal token, for 60 days"),
        ("og token <owner>", "an owner's: its folder's name in a project folder, e.g. acme"),
        ("og token <owner> <days>", "another lifetime: 1 to 366 days, GitHub's maximum"),
    ],
    notes=["The token goes in 1Password item github-pat-<owner>-<token_name, else the og profile> (the vault setting). "
           "Sandboxes made after it get it; an existing one gets it at og <name> --sync. More: docs/secrets.md"],
    examples=["og token", "og token acme", "og token acme 90"],
)

MAX_DAYS = 366   # GitHub's form takes 1..366 (expires_in); an org policy may cap it lower, in the form
DEFAULT_DAYS = 60
OWNER_RE = re.compile(r"[a-z0-9][a-z0-9-]*")   # the lowercase folder names vault_items() lists
# github_owners: "<folder>=<github owner> …", for a folder whose GitHub owner has another name
PAIR_RE = re.compile(r"([a-z0-9][a-z0-9-]*)=([A-Za-z0-9][A-Za-z0-9-]*)")
FORM = "https://github.com/settings/personal-access-tokens/new"
PERMISSIONS = "contents=write&pull_requests=write&actions=read&statuses=read"
ASKS = 3


def _sh(p) -> str:
    """A path for a command to copy: ~/… when the shell needs no quotes for it."""
    shown = log.path(p)
    return shown if re.fullmatch(r"[\w~/.+-]+", shown) else shlex.quote(str(p))


def usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("token", USAGE, problem=problem, err=err, **HELP)


def parse(args: list[str]) -> tuple[str, int] | None:
    """The owner and the lifetime in days; None, said, when either isn't one."""
    if len(args) > 2:
        usage("og token takes an owner and a lifetime, nothing more")
        return None
    if len(args) == 1 and args[0].isdigit():
        log.err(f"og token: '{args[0]}' is a lifetime, not an owner — og token <owner> [<days>], e.g. og token personal {args[0]}")
        return None
    owner, days = (args + ["personal", str(DEFAULT_DAYS)][len(args):])[:2]
    if not (days.isascii() and days.isdigit() and 1 <= int(days) <= MAX_DAYS):
        log.err(f"og token: days must be a whole number from 1 to {MAX_DAYS} (GitHub's maximum for fine-grained tokens), "
                f"got '{log.shown(days)}' — usage: og token [<owner>] [<days>] (default {DEFAULT_DAYS})")
        return None
    if not OWNER_RE.fullmatch(owner):
        log.err(f"og token: '{log.shown(owner)}' is not an owner key — its folder's name in a project folder, lowercase "
                f"(a-z, 0-9, -), e.g. og token {log.shown(owner.lower())}")
        return None
    return owner, int(days)


def github_owners() -> dict[str, str]:
    """github_owners as folder → GitHub owner. One pair that isn't one stops og: a
    form opened for the wrong account would mint a token for it."""
    pairs = {}
    for word in settings.get("github_owners").split():
        m = PAIR_RE.fullmatch(word)
        if not m:
            raise settings.Unreadable(f"github_owners: '{log.shown(word)}' isn't <folder>=<github owner> "
                                      "(the folder lowercase a-z, 0-9, -; the owner a GitHub name)")
        pairs[m[1]] = m[2]
    return pairs


def github_owner(owner: str) -> str:
    """The GitHub account a folder's token is for: github_owners' for it, else the
    folder's own name; personal's, unnamed, is "" and left to GitHub: your own account."""
    return github_owners().get(owner, "" if owner == "personal" else owner)


def form(item: str, owner: str, days: int, today: datetime.date) -> str:
    """GitHub's form for the token, pre-filled."""
    target = github_owner(owner)
    return (f"{FORM}?name={item}-{today.isoformat()}&description=sbx%20proxy%20token%20(docs/secrets.md)"
            + (f"&target_name={target}" if target else "") + f"&expires_in={days}&{PERMISSIONS}")


def credential(vault: str, item: str) -> str:
    """What the item's credential holds now, "" when it can't be read; compared,
    never shown."""
    p = subprocess.run(["op", "read", "-n", f"op://{vault}/{item}/credential"], capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else ""


def ask(prompt: str) -> str | None:
    """A line typed at the prompt; None at the end of input."""
    sys.stderr.write(prompt)
    sys.stderr.flush()
    line = sys.stdin.readline()
    return line.strip() if line else None


def token(args: list[str]) -> int:
    got = parse(args)
    if got is None:
        return 1
    owner, days = got
    item, vault, today = github.item(owner), github.vault(), datetime.date.today()
    # the credential as it is now (none for a new item), to tell a saved token
    # from an Enter pressed without saving
    before = credential(vault, item)
    url = form(item, owner, days, today)
    if not (shutil.which("open") and subprocess.run(["open", url], capture_output=True).returncode == 0):
        log.info(f"open this in a browser: {url}")
    print(f"1. Review the pre-filled form (owner: {github_owner(owner) or 'your own account'}, expires in {days} days), "
          "Generate token.")
    print(f"2. Paste it over the 'credential' field of 1Password item '{item}' (vault '{vault}'; "
          "create the item under that exact name if it is new).")
    ask("3. Press Enter once saved… ")
    if not saved(vault, item, before):
        log.err(f"og token: nothing recorded — 1Password item '{item}' (vault '{vault}') holds no new token, or couldn't be read.")
        log.note("The token you generated is live on GitHub: don't mint another. Save it to that item, then record its expiry:",
                 err=True)
        f = github.expiry_file(owner)
        log.note(log.cmd(f"mkdir -p {_sh(f.parent)} && date -v+{days}d +%Y-%m-%d > {_sh(f)}"), err=True)
        return 1
    f = github.expiry_file(owner)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text((today + datetime.timedelta(days=days)).isoformat() + "\n")
    log.ok(f"stored in {item}, expiring {f.read_text().strip()}", f"new sandboxes get it via: cd {log.path(paths.projects())}/{owner}/<repo> && og "
           f"(or anywhere: og --org {owner})")
    log.record(f"minted {item}, expiring {f.read_text().strip()}")
    log.note(f"existing {owner} sandboxes keep the OLD token until you sync each (it reads 1Password again): og <name> --sync")
    print("4. Delete the previous token on GitHub.")
    return 0


def saved(vault: str, item: str, before: str) -> bool:
    """The item holds a new token. By now one is live on GitHub, so a miss asks
    again here rather than sending anyone to mint a second; the read also misses
    when it was saved but 1Password is locked or its unlock declined."""
    for n in range(1, ASKS + 1):
        after = credential(vault, item)
        if after and after != before:
            return True
        if n == ASKS:
            return False
        ans = ask(f"   No new token in '{item}' yet — save it there and press Enter (or type skip): ")
        if ans is None or ans == "skip":
            return False
    return False
