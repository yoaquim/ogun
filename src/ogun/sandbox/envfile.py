"""A new sandbox's .sbxenv.yaml: the workspace, every folder it mounts and why,
written into the workspace with og's files kept out of git."""

import glob
import os
from pathlib import Path

from ogun.core import log, settings
from ogun.sandbox import facts, init


def _yamlq(s: str) -> str:
    """A host path for a double-quoted YAML scalar: a plain scalar turns "#" into a
    comment ("/Volumes/Sandbox #1" would mount "/Volumes/Sandbox"), and quotes and
    backslashes would break the quoting itself."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


# Host reference dirs mounted READ-ONLY into every sandbox: host_ro_mounts
# (colon-separated, globs allowed, each skipped when absent), none by default. Name
# only dirs a hostile sandbox may safely READ: reference material (the Mac's font
# folders, say), never credentials or state.
def host_ro_mounts() -> list[str]:
    return [m for m in settings.get("host_ro_mounts").split(":") if m]


def host_named() -> list[tuple[str, str]]:
    """Each folder host_ro_mounts names that's there, as (its path, its real path):
    sbx mounts the real one. ~ is expanded here: sbx expands nothing but its own
    ${{ env.* }} references."""
    return [(os.path.abspath(hm), init.real_path(hm)) for pat in host_ro_mounts()
            for hm in (sorted(glob.glob(os.path.expanduser(pat))) if pat else []) if os.path.isdir(hm)]


def host_mounts(d: str, related: list[str] = ()) -> list[tuple[str, str]]:
    """host_named(), less those another rule already mounts (the workspace, a related
    checkout): sbx rejects one path mounted twice ("conflicting read-only settings") at
    create time."""
    dr = init.real_path(d)
    return [(a, r) for a, r in host_named() if r not in (d, dr) and r not in related]


def linked(p: str) -> tuple[str, str] | None:
    """(p, its real path) when a link lies on its way, else None: sbx mounts the real
    path, so og makes the same link inside (sandbox-scripts/mount-links.sh) and p
    works there too."""
    a, r = os.path.abspath(p), init.real_path(p)
    return (a, r) if a != r else None


def _under(p: str, roots: list[str]) -> bool:
    return any(p == r or p.startswith(r.rstrip("/") + "/") for r in roots if r)


def outside_links(roots: list[str], mounted: list[str], cap: int = 5000) -> tuple[list[tuple[str, str]], bool]:
    """The links inside roots whose target is there on the Mac but under no mounted
    folder: inside the sandbox they point at nothing. Never mounted for you (a link
    to ~/.ssh would hand every sandbox your keys); said, so you can name the folder
    yourself. True with them when it stopped looking after cap entries."""
    found, seen = [], 0
    for root in roots:
        for dp, dns, fns in os.walk(root):   # never follows a link: one to a folder is listed, not entered
            dns[:] = [x for x in dns if x != ".git"]
            for n in dns + fns:
                seen += 1
                if seen > cap:
                    return found, True
                p = os.path.join(dp, n)
                if os.path.islink(p) and os.path.exists(p):
                    t = init.real_path(p)
                    if not _under(t, mounted):
                        found.append((p, t))
    return found, False


def say_outside_links(roots: list[str], mounted: list[str]) -> None:
    """outside_links(), a warning each (the first five), with the entry that would cover it."""
    found, cut = outside_links(roots, mounted)
    for link, t in found[:5]:
        folder = t if os.path.isdir(t) else os.path.dirname(t)
        log.warn(f"  {log.WARNING} {log.path(link)} links to {log.path(t)}, which this sandbox doesn't mount; "
                 f"to use it, add {log.path(folder)} to host_ro_mounts", err=True)
    if len(found) > 5:
        log.note(f"and {len(found) - 5} more such links", err=True)
    if cut:
        log.note("stopped looking for links outside the mounts after 5000 entries", err=True)


def git_excludes(d: str) -> None:
    """og's own files out of git: .sbxenv.yaml and .inbox/ in the repo's
    info/exclude, wherever git keeps it: a linked worktree's .git is a file, and a
    subdirectory shares its repo's."""
    if not d or not os.path.isdir(d):   # `git -C ""` would act on the current repo
        return
    p = init.run_git(d, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude")
    if p.returncode:
        return
    ex = Path(p.stdout.rstrip("\n"))
    try:
        ex.parent.mkdir(parents=True, exist_ok=True)
        have = ex.read_text().splitlines() if ex.is_file() else []
        with open(ex, "a") as f:
            for line in (".sbxenv.yaml", ".inbox/"):
                if line not in have:
                    f.write(line + "\n")
    except OSError:
        pass


def _mounts_shown(yaml: str) -> None:
    """The folders the new sandbox gets, as og wrote them: sbx's own plan of the
    same file is kept for a failure (and -vv)."""
    ms = facts.mounts(yaml)
    log.step(f"{len(ms)} folders mounted besides the workspace")
    for m in ms:
        log.note(f"{m['path']}{' (read-only)' if m['read_only'] else ''}")


def env_yaml(name: str, d: str, box: Path, related: list[str] = (), marketplaces: list[str] = (), ssh_keys: str = "",
             image: str = "") -> str:
    """The new sandbox's .sbxenv.yaml: the workspace, then every folder it mounts."""
    from ogun.exchange import folders
    # The project itself is the read-write workspace (a private clone); every other
    # folder is read-only, a host folder only when
    # host_ro_mounts names it
    y = ['schemaVersion: "1"', f"name: {name}", "agent: claude", "workspace:", f'  path: "{_yamlq(d)}"', "  clone: true",
         "additionalWorkspaces:"]
    ro = "    readOnly: true"
    # the ssh-keys folder (checked before): read-only stops edits, not copies
    if ssh_keys:
        y += [f'  - path: "{_yamlq(ssh_keys)}"', ro]
    y += [x for p in related if p != d for x in (f"  - path: {p}", ro)]
    y += [x for p in marketplaces for x in (f'  - path: "{_yamlq(p)}"', ro)]
    # exchange mounts (docs/exchange.md): read-only parents first, then
    # this sandbox's own writable subdirs inside/beside them. Quoted: a relocated
    # root may hold '#' or quotes, which a plain scalar truncates or breaks on.
    exy = _yamlq(str(folders.exchange()))
    y += [f'  - path: "{exy}/inbox"', ro, f'  - path: "{exy}/shared"', ro, f'  - path: "{exy}/shared/{name}"',
          f'  - path: "{_yamlq(str(box))}/out"',
          # this sandbox's PRIVATE inbox: host-written, read-only inside — files for
          # just this sandbox (og give <name>), so the broadcast inbox/ stays small
          f'  - path: "{_yamlq(str(box))}/in"', ro]
    # host reference mounts (host_ro_mounts, none by default): read-only, at their
    # real paths, skipped when absent or already mounted
    for _, hmr in host_mounts(d, related):
        y += [f'  - path: "{_yamlq(hmr)}"', ro]
    if image:
        y += ["sandboxOptions:", f"  template: {image}"]
    # Gateway servers (an issue tracker's, say) are not named here: .sbxenv.yaml wants a
    # url|command per server and guards urls against loopback, so they attach
    # after creation via `sbx mcp load`.
    return "\n".join(y) + "\n"


def write_env(d: str, yaml: str) -> Path | None:
    """The env file written into the workspace, its mounts said, og's files kept
    out of git, and the workspace's .inbox made."""
    env = Path(d) / ".sbxenv.yaml"
    try:
        env.write_text(yaml)
    except OSError as e:
        log.err(f"og: couldn't write {env}: {e.strerror}")
        return None
    log.step(f"wrote {env}")
    _mounts_shown(yaml)
    git_excludes(d)
    try:
        (Path(d) / ".inbox").mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return env
