"""SSH in a sandbox without the Mac's agent (docs/sandboxes.md). Two
guards:

- the agent probe: the ssh-agent forwarding setting is only the SAVED value;
  until the daemon restarts, a sandbox may still reach the Mac's agent, which
  holds the host's keys, perhaps a commit-signing one. So setup asks the sandbox.
- the key folder: <ssh dir>/sandbox is mounted read-only into every sandbox and
  its keys copied in (og's sandbox-ssh.sh). Every sandbox can read and
  copy what's there, so a protected key (protected_keys) is refused, and so is a
  symlink (it could point at one)."""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ogun.core import log, sbx, settings

# sbx documents no daemon start time to compare against, so the sandbox itself is
# the signal. The agent reaches it two ways: a socket (SSH_AUTH_SOCK, sbx's
# /run/ssh-agent.sock) and the gateway's TCP port behind it, which answers the
# agent protocol to any process that connects; so the probe asks that port for
# identities too, and any reply is an agent. OG_AGENT_SOCK and OG_AGENT_GATEWAY
# override its defaults, so the tests run it outside a sandbox.
PROBE = r'''
    s=${SSH_AUTH_SOCK:-}; k=${OG_AGENT_SOCK-/run/ssh-agent.sock}
    if { [ -n "$s" ] && [ -S "$s" ]; } || { [ -n "$k" ] && [ -S "$k" ]; }; then echo agent:present; exit 0; fi
    if command -v ssh-add >/dev/null 2>&1 && { ssh-add -l >/dev/null 2>&1; [ $? -ne 2 ]; }; then echo agent:present; exit 0; fi
    ask() { exec 3<>"/dev/tcp/$1/$2" || return 1; printf "\000\000\000\001\013" >&3; head -c1 <&3 | od -An -tx1; }
    export -f ask
    for g in ${SSH_AUTH_SOCK_GATEWAY:-} ${OG_AGENT_GATEWAY-gateway.docker.internal:3129}; do
        h=${g%:*}; p=${g##*:}; { [ -n "$h" ] && [ -n "$p" ] && [ "$h" != "$g" ]; } || continue
        r=$(timeout 3 bash -c "ask \"\$@\"" _ "$h" "$p" 2>/dev/null)
        [ -n "${r// /}" ] && { echo agent:present; exit 0; }
    done
    echo agent:none'''


def agent_absent(sb: str, cmd: str = "") -> bool:
    """The sandbox reaches no ssh-agent: it says agent:none and never
    agent:present. A probe that didn't run, or answered nothing, is a refusal."""
    who = f"og {cmd}" if cmd else "og"
    p = sbx.run("exec", sb, "bash", "-lc", PROBE, wait=f"checking that {sb} can't reach this Mac's ssh-agent")
    if p.returncode:
        log.err(f"{who}: could not run the ssh-agent check in '{sb}'; sbx said:")
        for line in (p.stderr or "").splitlines()[-3:]:
            log.note(log.shown(line), err=True)
        return False
    lines = (p.stdout or "").splitlines()
    if "agent:none" in lines and not any("agent:present" in x for x in lines):
        return True
    log.err(f"{who}: '{sb}' can reach the Mac's ssh-agent (and every key it holds): the forwarding setting is off but the daemon "
            "hasn't applied it. Restart it (running sandboxes stop), then try again:", fix=log.cmd("sbx daemon restart"))
    return False


def ssh_dir() -> Path:
    return Path.home() / ".ssh"


# a public key's first word is its type, whole: a signers file's first word is who it trusts,
# which may itself start "ssh-" (ssh-user@example.com)
KEY_TYPE_RE = re.compile(r"(?:ssh-(?:ed25519|rsa|dss)|ecdsa-sha2-nistp(?:256|384|521)"
                         r"|sk-(?:ssh-ed25519|ecdsa-sha2-nistp256)@openssh\.com)(?:-cert-v01@openssh\.com)?")


