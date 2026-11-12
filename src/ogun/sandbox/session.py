"""Attaching to a sandbox: the upkeep every attach runs first, the session
(plain claude, or clappa where OpenAPPA protects it), and what's said after
it. `og attach <name>` runs here, and the bare `og` (bare.py) calls the same
steps through session()."""

import signal
from pathlib import Path

from ogun import mcp
from ogun.core import boxes, config, log, paths, sbx, settings
from ogun.exchange import folders, scan
from ogun.net import baseline, egress, pushrules
from ogun.sandbox import appa, remove, sandboxes

ATTACH_USAGE = "<name>"
ATTACH_HELP = dict(
    about="Start a Claude session in a sandbox that already exists, from any folder. Leaving the session "
          "only detaches: the sandbox stays until og rm.",
    forms=[("og attach <name>", "refresh the sandbox's config and rules, then start its session")],
    notes=["To create a sandbox, or to attach with --sync, --rm or a new token, run a bare og in the repo."],
    examples=["og attach cub"],
)


def attach_usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("attach", ATTACH_USAGE, problem=problem, err=err, **ATTACH_HELP)


def provision_command() -> str:
    """SBX_PROVISION, a leading ~/ made your Mac's home: sbx mounts host folders at
    their own paths, so that's where they are inside the sandbox too. "" unset."""
    cmd = settings.get("SBX_PROVISION")
    return f"{Path.home()}/{cmd[2:]}" if cmd.startswith("~/") else cmd


def provision(sb: str):
    """The provision command run inside the sandbox, at create and on every attach
    (it must be safe to run again); None when none is set, said once. Callers
    decide whether a failure is fatal."""
    cmd = provision_command()
    if not cmd:
        config.once("provision", "no provision command (SBX_PROVISION): nothing of yours run inside")
        return None
    return sbx.run("exec", sb, "bash", "-lc", cmd, wait="provisioning")


def in_sandbox(sb: str, name: str, *args: str, wait: str):
    """One of og's own scripts (sandbox-scripts/<name>), sent in as text and run
    there, so it needs nothing of og's mounted in the sandbox."""
    return sbx.run("exec", sb, "bash", "-lc", (paths.SCRIPTS / name).read_text(), name, *args, wait=wait)


def docker_relay(sb: str):
    """Docker in the sandbox reaching the internet (og's sandbox-docker.sh): a
    relay to sbx's proxy. A restart stops it, so every attach runs it again;
    it's quick when the relay is already up."""
    return in_sandbox(sb, "sandbox-docker.sh", wait="starting the docker relay")


# The proxy injects the GitHub token on HTTPS only and there are no SSH keys
# inside, so an SSH remote can neither fetch nor push: github.com remotes are
# rewritten to HTTPS, fetch and push URLs alike (several of each, possibly), and a
# rewrite rule added, since sbx puts the host's remotes back at every start.
_HTTPS = r'''cd "$1" 2>/dev/null || exit 0
https() { case "$1" in git@github.com:*) echo "https://github.com/${1#git@github.com:}" ;; ssh://git@github.com/*) echo "https://github.com/${1#ssh://git@github.com/}" ;; *) echo "$1" ;; esac; }
for r in $(git remote 2>/dev/null); do
  for k in url pushurl; do
    if us=$(git config --get-all "remote.$r.$k"); then
      git config --unset-all "remote.$r.$k"
      printf "%s\n" "$us" | while IFS= read -r u; do
        n=$(https "$u"); git config --add "remote.$r.$k" "$n"
        if [ "$n" != "$u" ]; then if [ "$k" = url ]; then echo "$r: ssh -> https"; else echo "$r (push): ssh -> https"; fi; fi
      done
    fi
  done
done
for b in git@github.com: ssh://git@github.com/; do
  git config --get-all url.https://github.com/.insteadOf 2>/dev/null | grep -qxF "$b" \
    || git config --add url.https://github.com/.insteadOf "$b"
done
exit 0'''


def https_remotes(sb: str, d: str, say: bool = True) -> bool:
    p = sbx.run("exec", sb, "bash", "-lc", _HTTPS, "_", d, wait="checking the git remotes")
    if say:
        for line in (p.stdout or "").splitlines():
            if line.strip():
                log.note(log.shown(line.strip()))
    return p.returncode == 0


SHIP_SCRIPT = "workflow-push-request.sh"   # og ship's sandbox half, which the agent runs


def ship_script(sb: str) -> bool:
    """og's own copy of og ship's sandbox half, put on the sandbox's PATH
    (~/.local/bin) whole, so the agent can hand a workflow push to the Mac. A
    failure warns: the rest of a sandbox's setup doesn't need it."""
    p = sbx.run("exec", "-i", sb, "bash", "-c",
                f"mkdir -p ~/.local/bin && cat > ~/.local/bin/{SHIP_SCRIPT}.new && chmod 755 ~/.local/bin/{SHIP_SCRIPT}.new "
                f"&& mv -f ~/.local/bin/{SHIP_SCRIPT}.new ~/.local/bin/{SHIP_SCRIPT}",
                input=(paths.SCRIPTS / SHIP_SCRIPT).read_bytes(), wait="putting og ship's script in place")
    if p.returncode:
        log.warn(f"  {log.WARNING} couldn't put og ship's script in {sb}, so a workflow push can't be handed over; "
                 "to try again, run:", fix=log.cmd(f"og {sb} --sync"))
    return p.returncode == 0


