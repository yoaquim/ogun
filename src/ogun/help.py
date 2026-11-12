"""og's command table, and the two commands it serves directly: `og help` (the
list, or one command's usage) and `og ssh <name>`. One entry per command:
(arguments, what it does). The help page and `og help <cmd>` both read it here,
and the shell completion's copy is kept in
step with it (shared-values.test.sh), so a command's arguments are described once."""

import os
import sys

from ogun.core import log

COMMANDS = {
    'ls': ('[--json | <sbx ls args>]',
             'list sandboxes — sandbox, agent, status (any argument: raw sbx ls)'),
    'attach': ('<name>',
                 'attach to a sandbox that already exists'),
    'sh': ('<name> [<command> [<arg>...]]',
             'a login shell inside the sandbox, or one command run there'),
    'ports': ('<name> [[<mac port>:]<port>... | --rm <port>...]',
                "publish a sandbox's ports on this Mac's loopback, list them, or unpublish one"),
    'doctor': ('',
                 "how this Mac's sbx and og stand: sbx's own checks, then og's; only reads"),
    'stop': ('<name>... | --all',
               'stop sandboxes without removing them; attaching starts them again'),
    'ssh': ('<name>',
              'ssh in (after `sbx setup ssh`); <name>.sbx also mounts over SFTP'),
    'rm': ('<name> [--force | --if-clean]',
             'remove a sandbox and its folder in the exchange (--if-clean: only when no work or live session would be lost)'),
    'net': ('<name>|--all [--sbx | <domain>|github.com/<owner>/<repo>... [--read-only | --deny | --rm | --check]] | <name>|--all --log [-n <count>]',
              "a sandbox's network rules: list them (--sbx: with sbx's own), allow (the default), block (--deny), remove one (--rm), "
              "ask whether one is allowed (--check), or what it tried to reach (--log)"),
    'allow': ('<name> <domain>|github.com/<owner>/<repo>... [--read-only]  |  --all <domain>... [--read-only]',
                'allow egress to these domains for one sandbox (--all: every sandbox), or a push to that GitHub repo; --read-only: reading only'),
    'style': ('',
                "draw every pattern og's output uses: steps, notes, warnings, errors, a callout, a summary, a usage box (docs/appendix/ogun-style.md)"),
    'skills': ('',
                 "mirror your skills folder (skills_dir) into sbx's shared skills store, which every sandbox mounts, and lock it read-only"),
    'policy': ('',
                 "(re)apply this Mac's safety settings, for every sandbox: baseline egress allowlist, each sandbox's push rules "
                 "and registry egress, ssh-agent forwarding off, and the removal line for an allow covering all of github.com"),
    'log': ('[-n <count>] [--json]',
              'what og changed on this Mac, newest last: removals, allows, policy, the registry'),
    'pass': ('<name> <ENV_VAR> <host>...|--expose [--item <name>|--paste] [--vault <v>] [--field <f>]  |  <name> <ENV_VAR> --rm  |  <name>',
               'hand one secret to one sandbox: 1Password or pasted, proxy-swapped on <host> or exposed'),
    'token': ('[<owner>] [<days>]',
                "mint or rotate an owner's GitHub token for its sandboxes: GitHub's form pre-filled, 1Password, its expiry recorded"),
    'give': ('[<name>] <file>...  |  [<name>] --clip',
               'copy files into the exchange (a name targets that sandbox alone)'),
    'ship': ('<name> <patch> --remote <r> --branch <b> --base <sha> --commits <n> --tree <sha>',
               "from your clone: apply a sandbox's refused branch (a workflow change) in a throwaway worktree, page every commit, push on your y"),
    'take': ('<name> [<file>... | --all]',
               "list a sandbox's out/, or check and move files to ~/Downloads"),
    'scan': ('',
               'sweep shared/ — text only, quarantine violators, commit the history'),
    'tidy': ('[--rm]',
               'find what removed sandboxes left behind: folders in the exchange (--rm: remove them) and stored secrets'),
    'project': ('ls [--json] | add [<repo>] [--write]',
                  "the repo registry: what mounts into this repo's sandboxes"),
    'mcp': ('[ls [--json] | auth <server> | auth --all | load <name>]',
              'gateway MCP servers: login status; log in again and reload into the sandboxes using it; reload one sandbox. Every attach does both for its own servers'),
    'template': ('[<name> | ls [--json] | rm <name>]',
                   'build the recipe <name>.sh (templates/ in the config folder) into the template ogun-<name> (no name: every recipe); ls: recipes vs built images; rm: remove one'),
    'help': ('[<command>]',
               "this list, or one command's usage"),
}

