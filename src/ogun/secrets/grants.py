"""Secret grants: the 1Password values a sandbox is handed, declared in
registry.json `secrets` (docs/secrets.md#secret-grants).

ogun.secrets.rules reads them. A top-level grant reaches every sandbox on the Macs its
`profiles` name (no profile → none: fails closed); a repo's grant reaches only
that repo's sandboxes, behind the gate `template` and `mcp` take. Applied per
sandbox at create, through `og pass`: the sandbox holds a placeholder, the
proxy swaps in the value only on the grant's hosts, and its hosts are allowed
for that sandbox alone. Never global: a global proxy secret reaches sandboxes
nobody created with this grant in mind.

A grant travels as one line, scope TAB env TAB hosts TAB item TAB field, as the
reader prints it; an approval is that line and its vault. It decides who gets
a secret, so a change here deserves a secrets review."""

from pathlib import Path

from ogun.core import files, log, naming, paths, records, sbx
from ogun.secrets import approval, sandboxenv


def _list(r, key: str) -> list:
    v = r.get(key) if isinstance(r, dict) else None
    return v if isinstance(v, list) else []


def egress_drop(sb: str, also: list[str], hosts: list[str]) -> None:
    """Take back a sandbox's egress to these hosts, except one its record still
    justifies (a recorded grant's host, its template's runtime egress, or the
    registry's egress) or the caller still needs (also: a grant applied in the
    same batch, not recorded yet). og can't tell a hand-made `og allow` for a
    host from a grant's, so each removal is said, with how to restore it."""
    rec = records.record_file(sb)
    r = records.read_record(sb)
    # a registry grant keeps the whole host only if it writes: one that reads only
    # must not inherit the secret's every-method allow
    keep = {h for s in _list(r, "secrets") if isinstance(s, dict) for h in (s.get("hosts") or []) if isinstance(h, str)}
    keep |= {h for h in _list(r, "egress") if isinstance(h, str)}
    keep |= {e.get("host") for e in _list(r, "registry_egress") if isinstance(e, dict) and e.get("write") is True}
    keep |= set(also)
    for h in hosts:
        if h in keep:
            continue
        if sbx.run("policy", "rm", "network", "--sandbox", sb, "--resource", h).returncode == 0:
            log.note(f"removed {sb}'s egress to {h} (still needed? {log.cmd(f'og allow {sb} {h}')})", err=True)
            # sbx removes by host, the registry's read-only rule with it: off the record,
            # so the registry egress sync sets it again (this attach's, or og policy's)
            r = records.read_record(sb)
            if any(isinstance(e, dict) and e.get("host") == h for e in _list(r, "registry_egress")):
                try:
                    r["registry_egress"] = [e for e in r["registry_egress"] if not (isinstance(e, dict) and e.get("host") == h)]
                    files.write_json(rec, r, private=True)
                except OSError:
                    log.warn(f"  {log.WARNING} {h}: reading it may not come back by itself; allow it again:", err=True,
                             fix=log.cmd(f"og allow {sb} {h} --read-only"))
        else:
            log.warn(f"  {log.WARNING} could not remove {sb}'s egress to {h}; by hand:", err=True,
                     fix=log.cmd(f"sbx policy rm network --sandbox {sb} --resource {h}"))
        keep.add(h)   # once per host


def apply(sb: str, want: list[str], listing: str | None = None) -> tuple[list[str], bool]:
    """Each grant's hosts allowed for this sandbox only, its value registered for
    it by `og pass`. One the sandbox already holds exactly (same variable, hosts
    and op:// source, e.g. passed by hand) is adopted: its
    placeholder is exported and the grant counts as applied, never registered
    again (sbx refuses a second one, and a second would be a placeholder nothing
    swaps). The listing that decides it is the caller's when given, so caller and
    adoption agree on it. Returns the grants that were applied, and False when
    one failed, naming the command to run by hand; a failed one takes back the
    egress it opened, since nothing records it. Progress goes to stderr."""
    if not want:
        return [], True
    log.step(f"secret grants ({sb} only)", err=True)
    # every scope's registrations: a variable also registered for every sandbox can't be
    # granted too. Unreadable: nothing is granted, since any grant could be the duplicate
    # that leaves the sandbox unable to start
    p = sbx.run("secret", "ls")
    if p.returncode != 0:
        log.warn(f"  {log.WARNING} could not read sbx's registered secrets, so no grant was applied "
                 "(one could clash with a global one) — attach again", err=True)
        return [], False
    every = p.stdout
    # a listing sbx failed to finish adopts nothing: it may lack a second matching row
    if listing is None:
        q = sbx.run("secret", "ls", "--sandbox", sb)
        listing = q.stdout if q.returncode == 0 else ""
    ok, applied, ok_hosts, vault = True, [], [], approval.grants_vault()
    for g in want:
        done = apply_one(sb, g, every, listing, vault, ok_hosts)
        if done:
            applied.append("\t".join(approval.fields(g, 5)))
            ok_hosts += approval.fields(g, 5)[2].split(",")
        elif done is False:
            ok = False
    return applied, ok


