#!/usr/bin/env python3
"""policy.py <appa.toml> <workspace> [--private <host/path>]... [<read-only mount>...] — Ogun's block in
OpenAPPA's root policy, run inside a sandbox by activate.sh (docs/appa.md).

The block goes between two marker lines at the end of the file, and a rerun
replaces it, so the rest of the file stays OpenAPPA's own. Root rules come
before every battery's, and a root annotator replaces a battery's of the same
name, so the block can:

- say who `self` is: the GitHub account of the sandbox's token;
- make reading the workspace, or a read-only mount, narrow the session to
  `self`, for Read and Grep by path;
- tell the shell classifier the same, for commands and relative paths;
- tell the push classifier that a push to the workspace's own `origin` is for
  `self`, so pushing your own work doesn't ask. Its battery hint is kept, read
  from the installed battery, so a new OpenAPPA version's wording carries over.
  A GitHub origin gets this only when GitHub says it is private: a public one
  would take what the session read from a private mount without a question.
  Each `--private` place (the repo's registry entry, off GitHub) gets the same.
"""
import json
import os
import subprocess
import sys
import tomllib

# the marker that finds og's block in a policy
BEGIN = "# >>> ogun: written at create by og's appa/policy.py; rewritten, never edited"
END = "# <<< ogun"
HINT_MAX = 512   # OpenAPPA refuses a longer annotator hint
# the push rules of OpenAPPA's own hint, in fewer words, for when its hint and
# Ogun's sentence together run over HINT_MAX
REPO_RULES = ("`context.github` is the deployment's finding about the repository the command reaches. A push, "
              "pull request, issue, release or comment into a public repository, or one it doesn't establish, "
              "requires audience public; into a private or internal one, internal. A read keeps the session's audience.")
REPO_ANNOTATOR = "claude-code.bash-repository-requirements"
SHELL_ANNOTATOR = "claude-code.bash-requirements"


def q(s):
    """A TOML basic string: JSON's escaping is valid TOML for these values."""
    return json.dumps(s, ensure_ascii=False)


def battery_hint(conf_dir, name):
    try:
        with open(os.path.join(conf_dir, "batteries", "coding", "appa.toml"), "rb") as f:
            doc = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    for a in doc.get("policy", {}).get("annotator", []):
        if a.get("name") == name:
            return a.get("hint", "")
    return ""


def run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def origin(ws):
    """(the origin as the hint names it, its GitHub owner/repo or "")"""
    url = run("git", "-C", ws, "remote", "get-url", "origin")
    for p in ("https://github.com/", "git@github.com:", "ssh://git@github.com/"):
        if url.startswith(p):
            slug = url[len(p):].removesuffix(".git").rstrip("/")
            return "github.com/" + slug, slug
    return url, ""


def github_private(slug):
    """GitHub's answer, with the sandbox's token; anything but `true` is no"""
    return run("gh", "api", f"repos/{slug}", "--jq", ".private") == "true"


def block(conf_dir, ws, mounts, has_audience, places=()):
    paths = [ws] + [m for m in mounts if m and m != ws]
    out = [BEGIN]
    if not has_audience:
        out += ["[policy.audience]", 'self = ["github:viewer"]', ""]
    for p in paths:
        p = p.rstrip("/")
        out += ["[[policy.tool]]", f"name = {q(f'tool/coding/read_file(file_path:{p}/*)')}",
                'delta = { audience = ["self"] }', "",
                "[[policy.tool]]", f"name = {q(f'tool/coding/search_files(path:{p}*)')}",
                'delta = { audience = ["self"] }', ""]
    def shell_hint(where):
        return (f"Files under {where} are this sandbox's own and private: reading them, by full path or by a "
                f"relative path when the working directory is under one of them, is audience self. "
                f"When a command's readers can't be determined, assume public.")
    shell = shell_hint(", ".join(paths))
    if len(shell) > HINT_MAX:   # many or long mounts: the workspace by name, the mounts by the read rules
        shell = shell_hint(f"{ws} and the other folders this policy's read rules name")
    if len(shell) > HINT_MAX:
        raise SystemExit(f"the workspace path is too long for a {HINT_MAX}-character hint: {ws}")
    out += ["[[policy.annotator]]", f"name = {q(SHELL_ANNOTATOR)}", 'builtin = "claude-code"', f"hint = {q(shell)}", ""]
    # off GitHub there is no one to ask: every origin is taken as private, a public one included
    o, slug = origin(ws)
    into = [f"this sandbox's own origin, {o}"] if o and (not slug or github_private(slug)) else []
    if places:
        into.append(", ".join(places) + " (private to self)")
    if into:
        own = f"Except: a `git push` into {' or into '.join(into)}, requires audience self."
        repo = battery_hint(conf_dir, REPO_ANNOTATOR)
        hint = f"{repo} {own}" if repo and len(repo) + 1 + len(own) <= HINT_MAX else f"{REPO_RULES} {own}"
        if len(hint) > HINT_MAX:
            raise SystemExit(f"the origin URL and private places are too long for a {HINT_MAX}-character hint: {o} {' '.join(places)}")
        out += ["[[policy.annotator]]", f"name = {q(REPO_ANNOTATOR)}", 'builtin = "claude-code"', f"hint = {q(hint)}", ""]
    out.append(END)
    return "\n".join(out) + "\n"


def main():
    path, ws, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
    places, mounts = [], []
    while rest:
        if rest[0] == "--private" and len(rest) > 1:
            places.append(rest[1])
            rest = rest[2:]
        else:
            mounts.append(rest.pop(0))
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if BEGIN in text:
        head, rest = text.split(BEGIN, 1)
        text = head.rstrip("\n") + "\n" + (rest.split(END, 1)[1].lstrip("\n") if END in rest else "")
    has_audience = "audience" in tomllib.loads(text).get("policy", {})   # a table, not the text in a comment
    new = text.rstrip("\n") + "\n\n" + block(os.path.dirname(path), ws, mounts, has_audience, places)
    tomllib.loads(new)   # a block that breaks the file is never written
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
    os.replace(tmp, path)


if __name__ == "__main__":
    main()
