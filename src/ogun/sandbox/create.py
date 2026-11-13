"""A new sandbox (docs/sandboxes.md, docs/templates.md): the checks
before anything is made, which template it starts from and why, the plugin
marketplaces and other folders it mounts, its .sbxenv.yaml (envfile.py), `sbx env create`,
the runtime egress its template asks for, the record og keeps of all of it, and
the setup after. A folder that isn't a repo yet is offered one first
(init.py). The bare og (bare.py) calls create()."""

import os
import re
import subprocess
from pathlib import Path

from ogun.core import boxes, config, log, naming, sbx, settings
from ogun.net import baseline, egress, pushrules
from ogun.sandbox import appa, choose, envfile, facts, init, template

# ── the create itself ──

# sbx signed out of Docker (a new Mac, an expired login) fails a create halfway,
# after the plan prints, with "401 Unauthorized: user is not authenticated to
# Docker … not signed in" and a `sbx env rm` hint that does not apply; signed out,
# `sbx template ls` also reads empty, so a built template looks missing. So a
# create asks first. Only that sbx answer stops it: sbx down or any other
# failure is left to the steps that already report it.
SIGNED_OUT_RE = re.compile(r"not signed in|not authenticated|401 Unauthorized", re.I)


def _signed_out_hint() -> None:
    log.err("og: sbx is not signed in to Docker on this Mac; sign in, then retry:", fix=log.cmd("sbx login"))


def signed_in() -> bool:
    p = sbx.run("ls")
    if p.returncode == 0 or not SIGNED_OUT_RE.search((p.stdout or "") + (p.stderr or "")):
        return True
    _signed_out_hint()
    return False


def skills_store() -> Path:
    """sbx's shared skills store, which every sandbox mounts."""
    return Path.home() / "Library/Application Support/com.docker.sandboxes/sandboxes/agent-skills"


def skills_dir() -> str:
    """skills_dir, the folder mirrored into sbx's skills store ("" unset)."""
    v = settings.get("skills_dir")
    return str(Path(v).expanduser()) if v else ""


def skills() -> bool:
    """The skills folder (skills_dir) mirrored into the shared store every
    sandbox mounts; unset, none, said once. The store is ALWAYS left read-only:
    sandboxes mount it rw, and read-only file modes are the only thing stopping
    one sandbox from planting a skill for the rest. This mirror is the sole
    writer; it unlocks, syncs, and relocks."""
    src = skills_dir()
    if not src:
        config.once("skills", "no skills folder (skills_dir): none mirrored into sbx's skills store")
        return True
    if not os.path.isdir(src):
        log.err(f"og: the skills folder (skills_dir) {log.path(src)} isn't a folder")
        return False
    store = skills_store()
    if store.is_dir():
        subprocess.run(["chmod", "-R", "u+w", str(store)], stderr=subprocess.DEVNULL)
    try:
        store.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.err(f"og: couldn't make the skills store at {log.path(store)}")
        return False
    # --copy-unsafe-links: a skill linked in from elsewhere arrives as its files, never a
    # link to a Mac path no sandbox has
    if (subprocess.run(["rsync", "-a", "--copy-unsafe-links", "--delete", f"{src}/", f"{store}/"]).returncode
            or subprocess.run(["chmod", "-R", "a-w", str(store)]).returncode):
        log.err(f"og: couldn't mirror {log.path(src)} into sbx's skills store (above)")
        return False
    n = sum(1 for x in store.iterdir() if x.is_dir() and not x.is_symlink())
    log.step(f"skills store: {n} skills")
    return True


def fail_removed(name: str) -> None:
    from ogun.sandbox import remove
    if not remove.rm_clean(name, True):
        log.warn(f"  {log.WARNING} could not remove '{name}'; do it now:", fix=log.cmd(f"og rm {name} --force"))


