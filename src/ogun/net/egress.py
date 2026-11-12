"""The registry's egress, per sandbox: a repo's own hosts (registry.json `egress`),
approved once per Mac, applied at create and every attach, and taken back when dropped."""

import os
import sys
from pathlib import Path

from ogun.core import boxes, files, log, paths, records, registry, sbx, settings
from ogun.net import ruletable


def _approvals() -> Path:
    return settings.path("SBX_EGRESS_APPROVED", paths.state_dir() / "approved-egress")


def _approved(g: dict) -> bool:
    """May this grant write? Read-only ones never do. A write grant is asked
    about once on this Mac, yes or no, and the answer kept outside every repo,
    so an edit to the registry alone never opens a host for writing; until it's
    yes, the host is reachable reading only."""
    if not g["write"]:
        return True
    key = f"{g['scope']}\t{g['host']}"
    f = _approvals()
    lines = f.read_text().splitlines() if f.is_file() else []
    if key in lines:
        return True
    if f"{key}\tdeclined" in lines:
        log.note(f"{g['host']}: you said no to sending data there, so it's reading only — to be asked again, delete its line in {log.path(f)}")
        return False
    boxes.callout("SENDING DATA TO A DOMAIN, NOT YET APPROVED ON THIS MAC",
                [f"Sandboxes of {g['scope']} may send data to {g['host']}: uploads, forms, API writes."]
                + ([f"Why: {g['for']}"] if g["for"] else [])
                + ["Until you say yes, they can only read from it. You're asked once on this Mac."])
    if not sys.stdin.isatty():
        log.warn(f"  {log.WARNING} no terminal to ask at, so {g['host']} is reading only for now — answer at a terminal:", err=True,
                 fix=log.cmd("og policy"))
        return False
    yes = input("    let them? [y/N] ").strip().lower() in ("y", "yes")
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(os.open(f, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as out:
        out.write(key + ("" if yes else "\tdeclined") + "\n")
    return yes


def egress_sync(sb: str, d: str, say: bool = True, cmd: str = "") -> bool:
    """This sandbox's rules brought in line with its repo's registry `egress`:
    each new host allowed (reading only unless the grant writes and this Mac
    approved it), and each one the registry dropped or changed removed, its
    allows only. Only what the record (`registry_egress`) shows og allowed is
    ever removed, and never a host its template or a secret grant also needs;
    no record, nothing changes. cmd: the og command running it,
    for its error lines (the sandbox's name, as `og <name>` attaches)."""
    cmd = cmd or sb
    f, rec = records.record_file(sb), records.read_record(sb)
    if rec is None:
        listed = " ".join(g["host"] for g in registry.egress(d, quiet=True))
        if listed:
            log.warn(f"  {log.WARNING} {sb} has no create record of og's (made outside og?), so the domains its registry entry lists "
                     "aren't allowed — recreate it, or allow them by hand:", err=True,
                     fix=log.cmd(f"og allow {sb} {listed} --read-only"))
        return True
    # a write grant not approved here reads only: approval is for writing
    want = {g["host"]: {**g, "write": g["write"] and _approved(g)} for g in registry.egress(d, quiet=not say)}
    have = {e["host"]: e for e in rec.get("registry_egress") or [] if isinstance(e, dict) and isinstance(e.get("host"), str)}
    keep = set(rec.get("egress") or []) | {h for s in rec.get("secrets") or [] if isinstance(s, dict) for h in s.get("hosts") or []}
    # access changed either way: its rule is replaced, never kept beside the new one
    gone = [h for h, e in have.items() if h not in want or bool(e.get("write")) != want[h]["write"]]
    left, good = remove_gone(sb, cmd, gone, want, keep) if gone else ([], True)
    for h in left:
        del have[h]
    new = [h for h in want if h not in have]
    if new:
        # recorded before they're allowed: a rule the record doesn't show is one no
        # later sync could ever remove. A save that fails allows nothing
        for h in new:
            g = want[h]
            have[h] = {"host": h, "write": g["write"], "for": g["for"], "scope": g["scope"]}
        rec["registry_egress"] = sorted(have.values(), key=lambda e: e["host"])
        try:
            files.write_json(f, rec, private=True)
        except OSError:
            log.warn(f"  {log.WARNING} couldn't save {sb}'s record in {log.path(f.parent)}, so nothing new was allowed — try again:", err=True,
                     fix=log.cmd("og policy"))
            return False
    for h in allow_new(sb, new, want, say):
        good = False
        del have[h]
    rec["registry_egress"] = sorted(have.values(), key=lambda e: e["host"])
    try:
        files.write_json(f, rec, private=True)
    except OSError:
        # the record then errs closed: a host removed above is still on it (the next
        # sync drops it, finding no rule), and one whose allow failed shows as allowed
        # (it stays unreachable; its own warning above has the og allow line)
        log.warn(f"  {log.WARNING} couldn't save {sb}'s record in {log.path(f.parent)} — try again:", err=True, fix=log.cmd("og policy"))
        good = False
    return good


def remove_gone(sb: str, cmd: str, gone: list[str], want: dict, keep: set[str]) -> tuple[list[str], bool]:
    """The rules of hosts leaving the registry (or whose access changed) removed, its
    allows only, never one keep (its template, a secret grant) still needs. The hosts
    that leave the record, and False when a rule couldn't be read or removed (said)."""
    rules = ruletable.read_rules()
    if rules is None:
        log.err(f"og {cmd}: couldn't read {sb}'s rules from sbx, so domains its registry entry no longer lists are still allowed — try again:",
                fix=log.cmd("og policy"))
        return [], False
    # a rule can hold several of these hosts (a secret grant allows its hosts as one):
    # each rule goes once, putting back only the hosts not leaving, as og net --rm does
    leaving = {h for h in gone if h not in keep}
    done: dict[str, bool] = {}
    left, good = [], True
    for h in gone:
        if h in leaving:
            # its allows only: a block on that host is yours, and stays
            mine = [r for r in rules if r["scope"] == f"sandbox:{sb}" and r["decision"] == "allow" and not ruletable.narrows(r["path"])
                    and any(x.lower().removesuffix(":443") == h for x in r["res"])]
            for r in mine:
                if r["id"] not in done:
                    done[r["id"]] = ruletable.rm_rule(cmd, r, [x for x in r["res"] if x.lower().removesuffix(":443") not in leaving])
            if not all(done[r["id"]] for r in mine):
                good = False
                continue
            # no rule left to remove (removed by hand): it only leaves the record
            if mine:
                why = "its registry entry no longer lists it" if h not in want else "its access changed in the registry; allowed again below"
                log.note(f"{sb}: {h} removed ({why})")
                log.record(f"{sb}: {h} removed ({why})")
        left.append(h)
    return left, good


def allow_new(sb: str, new: list[str], want: dict, say: bool) -> list[str]:
    """Each new host allowed for this sandbox, reading only unless its grant writes;
    the ones sbx refused (each said with its og allow)."""
    refused = []
    for h in new:
        g = want[h]
        how = [] if g["write"] else ["--method", "GET,HEAD"]
        if sbx.run("policy", "allow", "network", "--sandbox", sb, h, *how).returncode:
            log.warn(f"  {log.WARNING} couldn't allow {h} for {sb} — by hand:", err=True,
                     fix=log.cmd(f"og allow {sb} {h}" + ("" if g["write"] else " --read-only")))
            refused.append(h)
            continue
        what = f"{sb} may reach {h}{'' if g['write'] else ' (reading only)'}, as its registry entry lists"
        if say:
            log.note(what)
        log.record(what)
    return refused