FLAGS = """flags (a bare og, or with a name)
  --org <owner>        token owner, overriding the one its folder names
  --item <vault item>  the exact vault item to install; its name gives the owner
  --name <name>        sandbox name, overriding the directory's
  --sync               re-run setup and the skills mirror, and read the GitHub token from
                       1Password again, before attaching
  --rm                 remove the sandbox when you exit Claude
  --appa               protect a new sandbox's sessions with OpenAPPA (docs/appa.md);
                       a template can ask with `# appa: on`
  --no-attach          create without attaching

The read commands take --json (ls, project ls, mcp ls, template ls).
Full reference: docs/README.md, in og's folder. One command's usage: og <command> --help"""

HEAD = """og — one sandboxed Claude session per project (also: ogun)

usage: og [<name>] [--org <owner> | --item <vault item>] [--name <n>]
          [--sync] [--rm] [--appa] [--no-attach]
       og <command> [arguments]

A bare `og` creates or attaches the sandbox for the current repo; its GitHub
token owner is the one its project folder names. Exiting Claude only detaches —
the sandbox persists until `og rm`.
"""

GROUPS = [("sandboxes", ["ls", "attach", "sh", "ssh", "stop", "ports", "rm"]),
          ("network", ["net", "allow", "policy"]),
          ("files", ["give", "take", "ship", "scan", "tidy"]),
          ("secrets", ["pass", "token"]),
          ("setup", ["project", "mcp", "template", "skills", "doctor", "style", "log", "help"])]


def page() -> None:
    """Every command, grouped, and the bare og's flags. On stdout: asking for help
    is an answer, not an error."""
    print(HEAD)
    for title, cmds in GROUPS:
        print(title)
        for c in cmds:
            print(f"  {c:<13} {COMMANDS[c][1]}")
        print()
    print(FLAGS)


def line(cmd: str) -> str:
    args = COMMANDS[cmd][0]
    return f"usage: og {cmd}" + (f" {args}" if args else "")


def help_(argv: list[str]) -> int:
    """og help [<command>]: the page, or one command's usage (`og help -h` is the page)."""
    rest = argv[1:] if argv[:1] in (["-h"], ["--help"]) else argv
    if not rest:
        page()
        return 0
    if rest[0] not in COMMANDS:
        log.err(f"og: no such command '{log.shown(rest[0])}'; they're listed by:", fix=log.cmd("og help"))
        return 1
    print(f"{line(rest[0])}\n\n  {COMMANDS[rest[0]][1]}")
    return 0


def help_usage(problem: str = "", err: bool = True) -> None:
    page()


def ssh_usage(problem: str = "", err: bool = True) -> None:
    print(f"{line('ssh')}" if problem else f"{line('ssh')}\n\n  {COMMANDS['ssh'][1]}", file=sys.stderr if err else sys.stdout)


def ssh(argv: list[str]) -> int:
    """og ssh <name>: one name and nothing after it — `og ssh cub ls` must not open
    a session and drop `ls`. Needs `sbx setup ssh` once."""
    if len(argv) != 1 or not argv[0]:
        ssh_usage("og ssh takes one sandbox name")
        return 1
    os.execvp("ssh", ["ssh", f"{argv[0]}.sbx"])
    return 1