def upkeep(sb: str, ws: str, existed: bool) -> None:
    """What every attach refreshes before the session: the exchange folders, the
    provision command (what it sets up may have changed since its create), the remotes a
    restart put back, its push rules and egress as the registry says now, the
    docker relay, og ship's script, and, on a sandbox that was already there, its MCP logins. Each
    is best effort: a failure warns, and the session still starts."""
    why = folders.dirs(sb)
    if why:
        log.warn(f"  {log.WARNING} {why}", err=True)
    scan.scan(quiet=True)
    p = provision(sb)
    if p is not None and p.returncode:
        log.warn(f"  {log.WARNING} the provision command failed (SBX_PROVISION), so the sandbox may be missing what it sets up; "
                 "to set it up again, run:", fix=log.cmd(f"og {sb} --sync"))
    if ws:
        https_remotes(sb, ws, say=False)
        pushrules.push_rules(sb, ws, say=False, quiet=True)   # again: a remote added since gets its rule
        egress.egress_sync(sb, ws)
    relay = docker_relay(sb)
    if relay.returncode:
        log.warn(f"  {log.WARNING} the docker relay isn't running, so the sandbox's containers can't download; "
                 "to set it up again, run:", fix=log.cmd(f"og {sb} --sync"))
        sbx.said(relay)
    ship_script(sb)
    # after the config refresh: that exec has woken a stopped sandbox, and a load wants it running
    if existed and ws:
        mcp.refresh(sb, ws)


def who(cmd: str) -> str:
    """The start of an error line: og attach's, or the bare og's."""
    return f"og {cmd}" if cmd else "og"


def guard(cmd: str) -> bool:
    """An sbx upgrade since the last create may have put back a broad default
    rule; one that can't be removed stops the attach (fail closed)."""
    if baseline.default_rules_off("an sbx upgrade restored it"):
        return True
    log.err(f"{who(cmd)}: not attaching while one of sbx's broad default rules is on; remove it by hand (the line above), "
            "then attach again")
    return False


class _keep_session:
    """While the session runs, a Ctrl-C reaching og itself (the terminal sends
    it to the whole group) doesn't end og and take the session with it. A
    handler, not SIG_IGN: a handler resets to the default in the child."""

    def __enter__(self):
        self.old = signal.signal(signal.SIGINT, lambda *_: None)

    def __exit__(self, *exc):
        signal.signal(signal.SIGINT, self.old)
        return False


def start(sb: str, ws: str, cmd: str) -> int:
    """The session: clappa in the workspace where OpenAPPA protects the sandbox
    (checked first, or no session), plain claude everywhere else. Its exit
    status, or 1 when it didn't start."""
    if sb in sandboxes.protected():
        if not appa.ensure(sb, ws, cmd):
            return 1
        with _keep_session():
            rc = sbx.run("exec", "-it", sb, "bash", "-lc", 'cd "$1" 2>/dev/null; exec "$HOME/.local/bin/clappa"', "_", ws,
                         show=True).returncode
    else:
        with _keep_session():
            rc = sbx.run("run", "--name", sb, "claude", show=True).returncode
    return rc


def remove_after(sb: str) -> None:
    """--rm: the sandbox removed once its session ends, only when nothing would
    be lost (remove.unsafe_reasons: a check that didn't run is a reason)."""
    why = remove.unsafe_reasons(sb)
    if why:
        log.step(f"--rm skipped: '{sb}' isn't safe to remove:")
        for line in why:
            log.note(log.shown(line))
        log.info(f"  sort that out, then: {log.cmd(f'og rm {sb}')}")
        return
    log.step(f"removing '{sb}' (--rm)")
    remove.rm_clean(sb)


def attach(args: list[str]) -> int:
    if len(args) != 1 or not args[0] or args[0].startswith("-"):
        attach_usage("og attach takes one sandbox name")
        return 1
    found = sandboxes.find("attach", args[0], "nothing was started")
    if found is None:
        return 1
    sb = args[0]
    ws = sbx.workspace(sb, found.text)
    upkeep(sb, ws, True)
    if not guard("attach"):
        return 1
    return start(sb, ws, "attach")


def session(sb: str, existed: bool, rm_after: bool) -> int:
    """The bare `og` path's attach, after its token and --sync steps: the same
    upkeep and session as og attach, then --rm. Its default-rules check already
    ran (an existing sandbox) or the create applied the baseline."""
    listing = sbx.ls()
    ws = sbx.workspace(sb, listing or "")
    upkeep(sb, ws, existed)
    rc = start(sb, ws, "")
    if rm_after:
        remove_after(sb)
    return rc
