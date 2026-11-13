"""The common base a sandbox starts with: og's apt tools and any apt_tools
names, and the latest Claude Code. A template build installs it into its image; setup() puts it, and
the rest of a sandbox's setup, in place at create and on attach --sync."""

import os
import random
import time

from ogun.core import log, sbx, settings

OWN_TOOLS = "jq socat"   # og's scripts read JSON with jq; the docker relay is socat


def apt_tools_list() -> str:
    """og's own apt tools, then those apt_tools adds (space-separated), each once."""
    return " ".join(dict.fromkeys([*OWN_TOOLS.split(), *settings.get("apt_tools").split()]))


_APT_WAIT = r"""for i in $(seq 60); do
  sudo fuser /var/lib/apt/lists/lock /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock >/dev/null 2>&1 || exit 0
  sleep 5
done; echo "apt still locked after 5m" >&2; exit 1"""


def apt_wait(sb: str) -> bool:
    """The sandbox image runs its own apt at first boot, and ours must queue
    behind it: wait until apt's and dpkg's locks are free, five minutes at most."""
    p = sbx.run("exec", sb, "bash", "-lc", _APT_WAIT, wait="waiting for the image's first-boot apt to finish")
    if p.returncode:
        sbx.said(p)
    return p.returncode == 0


def tools(sb: str) -> bool:
    """The apt tools installed, sbx's words shown if not."""
    tools = apt_tools_list()
    p = sbx.run("exec", sb, "bash", "-lc", "sudo apt-get -o DPkg::Lock::Timeout=180 update -qq && "
                f"sudo apt-get -o DPkg::Lock::Timeout=180 install -y -qq {tools}", wait=f"installing {tools}")
    return _ran(p)



def _ran(p) -> bool:
    """Whether the call worked; when it didn't, the last lines sbx printed."""
    if p.returncode:
        for line in ((p.stdout or "") + (p.stderr or "")).splitlines()[-5:]:
            if line.strip():
                log.note(log.shown(line.strip()), err=True)
    return p.returncode == 0


# The updater logs inside the sandbox between two `ogun:` lines (start, exit), so
# a timeout, which kills the exec before its output is printed, still shows where
# it stopped: a second exec reads the log's tail, and an exit line there means
# `sbx exec` itself never returned. Each run empties the log and tags its exit
# line with a run id, so an earlier run's line can't read as this one's. Prints
# `v <before> <after>` last (the updater's tail before it on failure); exits 0
# or 1 only, so a timeout is og's alone.
_UPDATE = r"""L=%s; : > "$L"; export PATH="$HOME/.local/bin:$PATH"
ver() { claude --version 2>/dev/null | awk "NR==1{print \$1}"; }
command -v claude >/dev/null || { echo "claude not found"; exit 1; }
b=$(ver); echo "ogun: claude update from ${b:-?} at $(date +%%T) (run $1)" >> "$L"
claude update < /dev/null >> "$L" 2>&1; rc=$?; a=$(ver)
echo "ogun: updater exited $rc at $(date +%%T), now ${a:-?} (run $1)" >> "$L"
[ "$rc" = 0 ] || grep -v "^ogun: " "$L" | tail -3
echo "v ${b:-?} ${a:-?}"; [ "$rc" = 0 ]"""


UPDATE_TIMEOUT = 300   # seconds; the download is ~230 MB
UPDATE_LOG = "/tmp/ogun-claude-update.log"   # inside the sandbox


def update_timeout() -> int:
    return UPDATE_TIMEOUT


def update_log() -> str:
    return UPDATE_LOG


def claude_update(sb: str) -> None:
    """The sandbox's Claude Code (the native install, ~/.local/bin/claude) brought
    to the latest release with `claude update`. Best effort and bounded: a blocked
    download or a hung updater warns, never fails the caller. The binary comes
    from downloads.claude.ai, which sbx already allows for the claude agent."""
    secs, where = update_timeout(), update_log()
    run = f"{int(time.time())}-{os.getpid()}-{random.randrange(32768)}"
    log.step("claude code (latest)")
    p = sbx.run("exec", sb, "bash", "-lc", _UPDATE % _quoted(where), "_", run, timeout=secs, cap=16384,
                wait="updating Claude Code")
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode == 0:
        v = next((line.split() for line in reversed(out.splitlines()) if line.startswith("v ")), [])
        b, a = [*v[1:3], "?", "?"][:2]
        log.note(f"{a} (already the latest)" if b == a else f"{b} → {a}")
        log.note("a claude session already running keeps its version until restarted")
    elif p.returncode == 124:
        log.warn(f"  {log.WARNING} claude update timed out after {secs}s; it goes on with the installed version. Its log so far:")
        t = sbx.run("exec", sb, "tail", "-5", where, timeout=15, cap=4096, wait="reading the updater's log")
        tail = (t.stdout or "") + (t.stderr or "")
        for line in tail.splitlines():
            log.note(log.shown(line))
        if any("ogun: updater exited " in line and line.endswith(f"(run {run})") for line in tail.splitlines()):
            log.warn(f"  {log.WARNING} the updater finished inside the sandbox: it was sbx exec that never returned")
    else:
        log.warn(f"  {log.WARNING} claude update failed (network policy? downloads.claude.ai); it goes on with the installed version")
        for line in [x for x in out.splitlines() if not x.startswith("v ")][-3:]:
            log.note(log.shown(line))


