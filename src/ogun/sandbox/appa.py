"""OpenAPPA (docs/appa.md): the pinned release in appa.lock (og's config folder) and
its install into a sandbox. Only where protection is on: `og --appa` at create,
or `# appa: on` in a template recipe. A sandbox with neither gets nothing of it."""

import base64
import io
import os
import re
import shlex
import tarfile
from pathlib import Path

from ogun.core import config, log, paths, sbx

REPO = "https://github.com/archestra-ai/OpenAPPA"
EGRESS = "release-assets.githubusercontent.com"   # where a GitHub release download lands; github.com is in the baseline


def lock_file() -> Path:
    return config.file("appa.lock")


def lock(key: str) -> str:
    """A value from the lock: `version`, or a platform's SHA-256."""
    try:
        lines = lock_file().read_text().splitlines()
    except OSError:
        return ""
    for line in lines:
        f = line.split()
        if f and not line.startswith("#") and f[0] == key:
            return f[1] if len(f) > 1 else ""
    return ""


def install(sb: str, cmd: str = "") -> bool:
    """The pinned OpenAPPA into the sandbox: og's appa/install.sh sent in
    as text, with the release download host allowed for that sandbox alone
    (`sbx rm` drops the rule). cmd: the og command running it, for its errors."""
    who = f"og {cmd}" if cmd else "og"
    if not lock_file().is_file():
        config.missing(who, "appa.lock", lock_file())
        return False
    v, a, x = lock("version"), lock("aarch64-unknown-linux-gnu"), lock("x86_64-unknown-linux-gnu")
    if not (re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", v) and re.fullmatch(r"[0-9a-f]{64}", a) and re.fullmatch(r"[0-9a-f]{64}", x)):
        log.err(f"{who}: {log.path(lock_file())} needs a version and both Linux SHA-256s")
        return False
    log.step(f"OpenAPPA {v}")
    p = sbx.run("policy", "allow", "network", "--sandbox", sb, EGRESS, wait=f"allowing {EGRESS}")
    if p.returncode:
        log.err(f"{who}: could not allow {EGRESS} for {sb}, where OpenAPPA downloads from")
        sbx.said(p)
        return False
    script = (paths.SCRIPTS / "appa" / "install.sh").read_text()
    p = sbx.run("exec", sb, "bash", "-c", script, "_", v, a, x, REPO, wait=f"installing OpenAPPA {v}")
    if p.returncode:
        log.err(f"{who}: OpenAPPA {v} could not be installed in {sb}")
        sbx.said(p)
        return False
    for line in (p.stdout or "").splitlines()[-1:]:
        log.note(log.shown(line.strip()))
    return True


# ── turning it on, and checking it before a session ──

BUNDLE = ("activate.sh", "ensure.sh", "policy.py")   # activate.sh runs the other two beside it


def bundle() -> str:
    """og's scripts that turn OpenAPPA on and check it, as a gzipped tar in
    base64: what a sandbox gets on stdin, its modes kept."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name in BUNDLE:
            t.add(paths.SCRIPTS / "appa" / name, arcname=name)
    return base64.b64encode(buf.getvalue()).decode()


def runner(provision: str) -> str:
    """The shell that unpacks the bundle into a fresh private folder, runs the
    script it's given ($0), and removes the folder: nothing is left for a later
    run to trust. provision: og's provision command (provision), which
    activate.sh runs again once its marker is written; none, and it does without."""
    return (f"OGUN_PROVISION={shlex.quote(provision)} "
            'd=$(mktemp -d) && base64 -d | tar -xzf - -C "$d" && OGUN_PROVISION=$OGUN_PROVISION bash "$d/$0" "$@"; '
            'rc=$?; rm -rf "$d"; exit "$rc"')


def _provision() -> str:
    from ogun.sandbox import session  # session runs these scripts too
    return session.provision_command()


def script(sb: str, name: str, *args: str, wait: str = "") -> object:
    """One of og's appa scripts, run inside the sandbox from the bundle og sends
    in, so it needs nothing of og's mounted in the sandbox."""
    return sbx.run("exec", "-i", sb, "bash", "-lc", runner(_provision()), name, *args,
                   input=bundle().encode(), wait=wait or f"running {name}")


_PLACE_RE = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:[0-9]{1,5})?(/[A-Za-z0-9._-]+)+")


