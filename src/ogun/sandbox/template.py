"""og template: recipes in og's config folder (templates/) and their images
(docs/templates.md): a build, ls and rm. A create (create.py) reads recipes
the same way."""

import fcntl
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from ogun.core import boxes, config, log, sbx
from ogun.net import baseline, ruletable
from ogun.sandbox import appa, base

NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")   # kept in step with the shell completion's _og_template_name_ok (shared-values.test.sh)

TEMPLATE_USAGE = "[<name> | ls [--json] | rm <name>]"
TEMPLATE_HELP = dict(
    about="The images new sandboxes start from: one per recipe in og's config folder (templates/), so a sandbox "
          "starts with its tools installed instead of installing them each time.",
    forms=[
        ("og template ls", "every recipe, its image, and whether it's built"),
        ("og template <name>", "build that recipe into its image, ogun-<name>"),
        ("og template", "build every recipe"),
        ("og template ls --json", "the same list as JSON"),
        ("og template rm <name>", "remove that recipe's image; og template <name> builds it again"),
    ],
    notes=["A new sandbox takes its repo's template (registry.json), else this Mac's og profile's, else sbx's own image."],
    examples=["og template ls", "og template home", "og template rm work"],
)


def usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("template", TEMPLATE_USAGE, problem=problem, err=err, **TEMPLATE_HELP)


def recipes_dir() -> Path:
    return config.file("templates")


def recipes() -> list[str]:
    return sorted(f.stem for f in recipes_dir().glob("*.sh") if f.is_file() and NAME_RE.fullmatch(f.stem))


def image(name: str) -> str:
    return f"ogun-{name}"


def machine() -> str:
    """This Mac's profile (config.label), whose recipe new sandboxes take by
    default; "" with none (or a name no recipe could have)."""
    m = config.label()
    return m if NAME_RE.fullmatch(m) else ""


def built(img: str, listing: str) -> bool:
    """Whether that image is a template here: docker.io/library/<img>:latest in
    one column, or <img> beside a tag."""
    return re.search(rf"(^|[/\s]){re.escape(img)}(:latest)?(\s|$)", listing, re.M) is not None


def created(img: str, listing: str) -> str:
    """Its CREATED column: columns are two or more spaces apart."""
    lines = listing.splitlines()
    if not lines:
        return ""
    head = [h.strip() for h in re.split(r"  +", lines[0])]
    c = next((i for i, h in enumerate(head) if "CREATED" in h.upper()), None)
    for line in lines[1:]:
        f = [x.strip() for x in re.split(r"  +", line)]
        if any(re.fullmatch(rf"(.*/)?{re.escape(img)}(:latest)?", x) for x in f):
            return f[c] if c is not None and c < len(f) else "?"
    return ""


def header(recipe: Path, key: str) -> list[str]:
    """The values of every `# <key>:` line in the recipe's leading comment block
    (after any #! line, blank lines skipped), commas or spaces apart."""
    out = []
    try:
        text = recipe.read_text()
    except OSError:
        return out
    for n, line in enumerate(text.splitlines()):
        if n == 0 and line.startswith("#!"):
            continue
        if not line.strip():
            continue
        if not line.startswith("#"):
            break
        body = re.sub(r"^#\s*", "", line)
        if body.startswith(key + ":"):
            out += [v for v in re.split(r"\s+", body[len(key) + 1:].replace(",", " ")) if v]
    return out


def _listing() -> str | None:
    p = sbx.run("template", "ls", wait="reading sbx's templates")
    return p.stdout if p.returncode == 0 else None


def as_json() -> dict:
    """og template ls --json: this Mac's profile, every recipe with
    its image, built or not, when, the egress its headers declare (what its build
    may reach, and what each sandbox made from it may). A listing sbx failed to
    give leaves built unknown (null), never false."""
    listing = _listing()
    ok = listing is not None

    def state(img):
        return built(img, listing) if ok else None

    rows = []
    for n in recipes():
        img, b = image(n), state(image(n))
        r = recipes_dir() / f"{n}.sh"
        rows.append({"name": n, "image": f"{img}:latest", "built": b, "created": created(img, listing) if b else "",
                     "egress": header(r, "egress"), "runtime_egress": header(r, "runtime-egress")})
    return {"profile": machine(), "listing_ok": ok, "recipes": rows}