def apply_one(sb: str, g: str, every: str, listing: str, vault: str, kept: list[str]) -> bool | None:
    """One grant applied to the sandbox (True), or not (False, said, and the egress
    it opened taken back unless a grant applied in kept still uses it); None when
    it names no variable. every is sbx's registrations in every scope, listing the
    sandbox's own."""
    _, env, hosts, item, field = approval.fields(g, 5)
    if not env:
        return None
    fl = "" if field == "credential" else f" --field {field}"
    each = hosts.split(",")
    # sbx refuses to start a sandbox that would hold one variable twice, so a grant on top
    # of a global registration would leave the sandbox unstartable: not applied, said
    gph = sandboxenv.global_placeholders(env, every)
    if gph:
        log.warn(f"  {log.WARNING} {env} is also registered for every sandbox ({' '.join(gph)}), and sbx won't start a "
                 "sandbox holding it twice — not granted. Grants replace it; remove each, then attach again:", err=True,
                 fix=log.cmd("sbx secret rm --placeholder <it> -f"))
        return False
    if sbx.run("policy", "allow", "network", "--sandbox", sb, hosts).returncode != 0:
        log.warn(f"  {log.WARNING} could not allow {hosts} for {env}; by hand:", err=True,
                 fix=log.cmd(f"og allow {sb} {' '.join(each)}"))
        return False
    phs = sandboxenv.placeholders(sb, env, hosts, f"op://{vault}/{item}/{field}", listing)
    if phs:
        if len(phs) > 1:
            log.warn(f"  {log.WARNING} {env} is registered for {sb} more than once ({' '.join(phs)}); keep one, "
                     "removing each other, then attach again:", err=True,
                     fix=log.cmd(f"sbx secret rm --sandbox {sb} --placeholder <each other>"))
        elif sandboxenv.export(sb, env, phs[0]):
            log.note(f"{env} was already registered for {sb} ({phs[0]}): kept and recorded, not registered again", err=True)
            return True
        else:
            log.warn(f"  {log.WARNING} {env} is already registered for {sb} ({phs[0]}), but its env couldn't be written "
                     f"— once '{sb}' is reachable, attach again", err=True)
        egress_drop(sb, kept, each)
        return False
    if sandboxenv.quiet_pass([sb, env, *each, "--item", item, "--field", field]) == 0:
        return True
    log.warn(f"  {log.WARNING} {env} not registered; by hand:", err=True,
             fix=log.cmd(f"og pass {sb} {env} {' '.join(each)} --item {item}{fl}"))
    egress_drop(sb, kept, each)
    return False


def facts(name: str, applied: list[str], revoked: list[tuple[str, str]] = ()) -> bool:
    """Grants actually applied, added to the sandbox's record (one for the same
    scope and variable replaces its entry), and revoked ones (scope, env)
    dropped: each only as its 1Password source, never a value. Warned, never
    fatal, like the record itself."""
    if not naming.name_ok(name):
        return False
    try:
        rec = records.record_file(name)
        r = records.read_record(name)
        if r is None:
            raise ValueError("no readable record")
        have = r.get("secrets") if isinstance(r.get("secrets"), list) else []
        gone = set(revoked)
        have = [h for h in have if not (isinstance(h, dict) and (h.get("scope"), h.get("env")) in gone)]
        for g in (x.split("\t") for x in applied):
            if len(g) == 5:
                new = {"scope": g[0], "env": g[1], "hosts": g[2].split(","), "source": f"op://{approval.grants_vault()}/{g[3]}/{g[4]}"}
                key = (new["scope"], new["env"])
                at = [i for i, h in enumerate(have) if isinstance(h, dict) and (h.get("scope"), h.get("env")) == key]
                if at:
                    have[at[0]] = new
                else:
                    have.append(new)
        r["secrets"] = have
        files.write_json(rec, r, private=True)
    except (OSError, ValueError, AttributeError, TypeError):
        log.warn(f"  {log.WARNING} could not record this sandbox's secret grants", err=True)
        return False
    return True


