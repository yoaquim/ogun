"""Each sandbox's GitHub pushes: the repos its workspace may push to, as one rule each
on that repo's receive-pack path."""

import re
import subprocess

from ogun.core import log, registry, sbx

# ── GitHub pushes: every sandbox reads GitHub (the baseline); each pushes only to its own repos ──

SLUG = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")


def _git(d: str, *args: str) -> list[str]:
    p = subprocess.run(["git", "-C", d, *args], capture_output=True, text=True)
    return p.stdout.splitlines() if p.returncode == 0 else []


def _slug(url: str) -> str | None:
    for prefix in ("https://github.com/", "git@github.com:", "ssh://git@github.com/"):
        if url.startswith(prefix):
            s = url[len(prefix):].removesuffix("/").removesuffix(".git")
            return s if SLUG.fullmatch(s) else None   # no glob characters reach a rule
    return None


def push_repos(d: str) -> list[str]:
    """The GitHub repos a sandbox for <d> may push to, owner/repo: every GitHub
    remote of the Mac's checkout and of each registry `write` repo's, and each
    `push` address. Read on the Mac, never in the sandbox: its workspace is a
    private clone, and the write repos are mounted read-only, so nothing in the
    sandbox can add a repo here. No directory, no repos: git would read an
    empty -C as the folder og was run from, and hand its remotes to the sandbox."""
    if not d:
        return []
    urls = []
    for x in [d, *registry.related(d, "write", quiet=True)]:
        for r in _git(x, "remote"):
            urls += _git(x, "config", "--get-all", f"remote.{r}.url")
            urls += _git(x, "config", "--get-all", f"remote.{r}.pushurl")
    urls += registry.related(d, "push")
    return sorted({s for s in map(_slug, urls) if s})


def push_allow(sb: str, slug: str) -> bool:
    """A push (POST …/git-receive-pack, with and without .git) to one repo, for one sandbox."""
    good = True
    for path in (f"/{slug}.git/git-receive-pack", f"/{slug}/git-receive-pack"):
        if sbx.run("policy", "allow", "network", "--sandbox", sb, "github.com", "--method", "POST", "--path", path).returncode:
            good = False
    return good


def push_rules(sb: str, d: str, say: bool = True, quiet: bool = False) -> bool:
    """This sandbox's pushes to its own repos: each repo printed bare (say), else
    one note naming them (og policy), or nothing but a failure (quiet: every attach)."""
    slugs, failed = push_repos(d), []
    for slug in slugs:
        if not push_allow(sb, slug):
            failed.append(slug)
        if say:
            print(slug, flush=True)
    if not say:   # a failed push is never named as allowed
        if (done := [x for x in slugs if x not in failed]) and not quiet:
            log.note(f"{sb} may push to {', '.join(done)}")
        if failed:
            log.warn(f"  {log.WARNING} couldn't allow {sb} to push to {', '.join(failed)}", err=True)
    return not failed
