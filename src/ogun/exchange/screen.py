"""The checks every file a sandbox wrote goes through before it reaches the Mac: its
name, its kind and its bytes; a clean one placed, never over another, and the rest
quarantined, never deleted."""

import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path

from ogun.core import log, settings
from ogun.exchange import folders

_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+ -]*")
_EXEC_MIME = {"application/x-mach-binary", "application/x-executable", "application/x-sharedlib",
              "application/x-pie-executable", "application/x-dosexec"}
# for the formats people double-click, the extension must not lie about the content
_EXT_MIME = {
    "pdf": lambda m: m == "application/pdf",
    "png": lambda m: m == "image/png",
    "jpg": lambda m: m == "image/jpeg", "jpeg": lambda m: m == "image/jpeg",
    "gif": lambda m: m == "image/gif",
    "zip": lambda m: m == "application/zip",
    "gz": lambda m: m in ("application/gzip", "application/x-gzip"), "tgz": lambda m: m in ("application/gzip", "application/x-gzip"),
    "html": lambda m: m == "text/html", "htm": lambda m: m == "text/html",
    "md": lambda m: m.startswith("text/") or m == "inode/x-empty", "txt": lambda m: m.startswith("text/") or m == "inode/x-empty",
    "csv": lambda m: m.startswith("text/") or m == "inode/x-empty", "log": lambda m: m.startswith("text/") or m == "inode/x-empty",
    "json": lambda m: m == "application/json" or m.startswith("text/"),
}


def take_dest() -> Path:
    return settings.path("SBX_TAKE_DEST", Path.home() / "Downloads")


shown = log.shown