def name_refused(name: str) -> bool:
    """A name og won't make a sandbox under, said with why."""
    from ogun.exchange import folders
    if not naming.name_ok(name):
        log.err(f"og: invalid sandbox name '{log.shown(name)}' — it must start with a letter or digit, then letters, "
                "digits, . _ -, at most 61 characters: it names exchange folders (a leading dot would hide them from "
                "og scan), a hostname and an ssh alias")
        return True
    if naming.reserved(name):
        log.err(f"og: '{name}' is a reserved exchange name (see docs/exchange.md); pick another with --name")
        return True
    # golden-<recipe> is a template build's own sandbox, and a build removes a
    # leftover one with sbx rm --force: og never makes one, in any case (the
    # Mac folds it). Only a recipe's name: a repo called golden-gate is not one
    for r in template.recipes():
        if name.lower() == f"golden-{r}":
            log.err(f"og: '{name}' — golden-{r} is the template build's own sandbox (og template {r}), which removes "
                    "a leftover one; pick another with --name")
            return True
    conflict = folders.case_conflict(name)
    if conflict:
        log.err(f"og: '{name}' case-folds to the existing exchange dir '{conflict}' — on this filesystem they would "
                "share directories; pick another name with --name")
        return True
    return False


def _listed(title: str, xs: list[str]) -> None:
    if xs:
        log.step(title)
        for x in xs:
            log.note(x)


def recipe_appa(decision: dict) -> tuple[int, str]:
    """template_appa of the chosen template's recipe; (1, "") with no such recipe."""
    tn = decision.get("name") or ""
    if tn and template.NAME_RE.fullmatch(tn) and (template.recipes_dir() / f"{tn}.sh").is_file():
        return template_appa(template.recipes_dir() / f"{tn}.sh")
    return 1, ""


def env_create(name: str, env: Path) -> bool:
    # the FILE is named, not its directory: sbx resolves a directory only to
    # `sbxenv.yaml` but reads a named file by any name, so the hidden, git-excluded
    # file stays. --force (v0.49's name for --auto-approve): sbx asks [y/N] over an
    # "environment plan" that is this file, which og just wrote from its own rules,
    # so it is approved; sbx's output shows only on failure (or at -vv). The flag
    # follows the path, as sbx's synopsis has it: `create [PATH...] [flags]`
    p = sbx.run("env", "create", str(env), "--force", wait=f"creating '{name}'")
    if p.returncode:
        # a sign-in that lapsed since signed_in() gets the same hint, not sbx's `sbx env rm`
        if SIGNED_OUT_RE.search((p.stdout or "") + (p.stderr or "")):
            _signed_out_hint()
        else:
            log.err(f"og: sbx couldn't create '{name}':")
            sbx.said(p)
        return False
    sbx.remember_one(name)   # tab completion offers it now, attached or not (--no-attach)
    return True


def allow_runtime_egress(name: str, decision: dict) -> list[str]:
    """What its template needs at runtime (`# runtime-egress:`), for this sandbox
    alone — `sbx rm` drops a sandbox's own rules, so nothing is left to clean.
    What was allowed: none when sbx refused."""
    regress = choose.runtime_egress(decision)
    if regress:
        joined = ",".join(regress)
        log.step(f"runtime egress of its template ({name} only): {joined}")
        if sbx.run("policy", "allow", "network", "--sandbox", name, joined).returncode:
            log.warn(f"  {log.WARNING} could not allow it; by hand:", fix=log.cmd(f"og allow {name} {' '.join(regress)}"))
            return []
    return regress


