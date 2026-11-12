"""`og pass`: hand one secret to one sandbox (docs/secrets.md).

The safe pair is the default: the value comes from 1Password, and the sandbox
holds only a placeholder, which the proxy swaps for the real value on requests
to the hosts named (`sbx secret set-custom`; the value never touches the
sandbox's disk). set-custom's --env reaches only sandboxes created later, so the
placeholder, deliberately not a secret, is also exported into the running one.
GitHub hosts are refused: one GitHub identity per sandbox.

--expose is for a key used inside the sandbox (decryption, signing: nothing for
the proxy to swap in): the real value goes into its persistent env, over the
sandbox's stdin, never in argv, a file on this Mac or the transcript. Readable
inside it, which is the point and the price; it dies with the sandbox. GitHub
items, pasted GitHub tokens and the names gh and git read are refused exposed:
any would be a second GitHub identity.

--paste: the value from a hidden prompt (one line) or, piped, all of stdin
(multi-line keys: `pbpaste | og pass …`), held only in this process. For the
proxy it goes to set-custom as --value: argv, for the instant sbx runs, visible
only to processes running as you, never typed, so never in shell history.
The one deliberate exception to "never in argv": set-custom's other literal
input (--command) would need the value in a file for as long as the secret lives.

The scripts that run inside the sandbox are og's sandbox-scripts/env/*.sh, one copy each,
which the secret grants (grants.py) run too. A change here, there or in sbx.py
deserves a secrets review."""

import getpass
import os
import re
import shlex
import subprocess
import sys

from ogun.core import boxes, log, paths, sbx
from ogun.core.log import shown
from ogun.secrets import github, stored


def env_script(name: str) -> str:
    """A script that runs inside the sandbox (og's sandbox-scripts/env/), read when used."""
    return (paths.SCRIPTS / "env" / name).read_text()

PASS_USAGE = "<name> <ENV_VAR> <host>...|--expose [--item <name>|--paste] [--vault <v>] [--field <f>]  |  <name> <ENV_VAR> --rm  |  <name>"
PASS_HELP = dict(
    about="Hand one secret to one sandbox. By default the value comes from 1Password and stays out of the "
          "sandbox: it holds a placeholder, and the proxy swaps the real value in on requests to the hosts you name.",
    forms=[
        ("og pass <name>", "its secrets: each variable, the hosts it's swapped in on, where it came from, and its placeholder"),
        ("og pass <name> <ENV_VAR> <host>…", "ENV_VAR in that sandbox, swapped for the real value on requests to these hosts "
                                             "(list several, or comma-separate them)"),
        ("… --expose", "the real value in the sandbox's environment instead, readable inside it: only for keys used "
                       "inside the sandbox (decryption, signing). Takes no host"),
        ("… --item <name>", "the 1Password item; asked for when left out"),
        ("… --vault <v>, --field <f>", "where in 1Password: vault Sandbox (or the vault setting), field credential"),
        ("… -p, --paste", "paste the value at a hidden prompt (one line), or pipe it in for multi-line keys: pbpaste | og pass …"),
        ("og pass <name> <ENV_VAR> --rm", "remove it: out of sbx, and out of the sandbox's environment"),
    ],
    notes=["GitHub hosts, GitHub tokens and the names gh and git read (GH_TOKEN, GITHUB_TOKEN) are refused: a sandbox's "
           "one GitHub identity comes from og. The secret lasts as long as the sandbox. More: docs/secrets.md"],
    examples=["og pass cub API_TOKEN api.orders.example --item orders-api",
              "og pass cub API_TOKEN api.orders.example app.orders.example --paste",
              "og pass cub SIGNING_KEY --expose --item signing-key",
              "pbpaste | og pass cub SIGNING_KEY --expose --paste"],
)

# gh and git credential helpers read these before anything else: a real value
# there IS a second GitHub identity, whatever the item is called
_GITHUB_ENVS = {"GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"}
_GITHUB_TOKEN = (b"ghp_", b"gho_", b"ghu_", b"ghs_", b"ghr_", b"github_pat_")
_VALUED = ("--item", "--vault", "--field")


def usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("pass", PASS_USAGE, problem=problem, err=err, **PASS_HELP)


def _github_fix(sb: str) -> str:
    """The command that replaces a sandbox's one GitHub token: its owner as
    github.set_token recorded it, read fresh from 1Password."""
    owner = github.token_owner(sb)
    return log.cmd(f"og {sb} --org {owner if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', owner) else '<owner>'}")


_GITHUB_ONE = "a sandbox has one GitHub identity, the token og sets for it; to replace that token, run:"


def _github_host(h: str) -> bool:
    h = h.lower()   # DNS is case-insensitive: GITHUB.COM must hit the refusal too
    return h in ("github.com", "githubusercontent.com") or h.endswith((".github.com", ".githubusercontent.com"))