def _recorded(r) -> list[tuple[str, str, str, str]]:
    """The record's grants: scope, env, hosts (comma-joined), op:// source. An
    entry that doesn't read that way is left out."""
    out = []
    for s in _list(r, "secrets"):
        if not isinstance(s, dict):
            continue
        scope, env, hosts, src = s.get("scope"), s.get("env"), s.get("hosts"), s.get("source")
        if (isinstance(scope, str) and isinstance(env, str) and isinstance(src, str)
                and isinstance(hosts, list) and all(isinstance(h, str) for h in hosts)):
            out.append((scope, env, ",".join(hosts), src))
    return out


def catch_up(sb: str, ws: str) -> None:
    """On attach: the grants this workspace's sandboxes get and this Mac approved,
    that the sandbox's record doesn't show as applied (its create stopped early,
    or the grant is newer), applied now and recorded. One already applied is
    never registered again: that would mint a new placeholder. No record:
    nothing is known, so nothing is applied."""
    if not ws or not naming.name_ok(sb):
        return
    rec, vault = records.record_file(sb), approval.grants_vault()
    # first: with no record nothing is known, so nothing is asked about either
    if not rec.is_file():
        if approval.grants(ws, quiet=True):
            log.warn(f"  {log.WARNING} {sb} has no create record, so its secret grants can't be checked — "
                     "recreate it, or og pass by hand", err=True)
        return
    # a grant the record holds that the registry no longer gives: still live in the proxy, so revoke it
    stale(sb, ws, rec)
    want = approval.approved(ws)
    if not want:
        return
    have = _recorded(records.read_record(sb))
    missing = []
    for g in want:
        scope, env, hosts, item, field = approval.fields(g, 5)
        if not env:
            continue
        if (scope, env, hosts, f"op://{vault}/{item}/{field}") in have:
            continue
        # the same scope and variable still on the record: an old grant the stale pass couldn't revoke.
        # The new one would replace its entry, leaving the old placeholder live with nothing to revoke it
        if any((s, e) == (scope, env) for s, e, _, _ in have):
            log.warn(f"  {log.WARNING} {env} ({scope}): its old grant is still live (not revoked, above) — "
                     "the new one waits for the next attach", err=True)
            continue
        missing.append(g)
    if missing and not give(sb, missing):
        log.warn(f"  {log.WARNING} not every secret grant was applied (above)", err=True)


def stale(sb: str, ws: str, rec: Path) -> None:
    """Each grant the record shows that the registry no longer gives this
    workspace (removed, narrowed, moved to another owner, its source changed) is
    revoked, leaves the record, and its egress goes, unless a kept grant or the
    template's runtime egress needs a host. Revoking needs no approval: it only
    takes away."""
    rows = _recorded(records.read_record(sb))
    if not rows:
        return
    # what the registry grants now; if it can't be read, nothing is known to be gone
    if paths.read_registry() is None:
        return
    vault, now = approval.grants_vault(), set()
    for g in approval.grants(ws, quiet=True):
        f = g.split("\t")
        if len(f) == 5:
            now.add((f[0], f[1], f[2], f"op://{vault}/{f[3]}/{f[4]}"))
    gone = [r for r in rows if r not in now]
    if not gone:
        return
    revoked = revoke(sb, gone, f"is no longer granted to {sb}")
    if not revoked:
        return
    facts(sb, [], [(s, e) for s, e, _, _ in revoked])
    egress_drop(sb, [], [h for _, _, hosts, _ in revoked for h in hosts.split(",")])


