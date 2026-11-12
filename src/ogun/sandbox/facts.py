"""A sandbox's create record: what it was made with (its mounts, its OpenAPPA), kept in
og's state folder for og ls, attach and rm."""

import datetime
import os
import re

from ogun.core import files, naming, records
from ogun.sandbox import appa, choose

# ── the record: what was decided for a sandbox, kept with it (0600, mounted nowhere) ──

def _unq(v: str) -> str:
    """A YAML scalar as envfile._yamlq wrote it: double-quoted, \\\\ and \\" escaped."""
    v = v.strip()
    return re.sub(r"\\(.)", r"\1", v[1:-1]) if len(v) >= 2 and v[0] == v[-1] == '"' else v


def mounts(yaml: str) -> list[dict]:
    """additionalWorkspaces from the .sbxenv.yaml this create wrote."""
    out, cur, sec = [], None, ""
    for line in yaml.splitlines():
        if re.match(r"^\S", line):
            sec, cur = line.split(":", 1)[0], None
            continue
        m = re.match(r"^  - path: (.*)$", line)
        if sec == "additionalWorkspaces" and m:
            cur = {"path": _unq(m.group(1)), "read_only": False}
            out.append(cur)
        elif cur is not None and re.match(r"^    readOnly: true\s*$", line):
            cur["read_only"] = True
    return out


def record(name: str, kind: str, ws: str, decision: dict | None, yaml: str, egress: list[str]) -> bool:
    """The sandbox's record: its template, mounts and runtime egress, as JSON
    the secret grants add to later, written whole. A yaml that names another
    sandbox (another create wrote over it) is no record of this one. The
    .sbxenv.yaml can't serve as the record: the next create from the same folder
    writes over it, even while this one's `sbx env create` runs."""
    if not naming.name_ok(name):   # the name becomes a path
        return False
    if not yaml:
        choose.skipped("could not record this sandbox's template and mounts: no copy of its .sbxenv.yaml")
        return False
    if not re.search(r"^name: " + re.escape(name) + r"$", yaml, re.M):
        choose.skipped("could not record this sandbox's template and mounts: its .sbxenv.yaml names another sandbox")
        return False
    try:
        out = records.record_file(name)
        out.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(out.parent, 0o700)
        rec = {"version": 1, "sandbox": name, "kind": kind,
               "created": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "workspace": ws, "template": decision, "mounts": mounts(yaml), "egress": [x for x in egress if x],
               "secrets": []}   # filled by the secret grants once applied
        files.write_json(out, rec, private=True)
    except OSError:
        choose.skipped("could not record this sandbox's template and mounts")
        return False
    return True


def has_appa(name: str) -> bool:
    """The sandbox's record says it was made with OpenAPPA."""
    try:
        return bool((records.read_record(name) or {}).get("appa", {}).get("version"))
    except AttributeError:
        return False


def record_appa(name: str) -> bool:
    """OpenAPPA in the sandbox's record, at the pinned version: attach then
    starts clappa (session.start)."""
    try:
        f = records.record_file(name)
        rec = records.read_record(name)
        if rec is None:
            return False
        rec["appa"] = {"version": appa.lock("version")}
        files.write_json(f, rec, private=True)
    except (OSError, ValueError, AttributeError, TypeError):
        return False
    return True