def _said(src: str) -> str:
    """Where the value came from, as the done line ends."""
    return "you pasted it" if src == "pasted" else f"from {src}"


def _output(p, hide: str = "") -> list[str]:
    """What sbx printed, both streams, a line each, to read the placeholder
    from: no control bytes, and a pasted value it echoed back not shown."""
    text = (p.stdout or "") + (p.stderr or "")
    return [shown(line) for line in sbx.redact(text, hide).splitlines()]


def pass_(argv: list[str]) -> int:
    if len(argv) == 1 and not argv[0].startswith("-"):
        return stored.listing(argv[0])
    if len(argv) < 2:
        usage("og pass needs a sandbox and an ENV_VAR")
        return 1
    sb, env, rest = argv[0], argv[1], argv[2:]
    if "--rm" in rest:
        if rest != ["--rm"]:
            usage("og pass: --rm takes only the sandbox and the ENV_VAR")
            return 1
        return stored.remove(sb, env)
    o = pass_flags(sb, env, rest)
    if isinstance(o, int) or refused(sb, env, o):
        return 1
    v = value_source(sb, env, o)
    if v is None:
        return 1
    value, src, item = v
    return _expose(sb, env, value, src) if o["expose"] else _proxy(sb, env, o["hosts"], value, src, item)


def pass_flags(sb: str, env: str, rest: list[str]) -> dict | int:
    """og pass's flags after the sandbox and variable: the hosts, the mode, the
    value's source; 1 when they don't parse (said)."""
    # same vault as every sandbox-bound credential (docs/secrets.md); --vault for exceptions
    opt = {"--item": "", "--vault": github.vault(), "--field": "credential"}
    hosts, expose, paste, op_opt, i = [], False, False, "", 0
    while i < len(rest):
        a = rest[i]
        if a == "--expose":
            expose = True
        elif a in ("-p", "--paste"):
            paste = True
        elif a in _VALUED:
            if i + 1 >= len(rest):
                usage(f"og pass: {a} needs a value")
                return 1
            opt[a] = rest[i + 1]
            op_opt = op_opt if a == "--item" else a
            i += 1
        elif a.startswith("-"):
            usage(f"og pass has no option {a}")
            return 1
        else:
            hosts += a.split(",")
        i += 1
    return {"hosts": hosts, "expose": expose, "paste": paste, "op_opt": op_opt, "item": opt["--item"],
            "vault": opt["--vault"], "field": opt["--field"]}


