"""`og policy`: this Mac's safety settings (re)applied for every sandbox: the baseline,
sbx's default rules off, the ssh-agent guard, and each sandbox's pushes and egress."""

import re

from ogun.core import boxes, log, naming, sbx
from ogun.net import baseline, egress, pushrules, ruletable

POLICY_HELP = dict(
    about="Apply this Mac's safety settings to every sandbox.",
    forms=[("og policy", "the baseline domains, each sandbox's GitHub pushes and registry domains, "
                         "allows covering all of github.com named for removal, ssh-agent forwarding off")],
    notes=["It takes no sandbox: it's for every one. For one sandbox: og allow <name> <domain>…"],
    examples=["og policy", "og -v policy"],
)


def policy_usage(problem: str = "", err: bool = True) -> None:
    boxes.usage("policy", "", problem=problem, err=err, **POLICY_HELP)


def policy(argv: list[str]) -> int:
    """This Mac's safety settings, for every sandbox: the baseline, each
    sandbox's push rules and registry egress, the removal of any allow that covers
    github.com (printed, never run), and ssh-agent forwarding off."""
    # one set of rules for the whole Mac: a name here would read as scoping it
    # to that sandbox, so it is refused, never ignored
    if argv:
        log.err("og policy takes no arguments — it sets rules for every sandbox on this Mac; for one sandbox:",
                fix=log.cmd("og allow <name> <domain>..."))
        return 1
    b = baseline.baseline_lists()
    summary: list[tuple[str, str]] = []
    log.step(f"baseline egress: {b['SBX_BASELINE_DOMAINS']}")
    base_ok = baseline.baseline()
    summary.append(("baseline", f"[ok]{log.DONE} applied[/]" if base_ok else f"[error]{log.FAILED} failed[/] (above)"))
    log.step("GitHub pushes: each sandbox to its own repos")
    listing = sbx.ls()
    unlisted = listing is None   # no list is no answer: never "no sandboxes"
    if unlisted:
        log.err("og policy: sbx couldn't list its sandboxes, so their pushes and domains weren't set")
    each = sandboxes(listing or "")
    push_row, push_ok = pushes(each, unlisted)
    dom_row, dom_ok = domains(each, unlisted)
    summary += [push_row, dom_row]
    # the whole-host allows anyone added; sbx's own defaults are the baseline's to remove
    rules = ruletable.read_rules()
    unread = rules is None   # unread rules are unknown, never "none left"
    if unread:
        log.err("og policy: sbx couldn't list its rules, so github.com wasn't checked; to try again, run:",
                fix=log.cmd("og policy"))
    added = [(r["scope"], res) for r in rules or [] if r["via"] != "default" and r["type"] == "network" and r["decision"] == "allow"
             for res in r["res"]]
    open_gh = len(github_wide(added))
    summary.append(("github.com", f"[error]{log.FAILED} not checked[/] (above)" if unread
                    else f"[warn]{log.WARNING} {_count(open_gh, 'rule covers', 'rules cover')} it[/] (above)" if open_gh
                    else f"[ok]{log.DONE} only per-repo pushes[/]"))
    log.step("ssh-agent forwarding: must be off")
    agent_ok = baseline.ssh_agent_off()
    summary.append(("ssh-agent", f"[ok]{log.DONE} off[/]" if agent_ok else f"[error]{log.FAILED} not off yet[/] (above)"))
    log.record("policy applied: " + "; ".join(f"{k} {re.sub(r'\[/?[a-z]*\]', '', v)}" for k, v in summary))
    boxes.table("og policy", summary)
    return int(not (base_ok and not unlisted and push_ok and dom_ok and not unread and agent_ok))


def sandboxes(listing: str) -> list[tuple[str, str]]:
    """Each sandbox `sbx ls` lists under a name og makes, with its workspace."""
    out = []
    for line in listing.splitlines()[1:]:
        f = line.split()
        if f and naming.name_ok(f[0]) and (w := sbx.workspace(f[0], listing)):
            out.append((f[0], w))
    return out


def pushes(each: list[tuple[str, str]], unlisted: bool) -> tuple[tuple[str, str], bool]:
    """Every sandbox's own push rules, so no sandbox needs a whole-host github.com
    allow to push: the summary row, and whether all held."""
    pushed, unpushed = [], []
    for name, w in each:
        # a failure names its repos itself
        (pushed if pushrules.push_rules(name, w, say=False) else unpushed).append(name)
    return ("pushes", f"[error]{log.FAILED} not set[/] (above)" if unlisted
            else f"[error]{log.FAILED} {len(unpushed)} failed[/] (above)" if unpushed
            else f"[ok]{log.DONE} {_count(len(pushed), 'sandbox', 'sandboxes')}[/]" if pushed else "no sandboxes"), not unpushed


def domains(each: list[tuple[str, str]], unlisted: bool) -> tuple[tuple[str, str], bool]:
    """The domains each repo's registry entry lists: one removed there closes now,
    not at its next attach. The summary row, and whether every sandbox is as listed."""
    log.step("Domains: each sandbox to the ones its repo's registry entry lists")
    synced, unsynced = [], []
    for name, w in each:
        (synced if egress.egress_sync(name, w, say=False, cmd="policy") else unsynced).append(name)
    return ("domains", f"[error]{log.FAILED} not set[/] (above)" if unlisted
            else f"[warn]{log.WARNING} {len(unsynced)} not as listed[/] (above)" if unsynced
            else f"[ok]{log.DONE} {_count(len(synced), 'sandbox', 'sandboxes')} as listed[/]" if synced else "no sandboxes"), not unsynced


def github_wide(added: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Any allow, for every sandbox or one, whose pattern covers github.com (`*.com`,
    `**`, one added by hand): each undoes the push
    limit where it applies. Named with its removal; never removed here."""
    wide = [(sc, r) for sc, r in added if ruletable.covers_github(r)]
    for sc, r in wide:
        where = "every sandbox" if sc == "all" else sc.removeprefix("sandbox:")
        what = "all of github.com is allowed" if ruletable.is_github(r) else f"{r} covers all of github.com"
        log.warn(f"  {log.WARNING} {what} for {where}, so {'any sandbox' if sc == 'all' else where} can push to any of your repos — to remove it:",
                 err=True, fix=f"{ruletable.rm_cmd('--all' if sc == 'all' else where, r)}, then {log.cmd('og policy')}")
    return wide


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"