def revoke(sb: str, gone: list[tuple[str, str, str, str]], why: str) -> list[tuple[str, str, str, str]]:
    """Each grant's (scope, env, hosts, op:// source) placeholder, found in this
    sandbox's own rows of `sbx secret ls`, removed from the proxy, and its export
    cleared from the sandbox's env (only that exact placeholder: a value passed
    again since stays). Returns the grants revoked. One not found or not
    removable is said, with the commands, and left out: never guessed at, and
    the next attach tries again. Egress and the record are the caller's."""
    p = sbx.run("secret", "ls", "--sandbox", sb)
    listing = p.stdout or ""
    full = p.returncode == 0 and sandboxenv.full(listing, sb)
    out = []
    for scope, env, hosts, src in gone:
        if not env:
            continue
        # this sandbox's rows for exactly that grant
        phs = sandboxenv.placeholders(sb, env, hosts, src, listing)
        if not phs and full:
            # already gone from the proxy (removed by hand, as the warning below says to): nothing to
            # remove, so it counts as revoked. Its export, if any, names a placeholder nothing swaps now
            log.warn(f"  {log.WARNING} {env} ({scope}) {why} — its placeholder is already gone from sbx, "
                     "so it leaves the record", err=True)
            out.append((scope, env, hosts, src))
            continue
        if not phs:
            log.warn(f"  {log.WARNING} {env} ({scope}) {why}, but its placeholder wasn't found; find it, then remove it:",
                     err=True, fix=f"{log.cmd(f'sbx secret ls --sandbox {sb}')}, then "
                                   f"{log.cmd(f'sbx secret rm --sandbox {sb} --placeholder <it>')}")
            continue
        # each placeholder removed has its export cleared at once: if a later one fails, the next
        # attach finds only what's left in the listing, and would never clear this one's export
        failed = False
        for ph in phs:
            # -f: no y/N, which nobody would see
            if sbx.run("secret", "rm", "--sandbox", sb, "--placeholder", ph, "-f").returncode != 0:
                log.warn(f"  {log.WARNING} could not revoke {env} from {sb}; by hand:", err=True,
                         fix=log.cmd(f"sbx secret rm --sandbox {sb} --placeholder {ph}"))
                failed = True
                continue
            sandboxenv.unexport(sb, env, ph)
        if failed:
            continue
        log.warn(f"  {log.WARNING} {env} ({scope}) {why} — revoked (the proxy may serve it until the sandboxes daemon restarts)",
                 err=True)
        out.append((scope, env, hosts, src))
    return out


def give(sb: str, want: list[str]) -> bool:
    """Apply these approved grants and record them, or not at all: a grant live in
    the proxy with no record could never be revoked (nor would the next attach
    know it was there). No create record: nothing is applied. A record that
    can't take the grants just applied: they are taken back."""
    if not want:
        return True
    if not records.record_file(sb).is_file():
        log.warn(f"  {log.WARNING} {sb} has no create record, so its secret grants weren't applied "
                 "(they couldn't be tracked) — recreate it, or og pass by hand", err=True)
        return False
    # what the sandbox held before, read once: adoption decides from this same listing, so a
    # failed record takes back only what this call registered, never a registration it found
    # (a listing that failed adopts nothing, and then nothing is mistaken for adopted)
    p = sbx.run("secret", "ls", "--sandbox", sb)
    before = p.stdout if p.returncode == 0 else ""
    applied, ok = apply(sb, want, before)
    if not applied:
        return ok
    if facts(sb, applied):
        return ok
    log.warn(f"  {log.WARNING} could not record the secret grants just applied to {sb} — taking it back", err=True)
    # an adopted grant keeps its registration (it was there before), but loses the export
    # adopting wrote: like every other grant, none is left usable and unrecorded
    vault, made = approval.grants_vault(), []
    for g in applied:
        scope, env, hosts, item, field = approval.fields(g, 5)
        src = f"op://{vault}/{item}/{field}"
        phs = sandboxenv.placeholders(sb, env, hosts, src, before)
        if phs:
            for ph in phs:
                sandboxenv.unexport(sb, env, ph)
                log.warn(f"  {log.WARNING} {env} was already registered for {sb} ({ph}): kept, but not exported "
                         "until the next attach can record it", err=True)
        else:
            made.append((scope, env, hosts, src))
    if made:
        revoke(sb, made, "was applied but couldn't be recorded")
    # every grant's egress goes, adopted or made, unless a recorded grant or the template needs it
    egress_drop(sb, [], [h for g in applied for h in approval.fields(g, 5)[2].split(",")])
    return False