def private(d: str) -> list[str]:
    """The other private places the repo's registry entry names ("appa":
    {"private": ["host/path", …]}): remotes off GitHub that a push from its
    sandbox may reach without a card. Same owner gate as "template". GitHub
    repos are refused: OpenAPPA asks GitHub whether one is private, and a listed
    public one would take private reads without a question."""
    repo = os.path.basename(d.rstrip("/"))
    entry = paths.registry_entry(repo)
    a = entry.get("appa") if isinstance(entry, dict) else None
    if a is None:
        return []
    places = a.get("private") if isinstance(a, dict) else None
    say = lambda msg: log.warn(f"  {log.WARNING} appa: {msg}", err=True)   # noqa: E731
    if not isinstance(places, list):
        say(f"repo '{repo}' needs \"appa\": {{\"private\": [\"host/path\", …]}}; skipped")
        return []
    no = paths.refusal(d, entry)
    if no == "unplaced":
        say(f"repo '{repo}' names private places, but this folder is not the repo it describes "
            f"({paths.shown_repo(repo)}, or the entry's `path`); skipped")
        return []
    if no:
        say(f"repo '{repo}' names private places for owner '{entry.get('owner')}', but this sandbox's owner is "
            f"'{paths.org_from_path(d)}'; skipped (add or fix the entry's `owner`)")
        return []
    out = []
    for p in places:
        if not (isinstance(p, str) and _PLACE_RE.fullmatch(p) and ".." not in p.split("/")):
            say(f"private place {log.shown(repr(p))} must be host/path, no scheme (git.example.com/me/repo); skipped")
        elif p.split("/")[0].split(":")[0] in ("github.com", "www.github.com"):
            say(f"private place '{p}' is on GitHub, which says itself whether a repo is private; skipped")
        else:
            out.append(p)
    return out


def activate(sb: str, ws: str, related: list[str] | None = None) -> bool:
    """OpenAPPA turned on inside the sandbox (activate.sh): the read-only mounts
    (related: the create's own list; otherwise the registry's now) count as
    private too, and so do the registry's other private places."""
    from ogun.core import registry
    ro = [p for p in (registry.related(ws, quiet=True) if related is None else related) if p and p != ws]
    places = private(ws)
    if places:
        log.step("OpenAPPA: other private places (registry):")
        for p in places:
            log.note(p)
    priv = [x for p in places for x in ("--private", p)]
    p = script(sb, "activate.sh", lock("version"), ws, *priv, *ro, wait="turning OpenAPPA on")
    if p.returncode:
        sbx.said(p)
    return p.returncode == 0


def ensure(sb: str, ws: str, cmd: str) -> bool:
    """Before a protected session: OpenAPPA's hooks in place and its runtime up
    (ensure.sh), or no session. One with OpenAPPA installed but not on (exit 3)
    is turned on first; activate.sh ends with ensure.sh."""
    p = script(sb, "ensure.sh", wait="checking OpenAPPA")
    if p.returncode == 3:
        log.step(f"turning OpenAPPA on in '{sb}' (created before protection)")
        if ws and activate(sb, ws):
            return True
        log.err(f"{'og ' + cmd if cmd else 'og'}: not starting '{sb}' unprotected: OpenAPPA couldn't be turned on. To start over, remove it, "
                f"then create it again with og --appa:", fix=log.cmd(f"og rm {sb}"))
        return False
    if p.returncode:
        sbx.said(p)
        log.err(f"{'og ' + cmd if cmd else 'og'}: not starting '{sb}' unprotected: OpenAPPA isn't ready; to set it up again, run:",
                fix=log.cmd(f"og {sb} --sync"))
        return False
    return True