def _quoted(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


# ── setup: create, and attach --sync ──


def setup(sb: str) -> bool:
    """A sandbox's setup, in order: the ssh-agent probe (an existing sandbox is
    probed too: it may predate the restart), apt tools (best effort), the
    latest Claude Code, the provision command (must succeed when set),
    ssh keys from the mounted folder (checked again every time: the folder is
    live), the docker relay, the exchange's shared root. False: stop, nothing
    after it runs."""
    from ogun.exchange import folders
    from ogun.sandbox import session
    from ogun.secrets import sshkeys
    if not sshkeys.agent_absent(sb):
        return False
    if not apt_tools(sb):
        return False
    claude_update(sb)
    mount_links(sb)
    log.step("provision")
    p = session.provision(sb)
    if p is not None and p.returncode:
        log.warn(f"  {log.WARNING} the provision command failed (provision)")
        sbx.said(p)
        return False
    if not ssh_keys(sb):
        return False
    log.step("docker in the sandbox")
    p = session.docker_relay(sb)
    if p.returncode:
        log.warn(f"  {log.WARNING} docker relay setup failed, so the sandbox's containers can't download; to try again, run:",
                 fix=log.cmd(f"og {sb} --sync"))
        sbx.said(p)
    # the exchange's shared root, recorded inside: og ship's script finds the
    # sandbox's out/ through it, wherever the exchange is
    p = sbx.run("exec", sb, "bash", "-lc", 'mkdir -p ~/.config/sbx && printf "%s\\n" "$1" > ~/.config/sbx/exchange-shared-root',
                "_", str(folders.exchange() / "shared"), wait="recording the exchange's place")
    if p.returncode:
        log.warn(f"  {log.WARNING} couldn't record the exchange's place, so og ship's script in {sb} won't find its out/; "
                 "to try again, run:", fix=log.cmd(f"og {sb} --sync"))
    session.ship_script(sb)
    return True


def mount_links(sb: str) -> None:
    """The links the sandbox's mounts were reached through, made inside
    (sandbox-scripts/mount-links.sh), before the provision command, which may run
    through one. From its create record; a failure is said, and setup goes on."""
    from ogun.core import records
    from ogun.sandbox import session
    pairs = [x for x in (records.read_record(sb) or {}).get("links") or []
             if isinstance(x, list) and len(x) == 2 and all(isinstance(p, str) for p in x)]
    if not pairs:
        return
    log.step("linked mounts")
    p = session.in_sandbox(sb, "mount-links.sh", *(v for pr in pairs for v in pr), wait="making the links its mounts were named by")
    if p.returncode:
        log.warn(f"  {log.WARNING} not every linked mount could be made inside; their own paths work there:")
        for line in (p.stdout or "").splitlines()[-5:]:
            log.note(log.shown(line))


def apt_tools(sb: str) -> bool:
    """The apt tools, once the image's own first-boot apt is done: False when it never
    is; a failed install is said, and setup goes on without them."""
    log.step("tools")
    if not apt_wait(sb):
        return False
    tools = apt_tools_list()
    p = sbx.run("exec", sb, "bash", "-lc", "sudo apt-get -o DPkg::Lock::Timeout=180 update -qq 2>&1 && "
                f"sudo apt-get -o DPkg::Lock::Timeout=180 install -y -qq {tools} 2>&1", wait=f"installing {tools}")
    if p.returncode:
        log.warn(f"  {log.WARNING} apt failed, so it goes on without {tools}. If the network policy is why, "
                 "put the baseline back:", fix=log.cmd("og policy"))
        for line in (p.stdout or "").splitlines()[-3:]:
            log.note(log.shown(line))
    return True


def ssh_keys(sb: str) -> bool:
    """ssh keys from the mounted folder, when there is one: False when the
    folder fails its check; a failed setup is said, and setup goes on."""
    from ogun.sandbox import session
    from ogun.secrets import sshkeys
    # a sandbox created before the folder existed has no mount, and the script
    # then leaves ssh unset
    d = sshkeys.keys_dir()
    if d:
        if not sshkeys.keys_check():
            return False
        log.step(f"ssh keys from {d}")
        if session.in_sandbox(sb, "sandbox-ssh.sh", d, wait="setting up ssh").returncode:
            log.warn(f"  {log.WARNING} ssh key setup failed; HTTPS still works. To try again, run:", fix=log.cmd(f"og {sb} --sync"))
    return True

