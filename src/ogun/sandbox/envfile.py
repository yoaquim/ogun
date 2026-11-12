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


# Host reference dirs mounted READ-ONLY into every sandbox: SBX_HOST_RO_MOUNTS
# (colon-separated, globs allowed, each skipped when absent), none by default. Name
# only dirs a hostile sandbox may safely READ: reference material (the Mac's font
# folders, say), never credentials or state.
def host_ro_mounts() -> list[str]:
    return [m for m in settings.get("SBX_HOST_RO_MOUNTS").split(":") if m]


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
    # SBX_HOST_RO_MOUNTS names it
    dr = init.real_path(d)
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
    # host reference mounts (SBX_HOST_RO_MOUNTS, none by default): read-only,
    # skipped when absent — and skipped when another rule already mounts the path
    # (the workspace, a related checkout): sbx rejects one path mounted twice
    # ("conflicting read-only settings") at create time. Written out in full: sbx
    # expands nothing but its own ${{ env.* }} references, so ~ is expanded here
    for pat in host_ro_mounts():
        for hm in sorted(glob.glob(os.path.expanduser(pat))) if pat else []:
            if not os.path.isdir(hm):
                continue
            hmr = init.real_path(hm)
            if hmr in (d, dr) or hmr in related:
                continue
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