def is_key_file(p: Path) -> bool:
    """A key, private or public, rather than a signers file (whose lines start with
    who is trusted): its first line that isn't blank or a comment starts like a key."""
    try:
        lines = p.read_text(errors="replace").splitlines()
    except OSError:
        return False
    first = next((ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")), "")
    return first.startswith("-----BEGIN") or bool(KEY_TYPE_RE.fullmatch(first.split()[0] if first else ""))


def protected_keys() -> list[Path]:
    """protected_keys: the files whose keys never go into a sandbox's keys folder,
    colon-separated, each a key (private or public) or a signers file (git's
    allowed_signers form, every key it trusts). Unset, git's own allowed_signers in the
    ssh folder. A path that isn't full stops og: a key meant to be kept out would not be."""
    v = settings.get("protected_keys")
    if not v:
        return [ssh_dir() / "allowed_signers"]
    out = []
    for p in v.split(":"):
        if not p.startswith(("/", "~/")):
            raise settings.Unreadable(f"protected_keys: '{log.shown(p)}' isn't a full path (/… or ~/…)")
        out.append(Path(p).expanduser())
    return out


def keys_dir(quiet: bool = False) -> str:
    """The folder when it's a real directory; a symlinked one is never mounted."""
    d = ssh_dir() / "sandbox"
    if d.is_symlink():
        if not quiet:
            log.warn(f"  {log.WARNING} {d} is a symlink, so it isn't mounted (it must be a real folder)", err=True)
        return ""
    return str(d) if d.is_dir() else ""


def _keygen(*args: str, stdin: bytes | None = None) -> str:
    p = subprocess.run(["ssh-keygen", *args], input=stdin if stdin is not None else b"", capture_output=True, check=False)
    return p.stdout.decode("utf-8", "replace")


def _sha(out: str) -> set[str]:
    return {f[1] for f in (line.split() for line in out.splitlines()) if len(f) > 1 and f[1].startswith("SHA256:")}


def fps(f: str) -> set[str]:
    """Every fingerprint a file can stand for: as itself (a public key, or a
    private one ssh-keygen -l reads through its .pub beside it), a private copy
    on its own (no .pub to read instead), and the public key derived from it
    with an empty passphrase (never a prompt)."""
    out = set()
    if not os.path.isfile(f):
        return out
    t = tempfile.mkdtemp()
    try:
        k = os.path.join(t, "k")
        try:
            shutil.copyfile(f, k)
            os.chmod(k, 0o600)
        except OSError:
            pass
        out |= _sha(_keygen("-lf", f))
        out |= _sha(_keygen("-lf", k))
        pub = _keygen("-y", "-P", "", "-f", k)
        if pub.strip():
            out |= _sha(_keygen("-lf", "-", stdin=pub.encode()))
    finally:
        shutil.rmtree(t, ignore_errors=True)
    return out


def signer_fps(f: Path) -> set[str]:
    """The keys an allowed-signers file trusts: each line's first key type and its key."""
    try:
        lines = f.read_text().splitlines()
    except OSError:
        return set()
    keys = []
    for line in lines:
        if line.lstrip().startswith("#"):
            continue
        w = line.split()[:-1]
        # the key type, whole: who it trusts may start "ssh-" too (ssh-user@example.com); a type
        # this list doesn't know is taken by its start only when no word is one it knows
        i = next((n for n, x in enumerate(w) if KEY_TYPE_RE.fullmatch(x)), None)
        if i is None:
            i = next((n for n, x in enumerate(w) if x.startswith(("ssh-", "ecdsa-", "sk-"))), None)
        if i is not None:
            keys.append(f"{w[i]} {line.split()[i + 1]}")
    return _sha(_keygen("-lf", "-", stdin=("\n".join(keys) + "\n").encode())) if keys else set()


def keys_check(cmd: str = "") -> bool:
    """The folder is absent or safe to mount: no symlink at any depth, and no key
    protected_keys keeps out, its own or one a signers file it names trusts."""
    who = f"og {cmd}" if cmd else "og"
    d = keys_dir(quiet=True)
    if not d:
        return True
    links, files = [], []
    for root, dirs, names in os.walk(d):
        for n in dirs + names:
            p = os.path.join(root, n)
            if os.path.islink(p):
                links.append(p)
            elif n in names and os.path.isfile(p):
                files.append(p)
    if links:
        log.err(f"{who}: {d} holds a symlink. It could point at a key that must stay out, and every sandbox reads this folder; "
                "copy the file in instead:")
        for p in sorted(links):
            log.note(p, err=True)
        return False
    if not files:
        return True
    if shutil.which("ssh-keygen") is None:
        log.err(f"{who}: ssh-keygen isn't installed, so {d} can't be checked for trusted keys; it won't be mounted")
        return False
    # each protected key's fingerprint, and how it's protected: a key file, or a signers file trusting it
    kept: dict[str, str] = {}
    for p in protected_keys():
        if not p.is_file():
            continue
        if is_key_file(p):
            for fp in fps(str(p)) | (fps(f"{p}.pub") if Path(f"{p}.pub").is_file() else set()):
                kept.setdefault(fp, f"is the key in {p}")
        else:
            for fp in signer_fps(p):
                kept.setdefault(fp, f"is a key {p} trusts")
    for f in files:
        for fp in sorted(fps(f)):
            if fp in kept:
                log.err(f"{who}: {f} {kept[fp]}, which protected_keys keeps out of sandboxes ({fp}): "
                        f"every sandbox can read and copy {d}, so it can't go there. Remove it.")
                return False
    return True