def ls(args: list[str]) -> int:
    if args not in ([], ["--json"]):
        usage("og template ls takes nothing, or --json")
        return 1
    if args:
        print(json.dumps(as_json(), ensure_ascii=False))
        return 0
    listing = _listing()
    if listing is None:
        log.err("og template ls: sbx couldn't list its templates, so what's built is unknown")
        return 1
    rows, unbuilt = [], []
    for n in recipes():
        img = image(n)
        if built(img, listing):
            rows.append([n, f"{img}:latest", "yes", created(img, listing) or "?"])
        else:
            rows.append([n, f"{img}:latest", "no", "-"])
            unbuilt.append(n)
    foot = ("to build one: " + ", ".join(log.cmd(f"og template {n}") for n in unbuilt)) if unbuilt else ""
    boxes.columns(["RECIPE", "IMAGE", "BUILT", "CREATED"], rows, title="template", quiet=(1,), foot=foot)
    return 0


def rm(args: list[str]) -> int:
    """Nothing is lost that the recipe can't build again, so there's no question
    first."""
    if len(args) != 1:
        usage("og template rm takes one recipe name")
        return 1
    name = args[0]
    if not NAME_RE.fullmatch(name):
        log.err(f"og template rm: '{name}' isn't a recipe name (a-z, 0-9, -)")
        return 1
    listing = _listing()
    if listing is None:
        log.err("og template rm: sbx couldn't list its templates, so nothing was removed")
        return 1
    img = f"{image(name)}:latest"
    if not built(image(name), listing):
        log.info(f"{img} isn't built here: nothing to remove")
        return 0
    p = sbx.run("template", "rm", img, "-f", wait=f"removing {img}")
    if p.returncode != 0:
        log.err(f"og template rm: sbx couldn't remove {img}:")
        for line in ((p.stdout or "") + (p.stderr or "")).splitlines():
            if line.strip():
                log.note(line.strip(), err=True)
        return 1
    log.ok(f"removed {img}", f"to build it again: {log.cmd(f'og template {name}')}"
           if (recipes_dir() / f"{name}.sh").is_file() else "")
    log.record(f"removed the template {img}")
    return 0


# ── a build: each recipe in its own sandbox, golden-<name>: the common base (apt
# tools, the latest Claude Code), then the
# recipe, then the scrub, then the save, and nothing else: no host folder copied (those are live mounts), no secrets, no
# logins, no unlocked repos. Any failing step saves nothing (an image built
# before stays as it was) and the build sandbox is removed either way.

# what a build removes before the save, as the build sandbox's shell expands it
SCRUB = ["~/.aws/sso", "~/.claude/.credentials.json", "~/.bash_history", "~/.git-credentials", "~/.config/gh"]
DOMAIN_RE = re.compile(r"(\*\.)?[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?")
_SCRUB_RE = re.compile(r"~/[A-Za-z0-9._/-]+")


def build(args: list[str]) -> int:
    if len(args) > 1 or any(a.startswith("-") for a in args):
        usage("og template builds one recipe, or every recipe with no name")
        return 1
    if not recipes_dir().is_dir():
        config.missing("og template", "templates")
        return 1
    names = args or recipes()
    if not names:
        log.err(f"og template: there are no recipes in {log.path(recipes_dir())}")
        return 1
    plans = {}
    for n in names:   # every recipe read before anything is created or removed
        plans[n] = _plan(n)
        if plans[n] is None and args:
            return 1
    if not baseline.ssh_agent_off("template"):
        return 1
    failed = [n for n in names if plans[n] is None or not _build_one(n, *plans[n])]
    if failed and not args:
        log.err(f"og template: {', '.join(failed)} failed; built {len(names) - len(failed)} of {len(names)}")
    return 1 if failed else 0