def refused(sb: str, env: str, o: dict) -> bool:
    """Every rule a pass must keep before any value is read, the broken one said."""
    hosts, expose, paste = o["hosts"], o["expose"], o["paste"]
    if not stored.sandbox_there(sb):
        return True
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", env):
        log.err(f"og pass: '{env}' isn't an environment variable name: letters, digits and _, like OPENAI_API_KEY")
        return True
    # a host unless exposed: a forgotten host must not quietly deliver the real
    # value, and an exposed value has no proxy to scope it to a host
    if expose and hosts:
        log.err("og pass: --expose takes no host: the real value goes into the sandbox, so no proxy swaps it in")
        return True
    if not expose and not hosts:
        log.err("og pass: name the host(s) the proxy swaps the value in on, or --expose to put the real value in the sandbox")
        return True
    if paste and o["item"]:
        log.err("og pass: --paste and --item are two sources for the value: use one")
        return True
    if paste and o["op_opt"]:
        log.err(f"og pass: {o['op_opt']} is for a 1Password item, so it means nothing with --paste")
        return True
    for h in hosts:
        # a GitHub address in any shape (a repo's, a URL) is GitHub first: its refusal says what to do
        if _github_host(re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", h).split("/")[0].split(":")[0]):
            log.err(f"og pass: GitHub is refused: {_GITHUB_ONE}", fix=_github_fix(sb))
            return True
        if not re.fullmatch(r"[A-Za-z0-9*][A-Za-z0-9.*-]{0,200}", h):
            log.err(f"og pass: '{shown(h)}' isn't a host name: name the host alone, like api.example.com, "
                    "not a web address or a path")
            return True
    if expose and env in _GITHUB_ENVS:
        log.err(f"og pass: {env} is never exposed: gh and git read it as a GitHub token, and {_GITHUB_ONE}", fix=_github_fix(sb))
        return True
    return False


def value_source(sb: str, env: str, o: dict) -> tuple[bytes | None, str, str] | None:
    """The value (pasted) or its 1Password reference, where it came from, and the
    item; None when there's none, or it's GitHub's and would be exposed (said)."""
    item, expose = o["item"], o["expose"]
    if o["paste"]:
        if sys.stdin.isatty():
            value = getpass.getpass(f"Paste the value for {env} (hidden), then Enter: ").encode()
        else:
            value = sys.stdin.buffer.read()       # piped: every byte, multi-line keys included
            value = value.removesuffix(b"\n")     # …but not the newline echo or pbpaste may add
        if not value:
            log.err("og pass: nothing was pasted")
            return None
        # a pasted GitHub token is a second identity however it's named
        if expose and value.startswith(_GITHUB_TOKEN):
            log.err(f"og pass: that's a GitHub token, never exposed: {_GITHUB_ONE}", fix=_github_fix(sb))
            return None
        return value, "pasted", item
    if not item:
        if sys.stdin.isatty():
            print(f"1Password item (vault {o['vault']}): ", end="", file=sys.stderr, flush=True)
        item = sys.stdin.readline().strip()
        if not item:
            log.err("og pass: a 1Password item is needed: --item, or --paste to paste the value")
            return None
    if expose and "github" in item.lower():
        log.err(f"og pass: GitHub items are never exposed: {_GITHUB_ONE}", fix=_github_fix(sb))
        return None
    return None, f"op://{o['vault']}/{item}/{o['field']}", item


def _expose(sb: str, env: str, value: bytes | None, src: str) -> int:
    """The real value into the sandbox's env, over its stdin: pasted, from here;
    from 1Password, op's output piped straight in, never held by og."""
    run = ("exec", "-i", sb, "bash", "-lc", env_script("expose.sh"), "_", env)
    if value is not None:
        ok = sbx.run(*run, input=value, wait=f"giving {sb} {env}").returncode == 0
    else:
        try:
            op = subprocess.Popen(["op", "read", "-n", src], stdout=subprocess.PIPE)
        except FileNotFoundError:
            log.err("og pass: 1Password's op isn't installed")
            return 1
        p = sbx.run(*run, stdin=op.stdout, wait=f"giving {sb} {env}")
        op.stdout.close()
        read_ok = op.wait() == 0
        if not read_ok:   # which side failed is known: say that one
            log.err(f"og pass: 1Password couldn't read {src} — unlock it, or check the item's name")
            return 1
        ok = p.returncode == 0
    if not ok:
        log.err(f"og pass: couldn't write {env} inside {sb}")
        return 1
    log.ok(f"gave {sb} {env}, the real value", f"readable inside it, gone with it; {_said(src)}")
    log.record(f"gave {sb} {env}, the real value; {_said(src)}")
    return 0


def _proxy(sb: str, env: str, hosts: list[str], value: bytes | None, src: str, item: str) -> int:
    hargs, v = [x for h in hosts for x in ("--host", h)], ""
    if value is not None:
        v = os.fsdecode(value)
        p = sbx.run("secret", "set-custom", "--sandbox", sb, *hargs, "--env", env, "--value", v, hide=v)
    else:
        p = sbx.run("secret", "set-custom", "--sandbox", sb, *hargs, "--env", env, "--ref", src)
    out = _output(p, v)
    # what set-custom printed can be shown: a pasted value in it is hidden (v),
    # and a --ref is read by sbx on demand, not while it's registered
    if p.returncode != 0:
        log.err("og pass: sbx couldn't register the secret:")
        sbx.said(p, v)
        return 1
    # sbx indents this line ("  Generated placeholder:  sbx-cs-…"); the first
    # placeholder anywhere in its answer only when it has none
    ph = next((m.group(1) for line in out if (m := re.match(r"\s*Generated placeholder:\s*(\S+)", line))), "")
    if not ph:
        m = re.search(r"sbx-cs-[A-Za-z0-9]+", "\n".join(out))
        ph = m.group(0) if m else ""
    if not ph:
        log.err("og pass: sbx's answer named no placeholder:")
        sbx.said(p, v)
        return 1
    # export into the RUNNING sandbox, replacing any earlier line for this
    # variable, so a re-pass (a rotated item, new hosts) never leaves a stale one
    if sbx.run("exec", sb, "bash", "-lc", env_script("export.sh"), "_", env, ph).returncode != 0:
        # registered, but unusable here: undo it, so a retry starts clean instead
        # of piling up placeholders nothing records
        if sbx.run("secret", "rm", "--sandbox", sb, "--placeholder", ph, "-f").returncode == 0:
            again = shlex.join(["og", "pass", sb, env, *hosts] + (["--item", item] if item else []))
            log.err(f"og pass: couldn't write {sb}'s environment, so its registration was removed again; "
                    f"once {sb} is reachable, try again:", fix=log.cmd(again))
        else:
            log.err(f"og pass: couldn't write {sb}'s environment, nor remove its registration; remove it:",
                    fix=log.cmd(f"sbx secret rm --sandbox {sb} --placeholder {ph} -f"))   # only it: an earlier pass may still work
        return 1
    where = ", ".join(hosts)
    log.ok(f"gave {sb} {env}", f"the proxy swaps it in on {where}; {_said(src)}")
    log.record(f"gave {sb} {env}: the proxy swaps it in on {where}; {_said(src)}")
    return 0