def _mime(f: Path) -> str:
    try:
        p = subprocess.run(["file", "-b", "--mime-type", "--", str(f)], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        return (p.stdout.strip() or "unknown") if p.returncode == 0 else "unknown"
    except OSError:
        return "unknown"


def check(f: Path, mode: str) -> str | None:
    """Why f can't pass (out: to the Mac; shared: to other sandboxes), or None."""
    # one look at the file, never two: a running sandbox can remove or swap it in
    # between, and a check that raised would stop the whole scan
    try:
        st = f.lstat()
    except FileNotFoundError:
        return None   # gone since the listing: nothing left to check
    except OSError:
        return "can't be read"
    if stat.S_ISLNK(st.st_mode):
        return "symlink"
    if not stat.S_ISREG(st.st_mode):
        return "not a regular file"
    if st.st_nlink > 1:
        return "hardlinked elsewhere"
    # names are attacker-chosen: printable, no leading dot or dash, no shell or
    # terminal surprises. The reason never quotes the name: it's printed as is
    if not _SAFE_NAME.fullmatch(f.name):
        if not _SAFE_NAME.fullmatch(f.name[:1]):
            return "its name doesn't start with a letter or digit"
        return "its name has a character other than letters, digits, spaces and . _ + -"
    mime = _mime(f)
    ext = f.name.rsplit(".", 1)[1].lower() if "." in f.name else ""
    if mode == "shared":
        if st.st_size > 1 << 20:
            return "over 1MB (shared is text)"
        if ext not in ("md", "txt", "json"):
            return "shared is .md/.txt/.json only"
        if not (mime.startswith("text/") or mime in ("application/json", "inode/x-empty")):
            return "its content couldn't be identified" if mime == "unknown" else f"claims .{ext} but content is {mime}"
        # the shared mount is read-only but not noexec, and live paths are never
        # chmodded: an executable text file is quarantined, not de-exec'd
        if os.access(f, os.X_OK):
            return "executable bit set"
        return None
    if st.st_size > 1 << 30:
        return "over 1GB"
    if mime in _EXEC_MIME:
        return "executable content"
    if ext in _EXT_MIME and not _EXT_MIME[ext](mime):
        return "its content couldn't be identified" if mime == "unknown" else f"claims .{ext} but content is {mime}"
    return None


def tag(f: Path) -> bool:
    """Never executable, and Gatekeeper's mark (the com.apple.quarantine xattr) so
    Gatekeeper checks it before it opens. No xattr: not a Mac, no Gatekeeper,
    nothing to mark. On a Mac a write that fails fails closed: the caller
    refuses to deliver an unmarked file."""
    try:
        f.chmod(f.stat().st_mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    except OSError:
        pass
    if not shutil.which("xattr"):
        return True
    # ALWAYS written, never kept: cp keeps xattrs, so a hostile sandbox can preset
    # a mark Gatekeeper reads as "already approved by the user"
    value = f"0083;{int(time.time()):x};sandbox-exchange;"
    return subprocess.run(["xattr", "-w", "com.apple.quarantine", value, str(f)], capture_output=True).returncode == 0


def tagged(f: Path) -> bool:
    """f carries Gatekeeper's mark, written again if it lost it; True where
    there's no Gatekeeper to tell (no xattr: not a Mac)."""
    if not shutil.which("xattr"):
        return True
    has = subprocess.run(["xattr", "-p", "com.apple.quarantine", str(f)], capture_output=True).returncode == 0
    return has or tag(f)


def taken(p: Path) -> bool:
    return p.exists() or p.is_symlink()   # a dangling link fails exists(), and reusing its name would overwrite evidence


def dedupe(d: Path, base: str) -> str:
    """A name in d nothing has yet: base, else stem-1.ext, stem-2.ext, …"""
    if not taken(d / base):
        return base
    stem, ext = (base.rsplit(".", 1)[0], "." + base.rsplit(".", 1)[1]) if "." in base and not base.startswith(".") else (base, "")
    i = 1
    while taken(d / f"{stem}-{i}{ext}"):
        i += 1
    return f"{stem}-{i}{ext}"


def place(src: Path, d: Path, base: str) -> Path | None:
    """Publish src into d under base (or a free name), atomically and never over
    another file: two at once deduping onto the same free name must not clobber
    each other. A hard link fails on an existing name (then a new one is tried);
    across filesystems a full copy is staged in d first, so no one ever sees a
    partial file, and moved in with mv -n, checked by the copy having moved."""
    part = None
    for _ in range(100):
        dest = d / dedupe(d, base)
        if part is None:
            try:
                os.link(src, dest)
                src.unlink(missing_ok=True)
                return dest
            except FileExistsError:
                continue
            except OSError:
                pass
            try:
                fd, name = tempfile.mkstemp(prefix=".part.", dir=d)
                os.close(fd)
                part = Path(name)
                # cp, not shutil.copyfile: on a Mac it keeps the file's extended
                # attributes, Gatekeeper's mark among them; copyfile copies only the bytes
                if subprocess.run(["cp", "--", str(src), str(part)], capture_output=True).returncode != 0:
                    raise OSError("cp failed")
            except OSError:
                if part:
                    part.unlink(missing_ok=True)
                return None
        subprocess.run(["mv", "-n", "--", str(part), str(dest)], capture_output=True)
        if not taken(part):
            src.unlink(missing_ok=True)
            return dest
    if part:
        part.unlink(missing_ok=True)
    return None


def quarantine(p: Path, name: str, reason: str) -> bool:
    """Move p out of the sandbox's reach into .quarantine/<name>/, then de-exec it:
    moved first, so a chmod can't be raced onto whatever a symlink points at. mv -n,
    checked by p having moved, so two at once never overwrite each other's
    evidence."""
    qd = folders.exchange() / ".quarantine" / name
    qd.mkdir(parents=True, exist_ok=True)
    dest = None
    for _ in range(100):
        dest = qd / dedupe(qd, p.name)
        subprocess.run(["mv", "-n", "--", str(p), str(dest)], capture_output=True)
        if not taken(p):
            break
    else:
        log.warn(f"  {log.WARNING} couldn't quarantine {shown(p.name)} — left in place", err=True)
        return False
    log.file("quarantined", shown(str(dest)))
    if not dest.is_symlink():
        subprocess.run(["chmod", "-R", "a-x", str(dest)], capture_output=True)
    # the exchange caught something: it must not read like any other line
    log.warn(f"  {log.WARNING} quarantined {name}/{shown(p.name)}: {reason}")
    log.aside(f"→ {shown(log.path(dest))}", under="  ⚠ ")
    return True