def turn_on_appa(name: str, org: str, item: str, d: str, rel: list[str]) -> bool:
    """Fails closed: a sandbox that asked for OpenAPPA and didn't get it is removed,
    never left looking as if it had it. Its token comes first: the policy asks
    GitHub whether the origin is private (og's appa/policy.py)."""
    from ogun.secrets import github
    if not (github.set_token(name, org, item) and appa.install(name)):
        fail_removed(name)
        return False
    if not appa.activate(name, d, rel):
        log.err(f"og: OpenAPPA couldn't be turned on in '{name}' (above) — removing it")
        fail_removed(name)
        return False
    if not facts.record_appa(name):
        log.warn(f"  {log.WARNING} OpenAPPA is on, but the sandbox's record doesn't say so: its attach starts plain claude")
    return True


def create(name: str, org: str, d: str, kind: str = "session", item: str = "", appa_on: bool = False) -> bool:
    """.sbxenv.yaml, `sbx env create`, its record, setup, and its token. Every
    refusal comes before anything is made."""
    from ogun import mcp
    from ogun.core import registry
    from ogun.exchange import folders
    from ogun.secrets import approval, github, sshkeys
    # the name, sign-in and ssh-agent refusals come before anything is reserved,
    # and so does the check of the ssh-keys folder every sandbox will mount
    if name_refused(name) or not signed_in() or not baseline.ssh_agent_off(name) or not sshkeys.keys_check():
        return False
    # the token step comes last, and an item it can't name would leave the sandbox
    # made and set up but without a token: refuse while nothing is made
    if not item and not github.token_name():
        log.err("og: no profile and no token_name, so og can't name this Mac's GitHub token items; nothing was made. "
                "Choose a profile (OG_PROFILE, or ~/.config/ogun/profile) or set token_name (docs/appendix/flags-and-env.md)")
        return False
    baseline.baseline_lists()   # a [baseline] og can't read stops here, not with the sandbox half set up
    # secret grants: asked about before anything exists, so a "no" leaves no half-made sandbox
    given = approval.approved(d)
    sshkd = sshkeys.keys_dir()
    # always regenerated at creation: the file is local, deterministic, and the
    # related mounts / MCP set may have changed since it was last written
    rel = [x for x in registry.related(d) if x]
    _listed("related, mounted read-only:", rel)
    _listed("MCP servers (register with 'sbx mcp add' first):", mcp.servers(d))
    mkt, links = mount_plan(d, rel, sshkd)
    img, decision = choose.choose_template(d)
    rc, v = recipe_appa(decision)
    if rc == 2:
        log.err(f"og: template '{decision.get('name')}' declares appa '{log.shown(v)}' — the only value is on")
        return False
    appa_on = appa_on or rc == 0
    # a failed reservation (case-fold conflict won by a concurrent create, or a
    # lock timeout) must abort creation, not mount someone else's directories
    why = folders.dirs(name)
    if why:
        log.err(f"og: couldn't make the folders for '{name}': {why}; pick another name with --name")
        return False
    box = folders.box(name)
    if box is None:
        log.err(f"og: no exchange box for '{name}' after reservation")
        return False
    yaml = envfile.env_yaml(name, d, box, rel, mkt, sshkd, img)
    env = envfile.write_env(d, yaml)
    if env is None or not skills():
        return False
    log.step(f"create sandbox '{name}' ({org}, {kind})")
    if not env_create(name, env):
        return False
    # what was decided for it — template, mounts as this create wrote them (another
    # create from the same workspace may write over the file meanwhile), runtime
    # egress; a record that could not be written is warned, never fatal
    facts.record(name, kind, d, decision, yaml, allow_runtime_egress(name, decision), links)
    return finish(name, org, item, d, rel, given, appa_on)