def _plan(name: str):
    """What the recipe's headers ask for, each value held to a plain shape, since
    it reaches a command line (policy, the scrub): (recipe, egress, scrub, appa
    on), or None with why said."""
    if not NAME_RE.fullmatch(name):
        log.err(f"og template: '{log.shown(name)}' isn't a recipe name (a-z, 0-9, -)")
        return None
    recipe = recipes_dir() / f"{name}.sh"
    if not recipe.is_file():
        log.err(f"og template: there's no recipe {log.path(recipe)}; "
                + (f"recipes: {', '.join(recipes())}" if recipes() else "there are no recipes yet"))
        return None
    egress = header(recipe, "egress")
    for d in egress + header(recipe, "runtime-egress"):
        if not DOMAIN_RE.fullmatch(d):
            log.err(f"og template: {name}.sh declares egress '{log.shown(d)}', which isn't a domain")
            return None
    a = " ".join(header(recipe, "appa"))
    if a not in ("", "on"):
        log.err(f"og template: {name}.sh declares appa '{log.shown(a)}' — the only value is on")
        return None
    scrub = list(SCRUB)
    for d in header(recipe, "scrub"):
        if not _SCRUB_RE.fullmatch(d) or "/../" in f"/{d}/":
            log.err(f"og template: {name}.sh declares scrub '{log.shown(d)}', which must be ~/<path>")
            return None
        scrub.append(d)
    return recipe, egress, scrub, a == "on"


def _build_one(name: str, recipe: Path, egress: list[str], scrub: list[str], appa_on: bool) -> bool:
    """One build per recipe at a time, across processes (two terminals): both
    would share golden-<name>, and each one's forced rm would take the other's
    live build sandbox. A kernel lock beside the workspace, not in it; Python
    opens it close-on-exec, so no sbx call inherits it, and it goes with this
    process however the build ends."""
    state = Path.home() / ".local" / "state"
    state.mkdir(parents=True, exist_ok=True)
    with open(state / f"sbx-golden-{name}.lock", "a") as held:
        try:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log.err(f"og template: a build of '{name}' is already running; wait for it to finish")
            return False
        return _build_locked(name, recipe, egress, scrub, appa_on, state / f"sbx-golden-{name}")


def _owns(sb: str, g: Path, listing: str | None) -> bool:
    """The sandbox exists and is a build's: its listed workspace is g, compared
    resolved (a symlinked HOME, a doubled slash), since sbx may list either."""
    ws = sbx.workspace(sb, listing or "")
    return bool(ws) and os.path.realpath(ws) == os.path.realpath(g)


def _build_locked(name: str, recipe: Path, egress: list[str], scrub: list[str], appa_on: bool, g: Path) -> bool:
    sb, img = f"golden-{name}", image(name)
    baseline.baseline_lists()   # a [baseline] og can't read stops here, before anything is made
    # golden-<name> is only ever this build's own throwaway: nothing in it is
    # worth a prompt, so each sbx call runs with no stdin, and rm takes --force,
    # since sbx refuses its y/N outright without a terminal. A leftover goes
    # before the workspace exists, so a failure leaves nothing.
    listing = sbx.ls()
    if listing is None:
        log.err(f"og template: sbx couldn't list its sandboxes, so a leftover {sb} can't be checked; nothing was built")
        return False
    if sb in sbx.names(listing):
        # a leftover only if it is a build's: a sandbox someone named
        # golden-<name> by hand is theirs, and a forced rm would take its
        # sessions and unpushed work with it
        if not _owns(sb, g, listing):
            log.err(f"og template: a sandbox named {sb} exists, and it isn't a build's (its workspace: "
                    f"{log.shown(sbx.workspace(sb, listing))}). {sb} is the build's own name; rename or remove that sandbox yourself")
            return False
        log.step(f"removing {sb}, left over from an earlier build")
        p = sbx.run("rm", sb, "--force", wait=f"removing {sb}")
        if p.returncode:
            log.err(f"og template: couldn't remove the old {sb}; to remove it, run:", fix=log.cmd(f"og rm {sb} --force"))
            sbx.said(p)
            return False
    shutil.rmtree(g, ignore_errors=True)
    g.mkdir(parents=True)
    subprocess.run(["git", "-C", str(g), "init", "-q"], check=False)
    (g / ".sbxenv.yaml").write_text(f'schemaVersion: "1"\nname: {sb}\nagent: claude\nworkspace:\n  path: {g}\n  clone: true\n')
    log.step(f"template '{name}': build sandbox {sb}")
    # the file, not the directory, and --force: no plan prompt
    p = sbx.run("env", "create", str(g / ".sbxenv.yaml"), "--force", wait=f"creating {sb}")
    try:
        done = p.returncode == 0 and _steps(sb, name, recipe, egress, scrub, img, appa_on)
        if p.returncode:
            sbx.said(p)
    finally:   # an error in a step (a config file og can't read) still removes the build
        # a create that failed half-way may still have left the sandbox. Only ours
        # goes: one made by hand between the check above and this create took the
        # name (so the create failed), and it is someone else's
        if _owns(sb, g, sbx.ls()):
            sbx.run("rm", sb, "--force", wait=f"removing {sb}")
        shutil.rmtree(g, ignore_errors=True)
    if not done:
        log.err(f"og template: '{name}' failed — nothing saved (an earlier {img}:latest, if any, is unchanged)")
        return False
    log.ok(f"built {img}:latest", "new sandboxes take it by their repo's entry or this Mac's og profile")
    log.record(f"built the template {img}:latest")
    return True