def mount_plan(d: str, rel: list[str], sshkd: str) -> tuple[list[str], list[tuple[str, str]]]:
    """The plugin marketplaces to mount (real paths, read-only, none another rule already
    mounts: the workspace, a related checkout), and each mount reached through a link
    as (link, real path), which setup makes inside. A link in a mounted folder whose
    target no mount covers is said, never mounted."""
    from ogun.exchange import folders
    named = [x for x in choose.marketplaces(d) if x]
    mkt = [x for x in dict.fromkeys(init.real_path(m) for m in named) if x not in (d, init.real_path(d)) and x not in rel]
    _listed("plugin marketplaces, mounted read-only:", mkt)
    hosts = envfile.host_mounts(d, rel)
    # every link whose target some mount covers, the workspace and related checkouts
    # included: a mount skipped as already mounted still needs its own name inside
    covered = [*mkt, *(r for _, r in hosts), d, init.real_path(d), *rel]
    links = list(dict.fromkeys(p for p in [*(envfile.linked(a) for a, _ in envfile.host_named()),
                                           *(envfile.linked(m) for m in named)] if p and p[1] in covered))
    envfile.say_outside_links([r for _, r in hosts] + mkt,
                              [d, init.real_path(d), *rel, *(r for _, r in hosts), *mkt, sshkd,
                               init.real_path(str(folders.exchange()))])
    return mkt, links


def finish(name: str, org: str, item: str, d: str, rel: list[str], given: list, appa_on: bool) -> bool:
    """Everything after sbx made it: the agent's absence proved, its MCP servers,
    network baseline, setup, OpenAPPA, remotes, push rules, grants, egress, token."""
    from ogun import mcp
    from ogun.sandbox import base, session
    from ogun.secrets import github, grants, sshkeys
    # the saved setting passed before; the sandbox proves the daemon applied it.
    # One that still sees the agent is removed (its box with it) before
    # anything runs in it.
    if not sshkeys.agent_absent(name):
        fail_removed(name)
        return False
    mcp.refresh(name, d)
    log.step("network baseline")
    if not baseline.baseline():
        log.warn(f"  {log.WARNING} could not apply baseline policy")
    if not base.setup(name) or (appa_on and not turn_on_appa(name, org, item, d, rel)):
        return False
    log.step("remotes")
    session.https_remotes(name, d)
    if not pushrules.push_repos(d):
        log.step("GitHub pushes: none (no GitHub remote)")
    elif not pushrules.push_rules(name, d, say=False):
        log.warn(f"  {log.WARNING} could not allow every push rule; by hand:", fix=log.cmd("og policy"))
    if not grants.give(name, given):
        log.warn(f"  {log.WARNING} not every secret grant was applied (above)")
    if not egress.egress_sync(name, d):
        log.warn(f"  {log.WARNING} not every domain its registry entry lists was allowed (above)")
    if appa_on:
        return True
    if not github.set_token(name, org, item):
        return False
    appa_remind(name, d)
    return True


_GITHUB_ORIGIN = re.compile(r"(https://github\.com/|git@github\.com:)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")


def appa_remind(sb: str, ws: str) -> None:
    """One block when an unprotected sandbox's repo is a private GitHub one, asked
    from inside it (its token can read the repo). Silent when it can't tell: not
    GitHub, or no answer."""
    p = sbx.run("exec", sb, "git", "-C", ws, "remote", "get-url", "origin")
    m = _GITHUB_ORIGIN.fullmatch((p.stdout or "").rstrip("\n")) if p.returncode == 0 else None
    if not m:
        return
    slug = m.group(2).removesuffix(".git")
    q = sbx.run("exec", sb, "gh", "api", f"repos/{slug}", "--jq", ".private")
    if (q.stdout or "").rstrip("\n") == "true":
        boxes.callout("NO OPENAPPA ON A PRIVATE REPO",
                    [f"{slug} is private, and '{sb}' runs without OpenAPPA: nothing stops its agent",
                     f"from copying it to a public repo. To protect it: og rm {sb}, then og --appa",
                     "(docs/appa.md)."])


def template_appa(recipe: Path) -> tuple[int, str]:
    """0 when the recipe's header says `appa: on`, 1 when it says nothing, 2 (and
    the value) when it says anything else."""
    v = " ".join(template.header(recipe, "appa"))
    return (1, "") if not v else (0, v) if v == "on" else (2, v)