def _steps(sb: str, name: str, recipe: Path, egress: list[str], scrub: list[str], img: str, appa_on: bool) -> bool:
    log.step("network baseline")
    if not baseline.baseline():
        return False
    if egress:
        doms = ",".join(egress)
        # this build sandbox only: the `sbx rm` at the end of the build drops it
        log.step(f"egress the recipe declares ({sb} only): {doms}")
        if not ruletable.allow_twice("policy", "allow", "network", "--sandbox", sb, doms):
            return False
    log.step("tools")
    if not (base.apt_wait(sb) and base.tools(sb)):
        return False
    base.claude_update(sb)   # the template carries this version; a stale one makes every new sandbox start old
    # the recipe goes in as a file, not as the shell's stdin: a command in it
    # that reads stdin would otherwise swallow the rest of the recipe. It runs
    # with its output on the terminal: your own code, worth watching
    log.step(f"recipe {log.path(recipe)}")
    p = sbx.run("exec", "-i", sb, "bash", "-c", "cat > /tmp/ogun-recipe.sh", input=recipe.read_bytes(), wait="sending the recipe")
    if p.returncode:
        sbx.said(p)
        return False
    p = sbx.run("exec", sb, "bash", "-lc", "bash -euo pipefail /tmp/ogun-recipe.sh", show=True)
    if p.returncode:
        log.note(f"the recipe stopped with exit {p.returncode}", err=True)
        return False
    if appa_on and not appa.install(sb, "template"):   # `# appa: on`: the image carries the pinned OpenAPPA
        return False
    # tilde paths, unquoted on purpose (their shape is checked in _plan): the
    # sandbox's shell expands them, and every one must be gone before the save
    s = " ".join(scrub)
    log.step(f"scrub (nothing secret may be in a snapshot): {s}")
    p = sbx.run("exec", sb, "bash", "-lc", f'rm -rf /tmp/ogun-recipe.sh {s}; for p in {s}; do [ ! -e "$p" ] || '
                '{ echo "still there: $p" >&2; exit 1; }; done', wait="scrubbing")
    if p.returncode:
        sbx.said(p)
        return False
    for what, call in ((f"stop {sb}", ("stop", sb)), (f"save template {img}", ("template", "save", sb, img))):
        log.step(what)   # sbx saves only a stopped sandbox
        p = sbx.run(*call, wait=what)
        if p.returncode:
            sbx.said(p)
            return False
    return True


def template(args: list[str]) -> int:
    if args[:1] == ["ls"]:
        return ls(args[1:])
    if args[:1] == ["rm"]:
        return rm(args[1:])
    return build(args)
